"""Videos de YouTube: yt-dlp busca y mpv reproduce a pantalla completa (ver plan §6.3).

mpv se controla por su IPC (JSON por un socket Unix): pausa, adelantar, cerrar y mensajes en
pantalla («Te escucho…») mientras el video tapa la interfaz de VOXA.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from voxa.services.process import CommandNotFound, CommandRunner, run_command

log = logging.getLogger(__name__)

# Se descartan transmisiones en vivo y, si hay opciones, los videos muy cortos (shorts) o eternos.
_GOOD_LENGTH = (90, 3 * 3600)
_SEARCH_RESULTS = 5
_FIELDS = "%(id)s\t%(title)s\t%(duration)s\t%(channel)s\t%(live_status)s"
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{6,20}")

# Tocar la pantalla pausa; dos toques cierran (en una pantalla táctil no hay teclado).
_INPUT_CONF = """\
MBTN_LEFT cycle pause
MBTN_LEFT_DBL quit
ESC quit
q quit
"""


class VideoUnavailable(Exception):
    """No se puede buscar o reproducir: falta yt-dlp o mpv, sin red, YouTube cambió…"""


class VideoNotFound(Exception):
    pass


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    duration: float | None = None
    channel: str | None = None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


class VideoSearch(Protocol):
    async def search(self, query: str) -> Video: ...


class VideoPlayer(Protocol):
    @property
    def current(self) -> Video | None: ...
    async def play(self, video: Video) -> None: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...
    async def seek(self, seconds: int) -> None: ...
    async def close(self) -> None: ...
    async def show_text(self, text: str, seconds: float = 2.0) -> None: ...


def _duration(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def parse_results(lines: str) -> list[Video]:
    """Las líneas de ``yt-dlp --print`` (id, título, duración, canal, en vivo), sin transmisiones en vivo."""
    videos = []
    for line in lines.splitlines():
        parts = line.split("\t")
        if len(parts) < 5 or not _VIDEO_ID.fullmatch(parts[0]) or parts[4] in ("is_live", "is_upcoming"):
            continue
        videos.append(Video(parts[0], parts[1], _duration(parts[2]), parts[3] if parts[3] != "NA" else None))
    return videos


def pick(lines: str) -> Video | None:
    """Primer resultado que se pueda ver completo; si ninguno dura «bien», el primero que no sea en vivo."""
    videos = parse_results(lines)
    low, high = _GOOD_LENGTH
    good = [v for v in videos if v.duration is not None and low <= v.duration <= high]
    return (good or videos or [None])[0]


class YtDlpSearch:
    def __init__(self, command: Sequence[str] = ("yt-dlp",), run: CommandRunner = run_command) -> None:
        self._command = tuple(command)
        self._run = run

    async def search(self, query: str) -> Video:
        args = [
            *self._command,
            "--ignore-config",
            "--no-warnings",
            "--flat-playlist",
            "--print",
            _FIELDS,
            f"ytsearch{_SEARCH_RESULTS}:{query}",
        ]
        try:
            result = await self._run(args, timeout=25.0)
        except CommandNotFound as exc:
            raise VideoUnavailable("yt-dlp no está instalado") from exc
        except asyncio.TimeoutError as exc:
            raise VideoUnavailable("YouTube no respondió a tiempo") from exc
        if result.returncode != 0:
            raise VideoUnavailable(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "yt-dlp falló")
        video = pick(result.stdout)
        if video is None:
            raise VideoNotFound(query)
        return video


def _runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())


class MpvPlayer:
    """Un solo mpv a la vez; al terminar o cerrarse avisa con ``on_end`` (la pantalla vuelve al frente)."""

    def __init__(
        self,
        command: Sequence[str] = ("mpv",),
        ytdlp: str = "yt-dlp",
        max_height: int = 720,
        on_end: Callable[[], None] | None = None,
        socket_path: Path | None = None,
    ) -> None:
        self._command = tuple(command)
        self._ytdlp = shutil.which(ytdlp) or ytdlp
        self._max_height = max_height
        self.on_end = on_end
        self._socket = socket_path or _runtime_dir() / f"voxa-mpv-{os.getpid()}.sock"
        self._proc: asyncio.subprocess.Process | None = None
        self._watch: asyncio.Task | None = None
        self._current: Video | None = None

    @property
    def current(self) -> Video | None:
        return self._current

    def arguments(self, video: Video, input_conf: Path) -> list[str]:
        h = self._max_height
        return [
            *self._command,
            "--fullscreen",
            "--no-terminal",
            "--force-window=immediate",
            "--keep-open=no",
            "--hwdec=auto",
            f"--ytdl-format=bestvideo[height<={h}]+bestaudio/best[height<={h}]/best",
            f"--script-opts=ytdl_hook-ytdl_path={self._ytdlp},osc-windowcontrols=yes",
            f"--input-ipc-server={self._socket}",
            f"--input-conf={input_conf}",
            "--osd-font-size=44",
            f"--title=VOXA · {video.title.replace('$', '')}",  # mpv expande ${...} en el título
            video.url,
        ]

    async def play(self, video: Video) -> None:
        await self.close()
        input_conf = _runtime_dir() / "voxa-mpv-input.conf"
        input_conf.write_text(_INPUT_CONF, encoding="utf-8")
        with contextlib.suppress(FileNotFoundError):
            self._socket.unlink()
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.arguments(video, input_conf),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise VideoUnavailable("mpv no está instalado") from exc
        self._current = video
        self._watch = asyncio.create_task(self._wait(self._proc))

    async def _wait(self, proc: asyncio.subprocess.Process) -> None:
        code = await proc.wait()
        if proc is not self._proc:
            return  # lo cerramos para poner otro
        log.info("mpv terminó (código %s)", code)
        self._proc, self._current = None, None
        if self.on_end:
            self.on_end()

    async def _command_ipc(self, *command: object) -> None:
        if self._proc is None:
            return
        await mpv_command(self._socket, *command)

    async def pause(self) -> None:
        await self._command_ipc("set_property", "pause", True)

    async def resume(self) -> None:
        await self._command_ipc("set_property", "pause", False)

    async def seek(self, seconds: int) -> None:
        await self._command_ipc("seek", seconds, "relative")

    async def show_text(self, text: str, seconds: float = 2.0) -> None:
        await self._command_ipc("show-text", text, int(seconds * 1000))

    async def close(self) -> None:
        proc, self._proc, self._current = self._proc, None, None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 3.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        with contextlib.suppress(FileNotFoundError):
            self._socket.unlink()


_REQUEST_IDS = itertools.count(1)


async def mpv_command(socket: Path, *command: object) -> dict | None:
    """Una orden por el IPC de mpv; la respuesta (o ``None`` si mpv no contesta)."""
    request = {"command": list(command), "request_id": next(_REQUEST_IDS)}
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(socket)), 2.0)
    except (OSError, asyncio.TimeoutError, AttributeError) as exc:  # AttributeError: sin sockets Unix (Windows)
        log.warning("No pude hablar con mpv: %s", exc)
        return None
    try:
        writer.write(json.dumps(request).encode() + b"\n")
        await writer.drain()
        # Llegan también eventos; se espera la respuesta a esta orden (o se rinde pronto).
        with contextlib.suppress(asyncio.TimeoutError, ValueError):
            return await asyncio.wait_for(_reply(reader, request["request_id"]), 2.0)
        return None
    finally:
        writer.close()


async def _reply(reader: asyncio.StreamReader, request_id: int) -> dict | None:
    while line := await reader.readline():
        message = json.loads(line)
        if message.get("request_id") == request_id:
            return message
    return None
