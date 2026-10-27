from __future__ import annotations

import logging

from voxa.core.types import OK, Intent, Response
from voxa.i18n import tr
from voxa.services.pipewire import VolumeControl, VolumeUnavailable

log = logging.getLogger(__name__)

_SMALL = ("poco", "poquito", "bit", "little")
_BIG = ("mucho", "bastante", "lot")


class VolumeSkill:
    def __init__(self, control: VolumeControl, step: int = 10) -> None:
        self._control = control
        self._step = step

    def _step_for(self, text: str) -> int:
        words = text.split()
        if any(w in words for w in _SMALL):
            return max(1, self._step // 2)
        if any(w in words for w in _BIG):
            return self._step * 2
        return self._step

    async def handle(self, intent: Intent) -> Response:
        try:
            return await self._handle(intent)
        except VolumeUnavailable as exc:
            log.warning("Volumen no disponible: %s", exc)
            return Response("No pude cambiar el volumen.", sound="error")

    async def _handle(self, intent: Intent) -> Response:
        match intent.name:
            case "volume.set":
                percent = max(0, min(100, intent.slots["number"]))
                await self._control.set(percent)
                await self._control.mute(False)
                return Response(tr("Volumen al {percent}.", percent=percent))
            case "volume.up" | "volume.down":
                state = await self._control.get()
                delta = self._step_for(intent.text) * (1 if intent.name == "volume.up" else -1)
                await self._control.set(state.percent + delta)
                if state.muted and delta > 0:
                    await self._control.mute(False)
                return OK
            case "volume.mute":
                await self._control.mute(True)
                return OK
            case "volume.unmute":
                await self._control.mute(False)
                return OK
        return Response("Todavía no sé hacer eso con el volumen.", sound="error")
