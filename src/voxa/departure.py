"""La salida de la mañana (a la escuela, al trabajo): cuánto falta y avisos antes de la hora.

«Faltan 15 minutos para salir. No olviden: mochila y lonche.», luego a los 5 y «¡Hora de salir!».
Solo los días elegidos (de lunes a viernes, si no se dice otra cosa). Se configura en Ajustes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from voxa.core.phrases import clock_words, join_words
from voxa.i18n import tr

WARNINGS = (15, 5)
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_time(text: str) -> tuple[int, int] | None:
    match = _TIME.match(text.strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def _minutes(n: int) -> str:
    return tr("un minuto") if n == 1 else tr("{count} minutos", count=n)


@dataclass(frozen=True)
class Departure:
    at: tuple[int, int] | None
    days: frozenset[int]
    checklist: list[str]

    @classmethod
    def from_config(cls, routine) -> Departure:
        items = [i.strip() for i in re.split(r",|\by\b", routine.checklist or "") if i.strip()]
        return cls(parse_time(routine.departure or ""), frozenset(routine.departure_days), items)

    def today(self, now: datetime) -> datetime | None:
        if self.at is None or now.weekday() not in self.days:
            return None
        return now.replace(hour=self.at[0], minute=self.at[1], second=0, microsecond=0)

    def _reminder(self) -> str:
        return tr(" No olviden: {items}.", items=join_words(self.checklist)) if self.checklist else ""

    def how_long(self, now: datetime) -> str:
        if self.at is None:
            return "No tengo hora de salida. Ponla en el celular: Ajustes, Rutina de la mañana."
        hour = clock_words(self.at[0], self.at[1], on_the_hour="")
        leave = self.today(now)
        if leave is None:
            return tr("Hoy no hay salida programada; los días de escuela es a {hour}.", hour=hour)
        left = round((leave - now).total_seconds() / 60)
        if left < 0:
            return tr("La salida era a {hour}.", hour=hour)
        if left == 0:
            return tr("¡Ya es hora de salir!") + self._reminder()
        return tr("Faltan {minutes} para salir (a {hour}).", minutes=_minutes(left), hour=hour) + self._reminder()

    def morning(self, now: datetime) -> str:
        """Para «buenos días»: la salida de hoy, si todavía no pasa."""
        leave = self.today(now)
        if leave is None or leave <= now:
            return ""
        left = round((leave - now).total_seconds() / 60)
        return tr("Salen a {hour}: faltan {minutes}.", hour=clock_words(self.at[0], self.at[1], on_the_hour=""),
                  minutes=_minutes(left))

    def due(self, now: datetime, told: set[str]) -> list[str]:
        """Los avisos que tocan ahora (cada uno una vez al día)."""
        leave = self.today(now)
        if leave is None:
            return []
        said = []
        for minutes in (*WARNINGS, 0):
            moment = leave - timedelta(minutes=minutes)
            key = f"{leave.date()}-{minutes}"
            if key in told or not moment <= now < moment + timedelta(minutes=2):
                continue
            told.add(key)
            text = tr("¡Hora de salir!") if minutes == 0 else tr("Faltan {minutes} para salir.", minutes=_minutes(minutes))
            said.append(text + self._reminder())
        return said
