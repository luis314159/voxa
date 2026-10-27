"""«¿Hay actualizaciones?» y «actualízate»: las versiones nuevas de VOXA, por voz."""

from __future__ import annotations

from voxa.core.types import Intent, Response
from voxa.i18n import tr
from voxa.update import Updater


class UpdateSkill:
    def __init__(self, updater: Updater) -> None:
        self._updater = updater

    async def handle(self, intent: Intent) -> Response:
        updater = self._updater
        if intent.name == "update.check":
            available = await updater.check()
            if available:
                return Response(tr("Sí: hay la versión {new}; tienes la {current}. Di «actualízate» para instalarla.",
                                   new=available, current=updater.current))
            return Response(tr("Estoy al día: tengo la versión {current}.", current=updater.current))
        if intent.name == "update.install":
            if not updater.available and not await updater.check():
                return Response(tr("Ya tengo la versión más reciente, la {current}.", current=updater.current))
            if updater.installing:
                return Response("Ya me estoy actualizando.")
            if updater.install():
                return Response(tr("Me actualizo a la versión {new}. En unos minutos vuelvo.", new=updater.available))
            return Response("No pude empezar la actualización. En la terminal: voxa actualizar.", sound="error")
        return Response("Todavía no sé hacer eso.", sound="error")
