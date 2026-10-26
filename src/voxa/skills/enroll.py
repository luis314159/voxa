"""«Aprende mi voz»: la grabación la hace el servicio (necesita el micrófono de la cocina)."""

from __future__ import annotations

from voxa.core.types import Intent, Response

ENROLL_ACTION = "voice.enroll"


class EnrollSkill:
    def __init__(self) -> None:
        self.ready = lambda: False
        """Lo pone el servicio: si hay micrófono y «Hey Voxa» (no en modo texto)."""

    async def handle(self, intent: Intent) -> Response:
        if intent.name != "voice.enroll":
            return Response("Todavía no sé hacer eso.", sound="error")
        if not self.ready():
            return Response("Para aprender tu voz necesito el micrófono de la cocina y «Hey Voxa» encendido.",
                            sound="error")
        name = (intent.slots.get("name") or "").strip()
        return Response(action=ENROLL_ACTION, target=name.title() if name else "")
