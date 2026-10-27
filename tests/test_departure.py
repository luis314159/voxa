from datetime import datetime

import pytest

from voxa.config import RoutineConfig
from voxa.departure import Departure, parse_time
from voxa.nlu import load_matcher
from voxa.settings import SettingsError, validate
from voxa.skills.routine import RoutineSkill
from voxa.state.timers import TimerManager

MONDAY = datetime(2026, 10, 26, 7, 0)
SATURDAY = datetime(2026, 10, 31, 7, 0)
SCHOOL = Departure.from_config(RoutineConfig(departure="07:30", checklist="mochila, lonche y uniforme"))


def test_parse_time():
    assert parse_time("07:30") == (7, 30) and parse_time("7:05") == (7, 5)
    assert parse_time("25:00") is None and parse_time("") is None


def test_how_long_until_we_leave():
    assert SCHOOL.how_long(MONDAY) == "Faltan 30 minutos para salir (a las 7 y media de la mañana). No olviden: mochila, lonche y uniforme."
    assert SCHOOL.how_long(SATURDAY).startswith("Hoy no hay salida programada")
    assert Departure.from_config(RoutineConfig()).how_long(MONDAY).startswith("No tengo hora de salida")


def test_warnings_once_each():
    told = set()
    assert SCHOOL.due(MONDAY.replace(minute=10), told) == []
    assert SCHOOL.due(MONDAY.replace(minute=15), told) == ["Faltan 15 minutos para salir. No olviden: mochila, lonche y uniforme."]
    assert SCHOOL.due(MONDAY.replace(minute=15, second=40), told) == []
    assert SCHOOL.due(MONDAY.replace(minute=25), told)[0].startswith("Faltan 5 minutos")
    assert SCHOOL.due(MONDAY.replace(minute=30), told)[0].startswith("¡Hora de salir!")
    assert SCHOOL.due(SATURDAY.replace(minute=15), set()) == []


async def test_good_morning_and_question(tmp_path):
    routine = RoutineSkill(TimerManager(tmp_path / "t.json"), now=lambda: MONDAY, departure=SCHOOL)
    said = (await routine.handle(load_matcher().match("buenos días"))).speech
    assert "Salen a las 7 y media de la mañana: faltan 30 minutos." in said
    said = (await routine.handle(load_matcher().match("¿cuánto falta para salir?"))).speech
    assert said.startswith("Faltan 30 minutos para salir")


def test_settings_validate_time_and_days():
    assert validate("routine", {"departure": "07:30", "departure_days": [4, 0, 0]}) == {
        "departure": "07:30", "departure_days": [0, 4]}
    with pytest.raises(SettingsError):
        validate("routine", {"departure": "siete"})
    with pytest.raises(SettingsError):
        validate("routine", {"departure_days": [9]})
