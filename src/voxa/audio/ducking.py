"""Baja la música mientras VOXA escucha o habla, y la regresa después.

Actúa sobre el volumen de cada stream de reproducción en PipeWire, así
funciona con Spotifast, mpv o cualquier otro reproductor, sin tocar el
volumen de Spotify ni el de la bocina.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Protocol

from voxa.services.process import CommandNotFound, CommandRunner, run_command

log = logging.getLogger(__name__)

_VOLUME = re.compile(r"Volume:\s*([\d.]+)")


class Ducker(Protocol):
    async def duck(self) -> None: ...
    async def restore(self) -> None: ...


class NoDucking:
    async def duck(self) -> None:
        pass

    async def restore(self) -> None:
        pass


class PipeWireDucker:
    def __init__(self, level: float = 0.2, run: CommandRunner = run_command, own_pid: int | None = None) -> None:
        self._level = level
        self._run = run
        self._own_pid = str(own_pid or os.getpid())
        self._saved: dict[int, float] = {}

    async def _stream_ids(self) -> list[int]:
        result = await self._run(["pw-dump"], timeout=3.0)
        ids = []
        for obj in json.loads(result.stdout or "[]"):
            props = (obj.get("info") or {}).get("props") or {}
            if obj.get("type") != "PipeWire:Interface:Node" or props.get("media.class") != "Stream/Output/Audio":
                continue
            if str(props.get("application.process.id")) == self._own_pid:
                continue  # la voz de VOXA no se baja
            ids.append(obj["id"])
        return ids

    async def duck(self) -> None:
        if self._saved:
            return
        try:
            for node in await self._stream_ids():
                out = (await self._run(["wpctl", "get-volume", str(node)])).stdout
                if m := _VOLUME.search(out):
                    volume = float(m.group(1))
                    self._saved[node] = volume
                    await self._run(["wpctl", "set-volume", str(node), f"{volume * self._level:.3f}"])
        except (CommandNotFound, asyncio.TimeoutError, ValueError) as exc:
            log.warning("No pude bajar la música: %s", exc)

    async def restore(self) -> None:
        saved, self._saved = self._saved, {}
        for node, volume in saved.items():
            try:
                await self._run(["wpctl", "set-volume", str(node), f"{volume:.3f}"])
            except (CommandNotFound, asyncio.TimeoutError) as exc:
                log.warning("No pude regresar el volumen del stream %s: %s", node, exc)
