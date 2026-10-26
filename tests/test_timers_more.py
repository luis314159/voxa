from datetime import datetime, timedelta

import pytest

from voxa.core.assistant import Assistant
from voxa.core.phrases import days_phrase
from voxa.nlu import load_matcher
from voxa.nlu.days import parse_days
from voxa.skills.timers import TimerSkill
from voxa.state.timers import TimerManager

START = datetime(2026, 10, 24, 15, 20)  # sábado, 3:20 de la tarde


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now.timestamp()

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def kitchen(tmp_path):
    clock = Clock()
    rang = []
    timers = TimerManager(tmp_path / "timers.json", clock=clock, on_ring=rang.append)
    skill = TimerSkill(timers, now=lambda: clock.now)
    assistant = Assistant(load_matcher(), {"timer": skill}, timers)

    async def say(text):
        return (await assistant.handle_text(text)).speech

    return say, timers, clock, rang


@pytest.mark.parametrize("text, days, repeat", [
    ("de lunes a viernes", {0, 1, 2, 3, 4}, True),
    ("entre semana", {0, 1, 2, 3, 4}, True),
    ("los fines de semana", {5, 6}, True),
    ("todos los dias", set(range(7)), True),
    ("los martes y jueves", {1, 3}, True),
    ("de viernes a domingo", {4, 5, 6}, True),
    ("los sabados", {5}, True),
    ("el viernes", {4}, False),
    ("el proximo lunes", {0}, False),
])
def test_days_are_understood(text, days, repeat):
    assert parse_days(text) == (frozenset(days), repeat)


def test_days_are_said_naturally():
    assert days_phrase([0, 1, 2, 3, 4]) == "de lunes a viernes"
    assert days_phrase([5, 6]) == "los fines de semana"
    assert days_phrase(range(7)) == "todos los días"
    assert days_phrase([1, 3]) == "los martes y jueves"
    assert days_phrase([5]) == "los sábados"


async def test_adjust_pause_and_resume(kitchen):
    say, timers, clock, _ = kitchen
    await say("pon un temporizador de 10 minutos para el arroz")
    clock.advance(minutes=2)
    assert await say("agrégale 5 minutos al arroz") == "Le agregué 5 minutos al arroz: faltan 13 minutos."
    assert await say("quítale 2 minutos") == "Le quité 2 minutos al arroz: faltan 11 minutos."
    assert await say("pausa el temporizador") == "Pausé el temporizador del arroz; quedan 11 minutos."
    clock.advance(minutes=30)  # en pausa no corre ni suena
    timers.check()
    assert not timers.ringing and timers.remaining(timers.active[0]) == 660
    assert await say("cuánto le falta al arroz") == "Faltan 11 minutos."
    assert await say("reanuda el temporizador del arroz") == "Sigue el temporizador del arroz: faltan 11 minutos."
    clock.advance(minutes=11)
    timers.check()
    assert timers.ringing


async def test_many_timers_ask_which_one(kitchen):
    say, *_ = kitchen
    await say("pon un temporizador de 10 minutos para el arroz")
    await say("pon un temporizador de 3 minutos para los huevos")
    assert await say("agrégale un minuto") == "¿A cuál? Tienes los huevos y el arroz."
    assert (await say("agrégale un minuto a los huevos")).startswith("Le agregué un minuto a los huevos")


async def test_five_more_minutes_snoozes_the_ringing_alarm(kitchen):
    say, timers, clock, rang = kitchen
    await say("pon un temporizador de 10 minutos para el pan")
    clock.advance(minutes=10)
    timers.check()
    assert timers.ringing
    assert await say("5 minutos más") == "Te aviso en 5 minutos."
    assert not timers.ringing and timers.remaining(timers.active[0]) == 300
    clock.advance(minutes=5)
    timers.check()
    assert len(rang) == 2


async def test_weekday_alarm_repeats_every_week(kitchen):
    say, timers, clock, rang = kitchen
    assert await say("despiértame de lunes a viernes a las 6") == "Alarma de lunes a viernes a las 6 de la mañana."
    alarm = timers.active[0]
    assert datetime.fromtimestamp(alarm.ends_at) == datetime(2026, 10, 26, 6, 0)  # el lunes
    assert await say("qué recordatorios tengo") == "Alarma, de lunes a viernes a las 6 de la mañana."
    clock.now = datetime(2026, 10, 26, 6, 0)
    timers.check()
    assert len(rang) == 1
    nxt = timers.active[0]
    assert datetime.fromtimestamp(nxt.ends_at) == datetime(2026, 10, 27, 6, 0)  # el martes, ya programada
    timers.stop_ringing()
    clock.now = datetime(2026, 10, 30, 6, 0)  # viernes
    timers.check()
    timers.stop_ringing()
    assert datetime.fromtimestamp(timers.active[0].ends_at) == datetime(2026, 11, 2, 6, 0)  # salta el fin de semana


async def test_weekly_reminder_and_one_time_weekday(kitchen):
    say, timers, *_ = kitchen
    said = await say("recuérdame los martes sacar la basura a las 8 de la noche")
    assert said == "Los martes a las 8 de la noche te recuerdo sacar la basura."
    said = await say("recuérdame el viernes a las 5 de la tarde llamar al doctor")
    assert said == "El viernes a las 5 de la tarde te recuerdo llamar al doctor."
    doctor = next(t for t in timers.active if t.label == "llamar al doctor")
    assert doctor.repeat is None and datetime.fromtimestamp(doctor.ends_at) == datetime(2026, 10, 30, 17, 0)
    assert "cancelé" in (await say("cancela el recordatorio de la basura")).lower()


async def test_wake_up_is_in_the_morning(kitchen):
    say, timers, *_ = kitchen  # son las 3:20 de la tarde
    assert await say("despiértame a las 6") == "Alarma para mañana a las 6 de la mañana."


def test_weekly_alarm_missed_while_off_moves_to_next_time(tmp_path):
    store = tmp_path / "timers.json"
    clock = Clock()
    timers = TimerManager(store, clock=clock)
    timers.add_at(datetime(2026, 10, 26, 6, 0).timestamp(), None, repeat=[0, 1, 2, 3, 4], at=[6, 0])
    clock.now = datetime(2026, 10, 28, 9, 0)  # VOXA estuvo apagada lunes y martes
    loaded = TimerManager(store, clock=clock).active
    assert [datetime.fromtimestamp(t.ends_at) for t in loaded] == [datetime(2026, 10, 29, 6, 0)]
