"""El calendario de la familia, de solo lectura, desde su dirección secreta en formato iCal.

Google Calendar, iCloud y Outlook dan una dirección privada (``.ics``) para cada calendario: con ella
VOXA lo lee sin pedir acceso a la cuenta. Se baja cada 15 minutos y se guarda en caché, para seguir
respondiendo aunque se vaya el internet. Entiende eventos de todo el día, zonas horarias, eventos
que se repiten (diarios, semanales, mensuales y anuales) con sus excepciones, y los cancelados.
"""

from __future__ import annotations

import calendar as cal
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from voxa.services.http import Http, HttpError

log = logging.getLogger(__name__)

REFRESH_SECONDS = 15 * 60
MAX_BYTES = 5 << 20
_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_DURATION = re.compile(r"^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_MAX_OCCURRENCES = 3000


class CalendarUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Event:
    title: str
    start: datetime
    """Con zona horaria; los de todo el día empiezan a las 00:00 de la casa."""
    end: datetime
    all_day: bool = False
    location: str = ""


@dataclass
class _Raw:
    uid: str = ""
    title: str = ""
    location: str = ""
    start: datetime | None = None
    end: datetime | None = None
    duration: timedelta | None = None
    all_day: bool = False
    rrule: dict[str, str] = field(default_factory=dict)
    exdates: set[datetime] = field(default_factory=set)
    recurrence_id: datetime | None = None
    cancelled: bool = False


# --- lectura del .ics ---------------------------------------------------------------------
def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    return lines


def _split(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    return name.upper(), {k.upper(): v.strip('"') for k, _, v in (p.partition("=") for p in params)}, value


def _text(value: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value).strip()


def _zone(name: str | None, home: tzinfo) -> tzinfo:
    if not name:
        return home
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return home  # nombres de Windows («Central Standard Time (Mexico)»): la de la casa


def _when(value: str, params: dict[str, str], home: tzinfo) -> tuple[datetime, bool]:
    """(momento con zona, es de todo el día)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        day = datetime.strptime(value[:8], "%Y%m%d")
        return day.replace(tzinfo=home), True
    moment = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return moment.replace(tzinfo=ZoneInfo("UTC")), False
    return moment.replace(tzinfo=_zone(params.get("TZID"), home)), False


def _duration(value: str) -> timedelta | None:
    m = _DURATION.match(value.strip())
    if not m:
        return None
    sign, weeks, days, hours, minutes, seconds = m.groups()
    delta = timedelta(weeks=int(weeks or 0), days=int(days or 0), hours=int(hours or 0),
                      minutes=int(minutes or 0), seconds=int(seconds or 0))
    return -delta if sign == "-" else delta


def parse_ics(text: str, home: tzinfo) -> list[_Raw]:
    events: list[_Raw] = []
    current: _Raw | None = None
    for line in _unfold(text):
        name, params, value = _split(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            current = _Raw()
        elif name == "END" and value.upper() == "VEVENT":
            if current is not None and current.start is not None:
                events.append(current)
            current = None
        elif current is None:
            continue
        else:
            try:
                _read_property(current, name, params, value, home)
            except ValueError as exc:
                log.debug("Calendario: %s mal escrito (%s): %s", name, value, exc)
    return events


def _read_property(event: _Raw, name: str, params: dict[str, str], value: str, home: tzinfo) -> None:
    if name == "UID":
        event.uid = value
    elif name == "SUMMARY":
        event.title = _text(value)
    elif name == "LOCATION":
        event.location = _text(value)
    elif name == "DTSTART":
        event.start, event.all_day = _when(value, params, home)
    elif name == "DTEND":
        event.end, _ = _when(value, params, home)
    elif name == "DURATION":
        event.duration = _duration(value)
    elif name == "RRULE":
        event.rrule = {k.upper(): v for k, _, v in (p.partition("=") for p in value.split(";"))}
    elif name == "EXDATE":
        for part in value.split(","):
            event.exdates.add(_when(part, params, home)[0])
    elif name == "RECURRENCE-ID":
        event.recurrence_id = _when(value, params, home)[0]
    elif name == "STATUS" and value.upper() == "CANCELLED":
        event.cancelled = True


# --- eventos que se repiten --------------------------------------------------------------
def _add_months(day: date, months: int) -> tuple[int, int]:
    index = day.year * 12 + day.month - 1 + months
    return index // 12, index % 12 + 1


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> int | None:
    days = [d for d in range(1, cal.monthrange(year, month)[1] + 1) if date(year, month, d).weekday() == weekday]
    if not days or abs(nth) > len(days) or nth == 0:
        return None
    return days[nth - 1] if nth > 0 else days[nth]


def _occurrences(event: _Raw, since: datetime, until: datetime) -> list[datetime]:
    """Los inicios del evento hasta ``until`` (en la hora de pared de su zona, como manda iCal).

    Sin COUNT se salta directo a cerca de ``since``: un evento diario desde 2015 no se recorre entero.
    """
    start = event.start
    assert start is not None
    rule = event.rrule
    if not rule:
        return [start]
    freq = rule.get("FREQ", "").upper()
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    limit = until
    if rule.get("UNTIL"):
        last, _ = _when(rule["UNTIL"], {}, start.tzinfo)
        limit = min(limit, last)
    zone, wall = start.tzinfo, start.replace(tzinfo=None)
    byday = [d for d in rule.get("BYDAY", "").split(",") if d]
    bymonthday = [int(d) for d in rule.get("BYMONTHDAY", "").split(",") if d.lstrip("-").isdigit()]

    skip = 0
    if count is None and since.replace(tzinfo=None) > wall:
        gap = since.astimezone(zone).replace(tzinfo=None) - wall
        periods = {"DAILY": gap.days, "WEEKLY": gap.days // 7,
                   "MONTHLY": gap.days * 12 // 366, "YEARLY": gap.days // 366}.get(freq, 0)
        skip = max(0, periods // interval - 1)

    def group(k: int) -> list[datetime]:
        if freq == "DAILY":
            return [wall + timedelta(days=k * interval)]
        if freq == "WEEKLY":
            monday = wall - timedelta(days=wall.weekday()) + timedelta(weeks=k * interval)
            days = sorted({_WEEKDAYS[d[-2:]] for d in byday if d[-2:] in _WEEKDAYS}) or [wall.weekday()]
            return [monday + timedelta(days=d) for d in days]
        if freq == "MONTHLY":
            year, month = _add_months(wall.date(), k * interval)
            size = cal.monthrange(year, month)[1]
            days: list[int] = []
            for d in byday:
                m = re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", d)
                if m and m.group(1) and (n := _nth_weekday(year, month, _WEEKDAYS[m.group(2)], int(m.group(1)))):
                    days.append(n)
            days += [d if d > 0 else size + d + 1 for d in bymonthday]
            if not byday and not bymonthday:
                days = [wall.day]
            return [wall.replace(year=year, month=month, day=d) for d in sorted(set(days)) if 1 <= d <= size]
        if freq == "YEARLY":
            year = wall.year + k * interval
            if wall.month == 2 and wall.day == 29 and not cal.isleap(year):
                return []
            return [wall.replace(year=year)]
        return [wall] if k == 0 else []

    found: list[datetime] = []
    for k in range(skip, skip + _MAX_OCCURRENCES):
        moments = group(k)
        if not moments and freq not in ("MONTHLY", "YEARLY"):
            break
        for moment in moments:
            if moment < wall:
                continue
            aware = moment.replace(tzinfo=zone)
            if aware > limit or (count is not None and len(found) >= count):
                return found
            found.append(aware)
    return found


def events_between(raw: list[_Raw], start: datetime, end: datetime) -> list[Event]:
    """Los eventos que caen (aunque sea en parte) entre ``start`` y ``end``, ordenados."""
    moved = {(e.uid, e.recurrence_id) for e in raw if e.recurrence_id is not None}
    out: list[Event] = []
    for event in raw:
        if event.cancelled and event.recurrence_id is None:
            continue
        length = (event.end - event.start) if event.end else event.duration or (
            timedelta(days=1) if event.all_day else timedelta(0))
        starts = [event.start] if event.recurrence_id is not None else _occurrences(event, start - length, end)
        for begin in starts:
            if event.recurrence_id is None and (begin in event.exdates or (event.uid, begin) in moved):
                continue
            if event.cancelled:
                continue
            finish = begin + length
            if begin < end and (finish > start or (length == timedelta(0) and begin >= start)):
                out.append(Event(event.title or "Evento", begin, finish, event.all_day, event.location))
    return sorted(out, key=lambda e: (not e.all_day, e.start))


class Calendar:
    """Baja el ``.ics`` (con caché en disco) y responde qué hay en un rango de tiempo."""

    def __init__(
        self,
        url: Callable[[], str | None],
        http: Http,
        cache_path: Path,
        *,
        home: tzinfo | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._url = url
        self._http = http
        self._cache = cache_path
        self.home = home or datetime.now().astimezone().tzinfo
        self._clock = clock
        self._raw: list[_Raw] | None = None
        self._fetched = 0.0

    async def events(self, start: datetime, end: datetime) -> list[Event]:
        return events_between(await self._load(), start, end)

    async def check(self) -> int:
        """Baja el calendario ahora mismo; devuelve cuántos eventos trae (para probar la dirección)."""
        self._fetched = 0.0
        return len(await self._load())

    async def _load(self) -> list[_Raw]:
        if self._raw is not None and self._clock() - self._fetched < REFRESH_SECONDS:
            return self._raw
        url = self._url()
        if not url:
            raise CalendarUnavailable("falta la dirección del calendario")
        try:
            response = await self._http.request("GET", _https(url), timeout=15)
            if response.status != 200 or not isinstance(response.data, str) or "BEGIN:VCALENDAR" not in response.data:
                raise CalendarUnavailable(f"la dirección no devolvió un calendario (HTTP {response.status})")
            text = response.data[:MAX_BYTES]
            self._cache.parent.mkdir(parents=True, exist_ok=True)
            self._cache.write_text(text, encoding="utf-8")
        except (HttpError, CalendarUnavailable, OSError) as exc:
            if self._raw is not None:
                log.info("Calendario sin actualizar (%s): uso el que ya tenía", exc)
                return self._raw
            try:
                text = self._cache.read_text(encoding="utf-8")
            except OSError:
                raise CalendarUnavailable(str(exc)) from None
            log.info("Calendario desde la caché (%s)", exc)
        self._raw, self._fetched = parse_ics(text, self.home), self._clock()
        return self._raw


def _https(url: str) -> str:
    # Google y Apple dan «webcal://»: es la misma dirección por HTTPS.
    url = url.strip()
    return "https://" + url[len("webcal://"):] if url.lower().startswith("webcal://") else url


def personal_calendars(config) -> dict[str, str]:
    """El calendario de cada persona ({nombre: dirección iCal}), en ``calendarios.json`` (600)."""
    import json

    try:
        data = json.loads(config.calendars_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v} if isinstance(data, dict) else {}


def save_personal_calendar(config, person: str, url: str | None) -> None:
    import json

    from voxa.settings import write_private

    calendars = personal_calendars(config)
    if url:
        calendars[person] = url
    else:
        calendars.pop(person, None)
    write_private(config.calendars_path, json.dumps(calendars, ensure_ascii=False))


def valid_url(url: str) -> bool:
    return bool(re.fullmatch(r"(?i)(https|webcal)://[^\s/]+\.[^\s/]+/\S+", url.strip()))
