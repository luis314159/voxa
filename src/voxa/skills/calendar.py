"""«¿Qué tengo hoy?»: el calendario de la familia (de solo lectura, con su dirección iCal)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from voxa.core.phrases import capitalize, clock_words, join_words, weekday_name
from voxa.core.types import Intent, Response
from voxa.services.calendar import Calendar, CalendarUnavailable, Event

log = logging.getLogger(__name__)

NOT_SET = "No tengo tu calendario. Agrégalo desde el celular, en Ajustes: «conecta mi celular»."
MAX_SAID = 5


def _start_of(day: datetime) -> datetime:
    return day.replace(hour=0, minute=0, second=0, microsecond=0)


def say_events(events: list[Event], home) -> str:
    """«a las 9 de la mañana, dentista; a las 5 de la tarde, futbol de Ana; todo el día: cumpleaños»."""
    timed = [e for e in events if not e.all_day]
    all_day = [e.title for e in events if e.all_day]
    parts = []
    for event in timed[:MAX_SAID]:
        at = event.start.astimezone(home)
        parts.append(f"a {clock_words(at.hour, at.minute, on_the_hour='')}, {event.title}")
    if len(timed) > MAX_SAID:
        parts.append(f"y {len(timed) - MAX_SAID} más")
    if all_day:
        parts.append(f"todo el día: {join_words(all_day)}")
    return "; ".join(parts)


def count_phrase(events: list[Event]) -> str:
    return "una cosa" if len(events) == 1 else f"{len(events)} cosas"


class CalendarSkill:
    def __init__(self, calendar: Calendar | None, now: Callable[[], datetime] | None = None) -> None:
        self.calendar = calendar
        self._now = now or (lambda: datetime.now().astimezone())

    async def handle(self, intent: Intent) -> Response:
        if self.calendar is None:
            return Response(NOT_SET)
        try:
            match intent.name:
                case "calendar.today":
                    return Response(await self.today())
                case "calendar.tomorrow":
                    return Response(await self._day(1))
                case "calendar.next":
                    return Response(await self._next())
        except CalendarUnavailable as exc:
            log.warning("Calendario: %s", exc)
            return Response("No pude leer el calendario. Revisa la dirección en Ajustes.", sound="error")
        return Response("Todavía no sé hacer eso con el calendario.", sound="error")

    async def today(self, *, morning: bool = False) -> str:
        """Lo que queda de hoy (``morning``: para «buenos días», vacío si no hay nada)."""
        now = self._now()
        events = await self.calendar.events(now, _start_of(now) + timedelta(days=1))
        if not events:
            return "" if morning else "Hoy ya no tienes nada en el calendario."
        lead = "En el calendario de hoy hay" if morning else "Hoy tienes"
        return f"{lead} {count_phrase(events)}: {say_events(events, now.tzinfo)}."

    async def today_for_morning(self) -> str:
        return await self.today(morning=True)

    async def _day(self, offset: int) -> str:
        day = _start_of(self._now()) + timedelta(days=offset)
        events = await self.calendar.events(day, day + timedelta(days=1))
        name = "Mañana" if offset == 1 else capitalize(f"el {weekday_name(day.weekday())}")
        if not events:
            return f"{name} no tienes nada en el calendario."
        return f"{name} tienes {count_phrase(events)}: {say_events(events, day.tzinfo)}."

    async def _next(self) -> str:
        now = self._now()
        events = [e for e in await self.calendar.events(now, now + timedelta(days=14)) if not e.all_day and e.start >= now]
        if not events:
            return "No tienes nada en el calendario en las próximas dos semanas."
        event = events[0]
        at = event.start.astimezone(now.tzinfo)
        days = (_start_of(at) - _start_of(now)).days
        when = "hoy" if days == 0 else "mañana" if days == 1 else f"el {weekday_name(at.weekday())} {at.day}"
        return f"Lo siguiente es {event.title}, {when} a {clock_words(at.hour, at.minute, on_the_hour='')}."
