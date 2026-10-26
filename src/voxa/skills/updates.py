"""«¿Hay actualizaciones?» y «actualízate»: las versiones nuevas de VOXA, por voz."""

from __future__ import annotations

from voxa.core.types import Intent, Response
from voxa.update import Updater


class UpdateSkill:
    def __init__(self, updater: Updater) -> None:
        self._updater = updater

    async def handle(self, intent: Intent) -> Response:
        updater = self._updater
        if intent.name == "update.check":
            available = await updater.check()
            if available:
                return Response(f"Sí: hay la versión {available}; tienes la {updater.current}. Di «actualízate» para instalarla.")
            return Response(f"Estoy al día: tengo la versión {updater.current}.")
        if intent.name == "update.install":
            if not updater.available and not await updater.check():
                return Response(f"Ya tengo la versión más reciente, la {updater.current}.")
            if updater.installing:
                return Response("Ya me estoy actualizando.")
            if updater.install():
                return Response(f"Me actualizo a la versión {updater.available}. En unos minutos vuelvo.")
            return Response("No pude empezar la actualización. En la terminal: voxa actualizar.", sound="error")
        return Response("Todavía no sé hacer eso.", sound="error")
