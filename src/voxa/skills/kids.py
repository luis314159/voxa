"""«Activa el modo niños»: se enciende por voz para todos; se apaga solo desde el celular."""

from __future__ import annotations

from voxa.core.types import Intent, Response
from voxa.kids import KidsRules


class KidsSkill:
    def __init__(self, rules: KidsRules) -> None:
        self._rules = rules

    async def handle(self, intent: Intent) -> Response:
        if intent.name == "kids.on":
            self._rules.turn_on()
            return Response("Listo, modo niños para todos: música sin groserías, volumen con tope y la IA para niños. "
                            "Se apaga desde el celular.")
        if intent.name == "kids.off":
            if not self._rules.config.enabled:
                return Response("El modo niños ya está apagado.")
            return Response("El modo niños se apaga desde el celular: Ajustes, Modo niños.")
        return Response("Todavía no sé hacer eso.", sound="error")
