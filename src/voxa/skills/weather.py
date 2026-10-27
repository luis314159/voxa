from __future__ import annotations

import logging

from voxa.core.types import Intent, Response
from voxa.i18n import tr
from voxa.services.weather import OpenMeteo, WeatherUnavailable

log = logging.getLogger(__name__)


class WeatherSkill:
    def __init__(self, source: OpenMeteo | None) -> None:
        self._source = source

    async def handle(self, intent: Intent) -> Response:
        if self._source is None:
            return Response("Aún no sé dónde estamos. Agrega la ubicación en la configuración.", sound="error")
        try:
            weather = await self._source.today()
        except WeatherUnavailable as exc:
            log.warning("Clima no disponible: %s", exc)
            return Response("No pude consultar el clima.", sound="error")

        rain = weather.rain_probability
        if intent.name == "weather.rain":
            if rain >= 60:
                return Response(tr("Sí, probablemente. Hay {rain} % de probabilidad de lluvia.", rain=rain))
            if rain >= 30:
                return Response(tr("Tal vez. Hay {rain} % de probabilidad de lluvia.", rain=rain))
            return Response(tr("No parece. La probabilidad de lluvia es de {rain} %.", rain=rain))
        return Response(
            tr("Ahora hay {now} grados y está {sky}. Hoy, máxima de {high} y mínima de {low}.",
               now=round(weather.temperature), sky=tr(weather.description), high=round(weather.high),
               low=round(weather.low))
            + (tr(" Probabilidad de lluvia: {rain} %.", rain=rain) if rain >= 30 else "")
        )
