"""La pantalla de cocina: «modo foto» (solo la imagen de fondo) y de regreso a la información."""

from __future__ import annotations

from voxa.core.types import Intent, Response


class ScreenSkill:
    def __init__(self) -> None:
        self.phone_ready = lambda: False
        """Lo pone el servicio: si VOXA para el celular está encendido ([web])."""

    async def handle(self, intent: Intent) -> Response:
        match intent.name:
            case "display.phone":
                if not self.phone_ready():
                    return Response("Para usarme desde el celular hay que activarlo en la configuración: enabled en [web].")
                return Response("Escanea el código con la cámara del celular.", action="display.phone")
            case "display.phone_close":
                return Response(sound="ok", action="display.phone_close")
            case "display.photo":
                return Response(sound="ok", action="display.photo")
            case "display.info":
                return Response(sound="ok", action="display.info")
        return Response("Todavía no sé hacer eso con la pantalla.", sound="error")
