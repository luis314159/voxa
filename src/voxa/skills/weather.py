from __future__ import annotations

import logging

from voxa.core.types import Intent, Response
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
                return Response(f"Sí, probablemente. Hay {rain} % de probabilidad de lluvia.")
            if rain >= 30:
                return Response(f"Tal vez. Hay {rain} % de probabilidad de lluvia.")
            return Response(f"No parece. La probabilidad de lluvia es de {rain} %.")
        return Response(
            f"Ahora hay {round(weather.temperature)} grados y está {weather.description}. "
            f"Hoy, máxima de {round(weather.high)} y mínima de {round(weather.low)}."
            + (f" Probabilidad de lluvia: {rain} %." if rain >= 30 else "")
        )
