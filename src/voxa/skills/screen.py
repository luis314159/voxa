"""La pantalla de cocina: «modo foto» (solo la imagen de fondo) y de regreso a la información."""

from __future__ import annotations

from voxa.core.types import Intent, Response


class ScreenSkill:
    async def handle(self, intent: Intent) -> Response:
        match intent.name:
            case "display.photo":
                return Response(sound="ok", action="display.photo")
            case "display.info":
                return Response(sound="ok", action="display.info")
        return Response("Todavía no sé hacer eso con la pantalla.", sound="error")
