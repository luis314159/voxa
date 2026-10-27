"""«¿Qué tengo hoy?»: el calendario de la familia (de solo lectura, con su dirección iCal)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from voxa.core.people import speaker
from voxa.core.phrases import capitalize, clock_words, join_words, weekday_name
from voxa.core.types import Intent, Response
from voxa.i18n import english, tr
from voxa.nlu.when import When, parse_when
from voxa.services.calendar import Calendar, CalendarUnavailable, Event
from voxa.services.google_calendar import GoogleCalendarWriter, GoogleError, GoogleNotConnected

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
        parts.append(tr("a {hour}, {title}", hour=clock_words(at.hour, at.minute, on_the_hour=""), title=event.title))
    if len(timed) > MAX_SAID:
        parts.append(tr("y {count} más", count=len(timed) - MAX_SAID))
    if all_day:
        parts.append(tr("todo el día: {items}", items=join_words(all_day)))
    return "; ".join(parts)


def count_phrase(events: list[Event]) -> str:
    return tr("una cosa") if len(events) == 1 else tr("{count} cosas", count=len(events))


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
        self.writer: Callable[[], GoogleCalendarWriter | None] = lambda: None
        """Lo pone la app si la cuenta de Google está conectada: para agregar citas por voz."""

    async def add(self, intent: Intent) -> Response:
        """«Agrega dentista el martes a las 5 al calendario»."""
        text = (intent.slots.get("query") or "").strip()
        if intent.slots.get("kind") == "cita":
            text = (tr("cita") + " " + text).strip()
        when = parse_when(text, self._now().replace(tzinfo=None), english=english())
        if when is None:
            return Response("¿Para cuándo? Dime, por ejemplo, «agrega dentista al calendario el martes a las 5».",
                            sound="error")
        writer = self.writer()
        if writer is None:
            return Response("Para agregar citas, conecta Google Calendar desde el celular: Ajustes, Calendario.",
                            sound="error")
        try:
            await writer.add(when.title, when.day if when.all_day else when.start)
        except GoogleNotConnected:
            return Response("Para agregar citas, conecta Google Calendar desde el celular: Ajustes, Calendario.",
                            sound="error")
        except GoogleError as exc:
            log.warning("Calendario de Google: %s", exc)
            return Response("No pude agregarlo al calendario. Revisa la conexión de Google en el celular.",
                            sound="error")
        if self.calendar is not None:
            self.calendar.forget()  # que «¿qué tengo el martes?» ya la vea
        return Response(tr("Listo, lo anoté en el calendario: {title}, {when}.", title=when.title,
                           when=_when_phrase(when, self._now())))

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
        if intent.name == "calendar.add":
            return await self.add(intent)
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
            if named:
                return tr("Hoy {person} ya no tiene nada en el calendario.", person=person)
            return "Hoy ya no tienes nada en el calendario."
        lead = tr("En el calendario de hoy hay") if morning else tr("Hoy {person} tiene", person=person) if named else tr("Hoy tienes")
        return tr("{lead} {count}: {events}.", lead=lead, count=count_phrase(events), events=say_events(events, now.tzinfo))

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
                text = (tr("en {minutes} minutos: {title}.", minutes=left, title=event.title) if left > 1
                        else tr("ya casi empieza: {title}.", title=event.title))
                said.append(f"{person}, {text}" if person else capitalize(text))
        return said

    async def today_for_morning(self) -> str:
        return await self.today(morning=True, person=speaker())

    async def _day(self, offset: int, person: str | None = None) -> str:
        day = _start_of(self._now()) + timedelta(days=offset)
        events = await self._events(day, day + timedelta(days=1), person)
        name = tr("Mañana") if offset == 1 else capitalize(tr("el {day}", day=weekday_name(day.weekday())))
        if not events:
            return tr("{when} no tienes nada en el calendario.", when=name)
        return tr("{when} tienes {count}: {events}.", when=name, count=count_phrase(events),
                  events=say_events(events, day.tzinfo))

    async def _next(self, person: str | None = None) -> str:
        now = self._now()
        events = [e for e in await self._events(now, now + timedelta(days=14), person) if not e.all_day and e.start >= now]
        if not events:
            return "No tienes nada en el calendario en las próximas dos semanas."
        event = events[0]
        at = event.start.astimezone(now.tzinfo)
        days = (_start_of(at) - _start_of(now)).days
        when = tr("hoy") if days == 0 else tr("mañana") if days == 1 else tr(
            "el {day} {number}", day=weekday_name(at.weekday()), number=at.day)
        return tr("Lo siguiente es {title}, {when} a {hour}.", title=event.title, when=when,
                  hour=clock_words(at.hour, at.minute, on_the_hour=""))


def _when_phrase(when: When, now: datetime) -> str:
    """«mañana a las 10 de la mañana», «el martes 3 de noviembre a las 5 de la tarde», «el sábado (todo el día)»."""
    days = (when.day - now.date()).days
    if days == 0:
        day = tr("hoy")
    elif days == 1:
        day = tr("mañana")
    else:
        day = tr("el {day} {number}", day=weekday_name(when.day.weekday()), number=when.day.day)
    if when.all_day:
        return tr("{day}, todo el día", day=day)
    return tr("{day} a {hour}", day=day, hour=clock_words(when.hour or 0, when.minute, on_the_hour=""))
