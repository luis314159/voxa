"""Música desde YouTube: gratis, sin cuenta y sin configurar nada (yt-dlp busca, mpv toca solo el audio).

Es la música de VOXA mientras no hay Spotify (o si Spotify no responde). Cada orden arma una cola
con varias canciones de la búsqueda, para que la música siga: «siguiente», «anterior», pausa y
aleatorio van por el IPC de mpv. Lo que es de una cuenta (Me gusta, playlists propias, pasar la
música a otro dispositivo) es de Spotify.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
from typing import Sequence

from voxa.services.music_backend import BackendUnavailable, NotSupported, NothingFound, NowPlaying, PlayResult
from voxa.services.process import CommandNotFound, CommandRunner, run_command
from voxa.services.video import Video, _runtime_dir, mpv_command, parse_results

log = logging.getLogger(__name__)

_RESULTS = 12
_SONG_LENGTH = (90, 12 * 60)  # canciones, no mezclas de 3 horas ni shorts
_SEARCH = {
    "artist": "{q} canciones",
    "playlist": "{q} música",
    "album": "{q} álbum completo",
    "track": "{q}",
}


def search_text(query: str, kind: str | None) -> str:
    return _SEARCH.get(kind or "", "{q}").format(q=query)


def songs(lines: str) -> list[Video]:
    """Los resultados que parecen canciones (en el orden de YouTube); si ninguno, los que no son en vivo."""
    videos = parse_results(lines)
    low, high = _SONG_LENGTH
    good = [v for v in videos if v.duration is not None and low <= v.duration <= high]
    return good or videos


class YouTubeMusic:
    name = "youtube"

    def __init__(
        self,
        ytdlp: Sequence[str] = ("yt-dlp",),
        mpv: Sequence[str] = ("mpv",),
        run: CommandRunner = run_command,
    ) -> None:
        self._ytdlp = tuple(ytdlp)
        self._mpv = tuple(mpv)
        self._run = run
        self._socket = _runtime_dir() / f"voxa-musica-{os.getpid()}.sock"
        self._proc: asyncio.subprocess.Process | None = None
        self._queue: list[Video] = []

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def _search(self, text: str) -> list[Video]:
        args = [*self._ytdlp, "--ignore-config", "--no-warnings", "--flat-playlist", "--print",
                "%(id)s\t%(title)s\t%(duration)s\t%(channel)s\t%(live_status)s", f"ytsearch{_RESULTS}:{text}"]
        try:
            result = await self._run(args, timeout=25.0)
        except CommandNotFound as exc:
            raise BackendUnavailable("yt-dlp no está instalado") from exc
        except asyncio.TimeoutError as exc:
            raise BackendUnavailable("YouTube no respondió a tiempo") from exc
        if result.returncode != 0:
            raise BackendUnavailable(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "yt-dlp falló")
        return songs(result.stdout)

    async def play(self, query: str, kind: str | None = None) -> PlayResult:
        found = await self._search(search_text(query, kind))
        if not found:
            raise NothingFound(query)
        await self._start(found)
        first = found[0]
        if kind == "track":
            return PlayResult(first.title, first.channel, "track")
        return PlayResult(query, kind=kind if kind in ("artist", "playlist") else None)

    def arguments(self, videos: list[Video]) -> list[str]:
        ytdlp = shutil.which(self._ytdlp[0]) or self._ytdlp[0]
        return [
            *self._mpv,
            "--no-video",
            "--no-terminal",
            "--idle=no",
            "--ytdl-format=bestaudio/best",
            f"--script-opts=ytdl_hook-ytdl_path={ytdlp}",
            f"--input-ipc-server={self._socket}",
            *(v.url for v in videos),
        ]

    async def _start(self, videos: list[Video]) -> None:
        await self.stop()
        with contextlib.suppress(FileNotFoundError):
            self._socket.unlink()
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.arguments(videos), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
        except FileNotFoundError as exc:
            raise BackendUnavailable("mpv no está instalado") from exc
        self._queue = videos

    async def _ipc(self, *command: object) -> dict | None:
        if not self.active:
            raise BackendUnavailable("no está sonando música de YouTube")
        return await mpv_command(self._socket, *command)

    async def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 3.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    async def pause(self) -> None:
        await self._ipc("set_property", "pause", True)

    async def resume(self) -> None:
        await self._ipc("set_property", "pause", False)

    async def next(self) -> None:
        await self._ipc("playlist-next", "weak")

    async def previous(self) -> None:
        await self._ipc("playlist-prev", "weak")

    async def seek(self, seconds: int) -> None:
        await self._ipc("seek", seconds, "relative")

    async def shuffle(self, on: bool) -> None:
        await self._ipc("playlist-shuffle" if on else "playlist-unshuffle")

    async def now_playing(self) -> NowPlaying | None:
        if not self.active:
            return None
        position = await mpv_command(self._socket, "get_property", "playlist-pos")
        paused = await mpv_command(self._socket, "get_property", "pause")
        index = (position or {}).get("data")
        if not isinstance(index, int) or not 0 <= index < len(self._queue):
            return None
        video = self._queue[index]
        return NowPlaying(video.title, video.channel, playing=not (paused or {}).get("data", False))

    async def like(self) -> None:
        raise NotSupported("«Me gusta» es de Spotify")

    async def transfer(self, device: str) -> str:
        raise NotSupported("pasar la música a otro dispositivo es de Spotify")
