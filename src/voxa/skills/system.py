from __future__ import annotations

from typing import Callable

from voxa.core.phrases import join_words
from voxa.core.types import OK, Intent, Response

HELP = (
    "Puedo poner música de Spotify, por ejemplo «pon Soda Stereo»; "
    "poner temporizadores, como «temporizador de diez minutos para el arroz», "
    "y recordatorios, como «recuérdame sacar la basura a las 8»; "
    "subir o bajar el volumen, decirte la hora y el clima. "
    "También pongo videos de recetas: «pon un video de cómo hacer pozole». "
    "Si quieres que deje de escuchar, di «deja de escuchar»."
)


# Cómo se dice cada problema de ``voxa.health`` («¿estás bien?» → «Aquí estoy, pero no tengo internet»).
_SPOKEN_PROBLEMS = {
    "voz": "me faltan los modelos de voz",
    "microfono": "no encuentro el micrófono",
    "activacion": "no puedo escuchar «Hey Voxa»",
    "internet": "no tengo internet",
    "spotify": "falta conectar Spotify",
    "musica": "Spotifast no responde",
}


class SystemSkill:
    def __init__(self) -> None:
        self.problems: Callable[[], list] = list
        """Lo pone el servicio: los problemas actuales (``voxa.health.Health.problems``)."""

    async def handle(self, intent: Intent) -> Response:
        match intent.name:
            case "system.help":
                return Response(HELP)
            case "system.status":
                problems = [_SPOKEN_PROBLEMS.get(p.id, p.text.lower()) for p in self.problems()]
                if problems:
                    return Response(f"Aquí estoy, pero {join_words(problems)}.")
                return Response("Aquí estoy.")
            case "system.mute_mic":
                return Response("Micrófono apagado. Toca la pantalla para reactivarme.", action="mic.mute")
            case "system.ack":
                return Response("¡De nada!") if "gracias" in intent.text else OK
        return OK
