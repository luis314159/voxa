"""Agregar citas al calendario de Google por voz («agrega dentista el martes a las 5 al calendario»)."""

import json
from datetime import date, datetime

import pytest

from voxa.app import build_app
from voxa.config import Config, VoiceConfig
from voxa.nlu.when import parse_when
from voxa.services.google_calendar import GoogleAuth, GoogleCalendarWriter, GoogleClient, GoogleError
from voxa.services.http import HttpResponse

TUESDAY_NOON = datetime(2026, 10, 27, 12, 0)


@pytest.mark.parametrize("said, title, day, hour", [
    ("dentista el martes a las 5", "dentista", date(2026, 11, 3), 17),
    ("la junta de la escuela el 3 de noviembre a las 6 de la tarde", "junta de la escuela", date(2026, 11, 3), 18),
    ("cita con el doctor mañana a las 10", "cita con el doctor", date(2026, 10, 28), 10),
    ("vacuna del perro el 15 a las 9 de la mañana", "vacuna del perro", date(2026, 11, 15), 9),
    ("futbol pasado mañana a las 4 y media", "futbol", date(2026, 10, 29), 16),
    ("el cumpleaños de Ana el sábado", "cumpleaños de Ana", date(2026, 10, 31), None),
    ("comida con mis papás a las 2", "comida con mis papás", date(2026, 10, 27), 14),
])
def test_when_in_spanish(said, title, day, hour):
    when = parse_when(said, TUESDAY_NOON)
    assert (when.title, when.day, when.hour) == (title, day, hour)


@pytest.mark.parametrize("said, title, day, hour", [
    ("dentist on tuesday at 5 pm", "dentist", date(2026, 11, 3), 17),
    ("school meeting on november 3rd at 6", "school meeting", date(2026, 11, 3), 18),
    ("doctor tomorrow at 10 am", "doctor", date(2026, 10, 28), 10),
])
def test_when_in_english(said, title, day, hour):
    when = parse_when(said, TUESDAY_NOON, english=True)
    assert (when.title, when.day, when.hour) == (title, day, hour)


def test_without_a_day_or_time_it_asks():
    assert parse_when("dentista", TUESDAY_NOON) is None


class FakeHttp:
    def __init__(self, status=200):
        self.status = status
        self.requests = []

    async def request(self, method, url, *, params=None, headers=None, json_body=None, form=None, timeout=8.0):
        self.requests.append({"method": method, "url": url, "json": json_body, "form": form, "headers": headers})
        if url.endswith("/token"):
            return HttpResponse(200, {"access_token": "nuevo", "expires_in": 3600})
        return HttpResponse(self.status, {"htmlLink": "https://calendar.google.com/x"})


def writer(tmp_path, status=200, expires_at=99_999_999_999):
    (tmp_path / "token.json").write_text(json.dumps({"access_token": "T", "refresh_token": "R", "expires_at": expires_at}))
    http = FakeHttp(status)
    auth = GoogleAuth(GoogleClient("id", "secreto"), tmp_path / "token.json", http)
    return GoogleCalendarWriter(auth, http, "familia@group.calendar.google.com"), http


async def test_an_appointment_with_time_lasts_an_hour(tmp_path):
    calendar, http = writer(tmp_path)
    await calendar.add("Dentista", datetime(2026, 11, 3, 17, 0))
    sent = http.requests[0]
    assert "familia%40group.calendar.google.com" in sent["url"] and sent["headers"]["Authorization"] == "Bearer T"
    assert sent["json"]["summary"] == "Dentista"
    assert sent["json"]["start"]["dateTime"].startswith("2026-11-03T17:00:00")
    assert sent["json"]["end"]["dateTime"].startswith("2026-11-03T18:00:00")


async def test_an_all_day_event_and_an_expired_token(tmp_path):
    calendar, http = writer(tmp_path, expires_at=0)
    await calendar.add("Cumpleaños de Ana", date(2026, 10, 31))
    assert http.requests[0]["form"]["grant_type"] == "refresh_token"
    assert http.requests[0]["form"]["client_secret"] == "secreto"
    assert http.requests[1]["json"]["start"] == {"date": "2026-10-31"} and http.requests[1]["json"]["end"] == {"date": "2026-11-01"}
    assert json.loads((tmp_path / "token.json").read_text())["refresh_token"] == "R"  # se conserva


async def test_google_errors_are_explained(tmp_path):
    calendar, _ = writer(tmp_path, status=404)
    with pytest.raises(GoogleError, match="no encontré el calendario"):
        await calendar.add("Dentista", date(2026, 11, 3))


class Recorder:
    def __init__(self):
        self.added = []

    async def add(self, title, start, *, minutes=60):
        self.added.append((title, start))
        return ""


async def test_by_voice(monkeypatch):
    import voxa.skills.calendar as calendar_skill

    app = build_app(Config(), simulated=True)
    skill = app.assistant.skill("calendar")
    said = await app.assistant.handle_text("agrega dentista el martes a las 5 al calendario")
    assert said.speech.startswith("Para agregar citas, conecta Google Calendar")
    recorder = Recorder()
    skill.writer = lambda: recorder
    skill._now = lambda: TUESDAY_NOON.astimezone()
    said = await app.assistant.handle_text("agrega dentista el martes a las 5 al calendario")
    assert said.speech == "Listo, lo anoté en el calendario: dentista, el martes 3 a las 5 de la tarde."
    assert recorder.added == [("dentista", datetime(2026, 11, 3, 17, 0))]
    said = await app.assistant.handle_text("hazme una cita con el doctor mañana a las 10")
    assert said.speech == "Listo, lo anoté en el calendario: cita con el doctor, mañana a las 10 de la mañana."
    said = await app.assistant.handle_text("agenda el cumpleaños de Ana el sábado")
    assert said.speech.endswith("el sábado 31, todo el día.")


async def test_by_voice_in_english():
    app = build_app(Config(voice=VoiceConfig(language="en")), simulated=True)
    skill = app.assistant.skill("calendar")
    recorder = Recorder()
    skill.writer = lambda: recorder
    skill._now = lambda: TUESDAY_NOON.astimezone()
    said = await app.assistant.handle_text("add dentist on tuesday at 5 pm to the calendar")
    assert said.speech == "Done, it's on the calendar: dentist, on Tuesday the 3 at 5 in the afternoon."
