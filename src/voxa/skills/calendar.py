"""«¿Qué tengo hoy?»: el calendario de la familia (de solo lectura, con su dirección iCal)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from voxa.core.people import speaker
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
    """El calendario de la familia y, si los hay, el de cada persona (se juntan según quién pregunta)."""

    def __init__(
        self,
        calendar: Calendar | None,
        now: Callable[[], datetime] | None = None,
        personal: dict[str, Calendar] | None = None,
    ) -> None:
        self.calendar = calendar
        self.personal = personal or {}
        self._now = now or (lambda: datetime.now().astimezone())

    def has_any(self) -> bool:
        return self.calendar is not None or bool(self.personal)

    def _sources(self, person: str | None) -> list[tuple[str | None, Calendar]]:
        sources: list[tuple[str | None, Calendar]] = [(None, self.calendar)] if self.calendar else []
        if person:
            sources += [(name, cal) for name, cal in self.personal.items() if name.lower() == person.lower()]
        return sources

    async def _events(self, start: datetime, end: datetime, person: str | None) -> list[Event]:
        events: list[Event] = []
        for _, calendar in self._sources(person):
            events += await calendar.events(start, end)
        return sorted(events, key=lambda e: (not e.all_day, e.start))

    async def handle(self, intent: Intent) -> Response:
        person = (intent.slots.get("person") or "").strip().title() or speaker()
        if not self._sources(person):
            return Response(NOT_SET)
        try:
            match intent.name:
                case "calendar.today":
                    return Response(await self.today(person=person, named=bool(intent.slots.get("person"))))
                case "calendar.tomorrow":
                    return Response(await self._day(1, person))
                case "calendar.next":
                    return Response(await self._next(person))
        except CalendarUnavailable as exc:
            log.warning("Calendario: %s", exc)
            return Response("No pude leer el calendario. Revisa la dirección en Ajustes.", sound="error")
        return Response("Todavía no sé hacer eso con el calendario.", sound="error")

    async def today(self, *, morning: bool = False, person: str | None = None, named: bool = False) -> str:
        """Lo que queda de hoy (``morning``: para «buenos días», vacío si no hay nada)."""
        now = self._now()
        events = await self._events(now, _start_of(now) + timedelta(days=1), person)
        if not events:
            if morning:
                return ""
            return f"Hoy {person} ya no tiene nada en el calendario." if named else "Hoy ya no tienes nada en el calendario."
        lead = "En el calendario de hoy hay" if morning else f"Hoy {person} tiene" if named else "Hoy tienes"
        return f"{lead} {count_phrase(events)}: {say_events(events, now.tzinfo)}."

    async def coming_up(self, minutes: int, told: set[tuple[str, str]]) -> list[str]:
        """Los avisos de los eventos que empiezan en los próximos ``minutes`` (cada uno una sola vez)."""
        now = self._now()
        said = []
        sources = [(None, self.calendar)] if self.calendar else []
        sources += list(self.personal.items())
        for person, calendar in sources:
            # El final se incluye: el evento de las 9:00 se avisa a las 8:50 con «10 minutos».
            for event in await calendar.events(now, now + timedelta(minutes=minutes, seconds=30)):
                key = (event.title, event.start.isoformat())
                if event.all_day or event.start < now or key in told:
                    continue
                told.add(key)
                left = round((event.start - now).total_seconds() / 60)
                text = f"en {left} minutos: {event.title}." if left > 1 else f"ya casi empieza: {event.title}."
                said.append(f"{person}, {text}" if person else capitalize(text))
        return said

    async def today_for_morning(self) -> str:
        return await self.today(morning=True, person=speaker())

    async def _day(self, offset: int, person: str | None = None) -> str:
        day = _start_of(self._now()) + timedelta(days=offset)
        events = await self._events(day, day + timedelta(days=1), person)
        name = "Mañana" if offset == 1 else capitalize(f"el {weekday_name(day.weekday())}")
        if not events:
            return f"{name} no tienes nada en el calendario."
        return f"{name} tienes {count_phrase(events)}: {say_events(events, day.tzinfo)}."

    async def _next(self, person: str | None = None) -> str:
        now = self._now()
        events = [e for e in await self._events(now, now + timedelta(days=14), person) if not e.all_day and e.start >= now]
        if not events:
            return "No tienes nada en el calendario en las próximas dos semanas."
        event = events[0]
        at = event.start.astimezone(now.tzinfo)
        days = (_start_of(at) - _start_of(now)).days
        when = "hoy" if days == 0 else "mañana" if days == 1 else f"el {weekday_name(at.weekday())} {at.day}"
        return f"Lo siguiente es {event.title}, {when} a {clock_words(at.hour, at.minute, on_the_hour='')}."
