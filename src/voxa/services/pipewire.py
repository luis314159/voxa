"""Volumen del sistema con ``wpctl`` (PipeWire): actúa sobre la salida activa, p. ej. la bocina Bluetooth."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol

from voxa.services.process import CommandNotFound, CommandRunner, run_command

_VOLUME = re.compile(r"Volume:\s*([\d.]+)(\s*\[MUTED\])?")


class VolumeUnavailable(Exception):
    pass


@dataclass(frozen=True)
class VolumeState:
    percent: int
    muted: bool


class VolumeControl(Protocol):
    async def get(self) -> VolumeState: ...
    async def set(self, percent: int) -> None: ...
    async def mute(self, on: bool) -> None: ...


class WpctlVolume:
    def __init__(self, target: str = "@DEFAULT_AUDIO_SINK@", run: CommandRunner = run_command) -> None:
        self._target = target
        self._run = run

    async def _call(self, *args: str) -> str:
        try:
            result = await self._run(["wpctl", *args])
        except (CommandNotFound, asyncio.TimeoutError) as exc:
            raise VolumeUnavailable("wpctl no disponible") from exc
        if result.returncode != 0:
            raise VolumeUnavailable(result.stderr.strip() or "wpctl falló")
        return result.stdout

    async def get(self) -> VolumeState:
        out = await self._call("get-volume", self._target)
        m = _VOLUME.search(out)
        if not m:
            raise VolumeUnavailable(f"salida inesperada de wpctl: {out!r}")
        return VolumeState(round(float(m.group(1)) * 100), bool(m.group(2)))

    async def set(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        # -l 1.0 impide pasar del 100 % (distorsiona la bocina).
        await self._call("set-volume", "-l", "1.0", self._target, f"{percent / 100:.2f}")

    async def mute(self, on: bool) -> None:
        await self._call("set-mute", self._target, "1" if on else "0")
