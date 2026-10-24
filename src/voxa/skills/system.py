from __future__ import annotations

from voxa.core.types import OK, Intent, Response

HELP = (
    "Puedo poner música de Spotify, por ejemplo «pon Soda Stereo»; "
    "poner temporizadores, como «temporizador de diez minutos para el arroz»; "
    "subir o bajar el volumen, decirte la hora y el clima. "
    "También pongo videos de recetas: «pon un video de cómo hacer pozole». "
    "Si quieres que deje de escuchar, di «deja de escuchar»."
)


class SystemSkill:
    async def handle(self, intent: Intent) -> Response:
        match intent.name:
            case "system.help":
                return Response(HELP)
            case "system.status":
                return Response("Aquí estoy.")
            case "system.mute_mic":
                return Response("Micrófono apagado. Toca la pantalla para reactivarme.", action="mic.mute")
            case "system.ack":
                return Response("¡De nada!") if "gracias" in intent.text else OK
        return OK
