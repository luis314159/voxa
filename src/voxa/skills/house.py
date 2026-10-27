"""Los avisos entre cuartos y lo que un cuarto le pregunta a la VOXA principal."""

from __future__ import annotations

import logging

from voxa.core.phrases import join_words
from voxa.core.types import Intent, Response
from voxa.house import House, HouseError, place_name

log = logging.getLogger(__name__)


class HouseSkill:
    def __init__(self, house: House) -> None:
        self.house = house

    async def handle(self, intent: Intent) -> Response:
        if intent.name != "house.announce":
            return Response("Todavía no sé hacer eso con la casa.", sound="error")
        message = intent.slots.get("query", "").strip()
        target = (intent.slots.get("device") or "").strip() or None
        if not message:
            return Response("¿Qué aviso?", sound="error")
        text = f"¡A {message}!" if intent.slots.get("call") else _sentence(message)  # «llama a todos a comer»
        try:
            heard = await self.house.announce(text, target=target)
        except HouseError as exc:
            log.warning("Aviso: %s", exc)
            return Response("No pude avisar: no contesta la VOXA principal.", sound="error")
        if not heard:
            if target:
                return Response(f"No encontré {place_name(target)} conectada.", sound="error")
            return Response("No hay otros cuartos con VOXA conectados.", sound="error")
        return Response(f"Listo, avisé en {join_words([place_name(r) for r in heard])}.")


class RemoteSkill:
    """En un cuarto: la lista del súper y el calendario son de toda la casa; contesta la principal."""

    def __init__(self, house: House) -> None:
        self.house = house

    async def handle(self, intent: Intent) -> Response:
        try:
            return Response(await self.house.ask_main(intent.raw or intent.text))
        except HouseError as exc:
            log.warning("Pregunta a la principal («%s»): %s", intent.raw, exc)
            return Response("No contesta la VOXA de la cocina; inténtalo en un momento.", sound="error")


def _sentence(text: str) -> str:
    text = text.strip()
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."
