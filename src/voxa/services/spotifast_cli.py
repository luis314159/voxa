"""Control de Spotifast mediante su CLI oficial (``spotifast <verbo>``).

Referencia: docs de Spotifast, «Using Spotifast» → comandos para lanzadores, y ``spotifast --help``
(confirmado con Spotifast 0.14 en Windows: ``play-search --kind``, ``now-playing --raw`` y ``like``).
Un verbo sale con código distinto de cero si Spotifast no está corriendo.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

from voxa.services.music_backend import BackendUnavailable, NotSupported, NowPlaying, PlayResult
from voxa.services.process import CommandNotFound, CommandRunner, run_command

_KINDS = {"artist", "album", "playlist"}


class SpotifastCli:
    name = "spotifast"

    def __init__(self, command: Sequence[str] = ("spotifast",), run: CommandRunner = run_command) -> None:
        self._command = list(command)
        self._run = run

    async def _call(self, *args: str) -> str:
        try:
            result = await self._run([*self._command, *args])
        except CommandNotFound as exc:
            raise BackendUnavailable("Spotifast no está instalado") from exc
        except asyncio.TimeoutError as exc:
            raise BackendUnavailable("Spotifast no respondió") from exc
        if result.returncode != 0:
            raise BackendUnavailable(result.stderr.strip() or "Spotifast no está corriendo")
        return result.stdout

    async def play(self, query: str, kind: str | None = None) -> PlayResult:
        args = ["play-search"]
        if kind in _KINDS:
            args += ["--kind", kind]
        await self._call(*args, *query.split())
        return PlayResult(query, kind=kind)

    async def pause(self) -> None:
        await self._call("pause")

    async def resume(self) -> None:
        await self._call("play")

    async def next(self) -> None:
        await self._call("next")

    async def previous(self) -> None:
        await self._call("previous")

    async def seek(self, seconds: int) -> None:
        await self._call("seek", "--", str(seconds))

    async def shuffle(self, on: bool) -> None:
        await self._call("shuffle", "on" if on else "off")

    async def like(self) -> None:
        # «like» alterna: si la canción ya está en tus Me gusta, la quitaría. Solo se llama si no está.
        if (await self._raw())[10:11] == ["yes"]:
            return
        await self._call("like")

    async def now_playing(self) -> NowPlaying | None:
        fields = await self._raw()
        if len(fields) < 3 or not fields[1]:
            return None
        state, title, artists = fields[0].lower(), fields[1], fields[2]
        extra = fields + [""] * (10 - len(fields))
        album, position, length, art = extra[3] or None, _seconds(extra[4]), _seconds(extra[5]), extra[9] or None
        return NowPlaying(title, artists or None, playing=state == "playing", album=album, art_url=art,
                          position=position, length=length)

    async def _raw(self) -> list[str]:
        """``now-playing --raw``: estado, título, artistas, álbum, posición (ms), duración (ms), volumen,
        aleatorio, repetir, portada, en tus Me gusta («yes»/«no») y dispositivo, separados por tabulador."""
        return (await self._call("now-playing", "--raw")).rstrip("\r\n").split("\t")

    async def transfer(self, device: str) -> str:
        raise NotSupported("la CLI necesita el id del dispositivo")


def _seconds(ms: str) -> float | None:
    try:
        return int(ms) / 1000
    except ValueError:
        return None
