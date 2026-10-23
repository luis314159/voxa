"""Clima con Open-Meteo (gratis, sin llave)."""

from __future__ import annotations

from dataclasses import dataclass

from voxa.services.http import Http, HttpError

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Weather:
    temperature: float
    code: int
    high: float
    low: float
    rain_probability: int

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
    def __init__(self, http: Http, latitude: float, longitude: float) -> None:
        self._http = http
        self._lat = latitude
        self._lon = longitude

    async def today(self) -> Weather:
        params = {
            "latitude": self._lat,
            "longitude": self._lon,
            "current": "temperature_2m,weather_code",
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
        )
