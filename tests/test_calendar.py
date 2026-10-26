from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from voxa.nlu import load_matcher
from voxa.services.calendar import Calendar, CalendarUnavailable, events_between, parse_ics, valid_url
from voxa.services.http import HttpError, HttpResponse
from voxa.skills.calendar import NOT_SET, CalendarSkill
from voxa.skills.routine import RoutineSkill
from voxa.state.timers import TimerManager

HOME = ZoneInfo("America/Mexico_City")
NOW = datetime(2026, 10, 26, 8, 0, tzinfo=HOME)  # lunes, 8 de la mañana

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Google Inc//Google Calendar 70.9054//EN
BEGIN:VEVENT
UID:dentista
DTSTART;TZID=America/Mexico_City:20261026T090000
DTEND;TZID=America/Mexico_City:20261026T100000
SUMMARY:Dentista
LOCATION:Av. Juárez 10\\, Centro
END:VEVENT
BEGIN:VEVENT
UID:futbol
DTSTART:20260907T230000Z
DTEND:20260908T000000Z
RRULE:FREQ=WEEKLY;BYDAY=MO,WE
EXDATE:20261028T230000Z
SUMMARY:Futbol de Ana
END:VEVENT
BEGIN:VEVENT
UID:cumple
DTSTART;VALUE=DATE:20151026
DTEND;VALUE=DATE:20151027
RRULE:FREQ=YEARLY
SUMMARY:Cumpleaños de
  la abuela
END:VEVENT
BEGIN:VEVENT
UID:clase
DTSTART;TZID=America/Mexico_City:20261001T180000
DTEND;TZID=America/Mexico_City:20261001T190000
RRULE:FREQ=DAILY;COUNT=40
SUMMARY:Clase de piano
END:VEVENT
BEGIN:VEVENT
UID:clase
RECURRENCE-ID;TZID=America/Mexico_City:20261027T180000
DTSTART;TZID=America/Mexico_City:20261027T200000
DTEND;TZID=America/Mexico_City:20261027T210000
SUMMARY:Clase de piano (cambio)
END:VEVENT
BEGIN:VEVENT
UID:junta
DTSTART;TZID=America/Mexico_City:20261026T120000
DURATION:PT30M
SUMMARY:Junta cancelada
STATUS:CANCELLED
END:VEVENT
BEGIN:VEVENT
UID:mensual
DTSTART;TZID=America/Mexico_City:20250101T110000
DTEND;TZID=America/Mexico_City:20250101T113000
RRULE:FREQ=MONTHLY;BYDAY=-1MO
SUMMARY:Pagar la luz
END:VEVENT
END:VCALENDAR
"""


def day(offset=0):
    start = NOW.replace(hour=0) + timedelta(days=offset)
    return start, start + timedelta(days=1)


def titles(offset=0):
    return [e.title for e in events_between(parse_ics(ICS, HOME), *day(offset))]


def test_a_day_with_everything():
    # Lunes 26: el último lunes del mes, cumpleaños (todo el día, primero), dentista, futbol y clase.
    assert titles(0) == ["Cumpleaños de la abuela", "Dentista", "Pagar la luz", "Futbol de Ana", "Clase de piano"]


def test_exceptions_moves_and_cancellations():
    assert titles(1) == ["Clase de piano (cambio)"]  # martes: la clase se movió a las 8
    assert titles(2) == ["Clase de piano"]  # miércoles: el futbol se canceló (EXDATE)
    assert "Junta cancelada" not in titles(0)


def test_count_and_text_details():
    assert titles(40) == []  # la clase ya acabó sus 40 veces
    dentist = events_between(parse_ics(ICS, HOME), *day(0))[1]
    assert dentist.location == "Av. Juárez 10, Centro"
    futbol = events_between(parse_ics(ICS, HOME), *day(0))[-2]
    assert futbol.start.astimezone(HOME).hour == 17  # 23:00 UTC = 5 de la tarde en México


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.urls = []

    async def request(self, method, url, **kwargs):
        self.urls.append(url)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def agenda(tmp_path):
    http = FakeHttp(HttpResponse(200, ICS))
    calendar = Calendar(lambda: "webcal://calendar.google.com/calendar/ical/secreto/basic.ics", http,
                        tmp_path / "cal.ics", home=HOME)
    return CalendarSkill(calendar, now=lambda: NOW), http, calendar


async def ask(skill, text):
    return (await skill.handle(load_matcher().match(text))).speech


async def test_what_do_i_have_today(agenda):
    skill, http, _ = agenda
    said = await ask(skill, "¿qué tengo hoy?")
    assert said == ("Hoy tienes 5 cosas: a las 9 de la mañana, Dentista; a las 11 de la mañana, Pagar la luz; "
                    "a las 5 de la tarde, Futbol de Ana; a las 6 de la tarde, Clase de piano; "
                    "todo el día: Cumpleaños de la abuela.")
    assert http.urls[0].startswith("https://calendar.google.com/")  # webcal:// → https://
    assert (await ask(skill, "qué tengo mañana")).startswith("Mañana tienes una cosa: a las 8 de la noche, Clase de piano (cambio)")
    assert (await ask(skill, "cuál es mi siguiente cita")) == "Lo siguiente es Dentista, hoy a las 9 de la mañana."


async def test_works_offline_with_the_cached_copy(agenda, tmp_path):
    skill, http, calendar = agenda
    await calendar.check()
    http.response = HttpError("sin internet")
    fresh = Calendar(lambda: "https://x.example/cal.ics", http, tmp_path / "cal.ics", home=HOME)
    assert await CalendarSkill(fresh, now=lambda: NOW).today()


async def test_bad_address_is_explained(tmp_path):
    http = FakeHttp(HttpResponse(404, "Not found"))
    calendar = Calendar(lambda: "https://x.example/cal.ics", http, tmp_path / "cal.ics", home=HOME)
    with pytest.raises(CalendarUnavailable):
        await calendar.check()
    response = await CalendarSkill(calendar, now=lambda: NOW).handle(load_matcher().match("qué tengo hoy"))
    assert response.sound == "error"


async def test_without_a_calendar_it_says_how_to_add_one():
    assert (await CalendarSkill(None).handle(load_matcher().match("qué tengo hoy"))).speech == NOT_SET


async def test_good_morning_includes_the_calendar(agenda, tmp_path):
    skill, _, _ = agenda
    routine = RoutineSkill(TimerManager(tmp_path / "t.json"), now=lambda: NOW.replace(tzinfo=None),
                           agenda=skill.today_for_morning)
    said = (await routine.handle(load_matcher().match("buenos días"))).speech
    assert "En el calendario de hoy hay 5 cosas" in said


def test_urls():
    assert valid_url("https://calendar.google.com/calendar/ical/abc%40group/private-123/basic.ics")
    assert valid_url("webcal://p01-caldav.icloud.com/published/2/abc")
    assert not valid_url("http://inseguro.example/cal.ics")
    assert not valid_url("calendario")
