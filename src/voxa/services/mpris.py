"""Controles MPRIS con ``playerctl``: instantáneos, locales y sin red."""

from __future__ import annotations

import asyncio

from voxa.services.music_backend import BackendUnavailable, NotSupported, NowPlaying, PlayResult
from voxa.services.process import CommandNotFound, CommandRunner, run_command

_METADATA_FORMAT = "\t".join(
    ["{{status}}", "{{title}}", "{{artist}}", "{{album}}", "{{mpris:artUrl}}", "{{position}}", "{{mpris:length}}"]
)


def _seconds(microseconds: str) -> float | None:
    """MPRIS mide en microsegundos."""
    try:
        return int(microseconds) / 1_000_000
    except ValueError:
        return None


class PlayerctlBackend:
    name = "mpris"

    def __init__(self, player: str = "spotifast", run: CommandRunner = run_command) -> None:
        self._player = player
        self._run = run

    async def _call(self, *args: str) -> str:
        try:
            result = await self._run(["playerctl", f"--player={self._player}", *args])
        except CommandNotFound as exc:
            raise BackendUnavailable("playerctl no está instalado") from exc
        except asyncio.TimeoutError as exc:
            raise BackendUnavailable("playerctl no respondió") from exc
        if result.returncode != 0:
            raise BackendUnavailable(result.stderr.strip() or f"no hay reproductor {self._player}")
        return result.stdout

    async def play(self, query: str, kind: str | None = None) -> PlayResult:
        raise NotSupported("MPRIS no busca")

    async def pause(self) -> None:
        await self._call("pause")

    async def resume(self) -> None:
        await self._call("play")

    async def next(self) -> None:
        await self._call("next")

    async def previous(self) -> None:
        await self._call("previous")

    async def seek(self, seconds: int) -> None:
        await self._call("position", f"{abs(seconds)}{'+' if seconds >= 0 else '-'}")

    async def shuffle(self, on: bool) -> None:
        await self._call("shuffle", "On" if on else "Off")

    async def like(self) -> None:
        raise NotSupported("MPRIS no tiene «me gusta»")

    async def now_playing(self) -> NowPlaying | None:
        out = await self._call("metadata", "--format", _METADATA_FORMAT)
        fields = out.rstrip("\n").split("\t")
        if len(fields) < 3 or not fields[1]:
            return None
        fields += [""] * (7 - len(fields))
        status, title, artist, album, art_url, position, length = fields[:7]
        return NowPlaying(
            title,
            artist or None,
            playing=status == "Playing",
            album=album or None,
            art_url=art_url or None,
            position=_seconds(position),
            length=_seconds(length),
        )

    async def transfer(self, device: str) -> str:
        raise NotSupported("MPRIS no conoce otros dispositivos")
