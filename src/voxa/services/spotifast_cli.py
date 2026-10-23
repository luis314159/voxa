"""Control de Spotifast mediante su CLI oficial (``spotifast <verbo>``).

Referencia: docs de Spotifast, «Using Spotifast» → comandos para lanzadores.
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
        await self._call("like")

    async def now_playing(self) -> NowPlaying | None:
        # --raw: estado, título, artistas, álbum, posición, duración, … separados por tabulador.
        fields = (await self._call("now-playing", "--raw")).rstrip("\n").split("\t")
        if len(fields) < 3 or not fields[1]:
            return None
        state, title, artists = fields[0].lower(), fields[1], fields[2]
        return NowPlaying(title, artists or None, playing=state == "playing")

    async def transfer(self, device: str) -> str:
        raise NotSupported("la CLI necesita el id del dispositivo")
