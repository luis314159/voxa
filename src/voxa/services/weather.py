"""Clima con Open-Meteo (gratis, sin llave)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from voxa.services.http import Http, HttpError

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# La pantalla y las preguntas comparten la misma consulta: el pronóstico no cambia minuto a minuto.
MAX_AGE_SECONDS = 10 * 60


class WeatherUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Weather:
    temperature: float
    code: int
    high: float
    low: float
    rain_probability: int
    is_day: bool = True

    @property
    def description(self) -> str:
        return describe_code(self.code)


def describe_code(code: int) -> str:
    """Códigos WMO que usa Open-Meteo."""
    if code == 0:
        return "despejado"
    if code in (1, 2):
        return "parcialmente nublado"
    if code == 3:
        return "nublado"
    if code in (45, 48):
        return "con niebla"
    if 51 <= code <= 57:
        return "con llovizna"
    if 61 <= code <= 67:
        return "lloviendo"
    if 71 <= code <= 77 or code in (85, 86):
        return "nevando"
    if 80 <= code <= 82:
        return "con chubascos"
    if code >= 95:
        return "con tormenta"
    return "variable"


class OpenMeteo:
    def __init__(
        self, http: Http, latitude: float, longitude: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._http = http
        self._lat = latitude
        self._lon = longitude
        self._clock = clock
        self._cached: tuple[float, Weather] | None = None

    async def today(self) -> Weather:
        if self._cached and self._clock() - self._cached[0] < MAX_AGE_SECONDS:
            return self._cached[1]
        weather = await self._fetch()
        self._cached = (self._clock(), weather)
        return weather

    async def _fetch(self) -> Weather:
        params = {
            "latitude": self._lat,
            "longitude": self._lon,
            "current": "temperature_2m,weather_code,is_day",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 1,
        }
        try:
            resp = await self._http.request("GET", FORECAST_URL, params=params)
        except HttpError as exc:
            raise WeatherUnavailable(str(exc)) from exc
        if resp.status != 200 or not isinstance(resp.data, dict):
            raise WeatherUnavailable(f"Open-Meteo respondió {resp.status}")
        current, daily = resp.data["current"], resp.data["daily"]
        return Weather(
            temperature=current["temperature_2m"],
            code=current["weather_code"],
            high=daily["temperature_2m_max"][0],
            low=daily["temperature_2m_min"][0],
            rain_probability=daily["precipitation_probability_max"][0] or 0,
            is_day=bool(current.get("is_day", 1)),
        )


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


@dataclass(frozen=True)
class Place:
    name: str
    region: str
    country: str
    latitude: float
    longitude: float

    @property
    def label(self) -> str:
        return ", ".join(p for p in (self.name, self.region, self.country) if p)


async def find_places(http: Http, text: str, limit: int = 6) -> list[Place]:
    """«Monterrey» → las ciudades que se llaman así (para elegir la de la casa sin escribir coordenadas)."""
    try:
        response = await http.request(
            "GET", GEOCODING_URL, params={"name": text.strip()[:80], "count": limit, "language": "es", "format": "json"}
        )
    except HttpError as exc:
        raise WeatherUnavailable(f"sin conexión con Open-Meteo: {exc}") from exc
    if response.status != 200 or not isinstance(response.data, dict):
        raise WeatherUnavailable(f"Open-Meteo respondió {response.status}")
    return [
        Place(str(r.get("name", "")), str(r.get("admin1", "")), str(r.get("country", "")),
              float(r["latitude"]), float(r["longitude"]))
        for r in response.data.get("results") or []
        if "latitude" in r and "longitude" in r
    ]
