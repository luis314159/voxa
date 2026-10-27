from __future__ import annotations

from typing import Callable

from voxa.core.phrases import join_words
from voxa.core.types import OK, Intent, Response
from voxa.i18n import tr

HELP = (
    "Puedo poner música de Spotify, por ejemplo «pon Soda Stereo» o «pon algo tranquilo para cocinar»; "
    "poner temporizadores, como «temporizador de diez minutos para el arroz», "
    "y recordatorios, como «recuérdame sacar la basura a las 8» o «despiértame de lunes a viernes a las 6»; "
    "subir o bajar el volumen, decirte la hora y el clima. "
    "También pongo videos de recetas: «pon un video de cómo hacer pozole». "
    "Si quieres que deje de escuchar, di «deja de escuchar»."
)
HELP_AI = (
    " Con la IA también te guío en recetas paso a paso: «dame la receta de arroz rojo»."
    " Y cualquier otra pregunta, como «¿con qué sustituyo el huevo en un pastel?», se la paso a la IA."
)


# Cómo se dice cada problema de ``voxa.health`` («¿estás bien?» → «Aquí estoy, pero no tengo internet»).
_SPOKEN_PROBLEMS = {
    "voz": "me faltan los modelos de voz",
    "microfono": "no encuentro el micrófono",
    "activacion": "no puedo escuchar «Hey Voxa»",
    "internet": "no tengo internet",
    "spotify": "falta conectar Spotify",
    "musica": "Spotifast no responde",
    "ia": "no puedo usar la IA",
}


class SystemSkill:
    def __init__(self) -> None:
        self.problems: Callable[[], list] = list
        """Lo pone el servicio: los problemas actuales (``voxa.health.Health.problems``)."""
        self.open_questions = False
        """Hay respaldo con IA: la ayuda lo menciona."""

    async def handle(self, intent: Intent) -> Response:
        match intent.name:
            case "system.help":
                return Response(HELP + HELP_AI if self.open_questions else HELP)
            case "system.status":
                problems = [tr(_SPOKEN_PROBLEMS.get(p.id, p.text.lower())) for p in self.problems()]
                if problems:
                    return Response(tr("Aquí estoy, pero {problems}.", problems=join_words(problems)))
                return Response("Aquí estoy.")
            case "system.mute_mic":
                return Response("Micrófono apagado. Toca la pantalla para reactivarme.", action="mic.mute")
            case "system.ack":
                thanks = "gracias" in intent.text or "thank" in intent.text
                return Response("¡De nada!") if thanks else OK
        return OK
