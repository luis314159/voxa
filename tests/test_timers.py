from voxa.core.phrases import falta, format_duration, format_remaining, of_label
from voxa.core.types import Intent
from voxa.skills.timers import TimerSkill, ring_phrase
from voxa.state.timers import TimerManager, label_key


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make(tmp_path=None, **kwargs):
    clock = FakeClock()
    rang = []
    manager = TimerManager(tmp_path / "timers.json" if tmp_path else None, clock=clock, on_ring=rang.append, **kwargs)
    return manager, clock, rang


def test_timer_rings_once_then_repeats_until_stopped():
    manager, clock, rang = make(repeat_seconds=30)
    manager.add(60, "el arroz")
    clock.now += 59
    manager.check()
    assert rang == []
    clock.now += 1
    manager.check()
    assert len(rang) == 1 and manager.ringing
    clock.now += 10
    manager.check()
    assert len(rang) == 1
    clock.now += 20
    manager.check()
    assert len(rang) == 2
    manager.stop_ringing()
    clock.now += 60
    manager.check()
    assert len(rang) == 2 and not manager.ringing


def test_alarm_gives_up_after_timeout():
    manager, clock, _ = make(ring_timeout_seconds=600)
    manager.add(10)
    clock.now += 10
    manager.check()
    clock.now += 600
    manager.check()
    assert not manager.ringing and not manager.active


def test_timers_survive_restart(tmp_path):
    manager, clock, _ = make(tmp_path)
    manager.add(600, "el arroz")
    clock.now += 100
    restored = TimerManager(tmp_path / "timers.json", clock=clock)
    assert [t.label for t in restored.active] == ["el arroz"]
    assert restored.remaining(restored.active[0]) == 500
    assert restored.add(60).id == 2


def test_old_expired_timers_are_dropped_on_restart(tmp_path):
    manager, clock, _ = make(tmp_path)
    manager.add(60)
    clock.now += 2 * 3600
    assert TimerManager(tmp_path / "timers.json", clock=clock).active == []


def test_label_key_ignores_articles():
    assert label_key("al arroz") == label_key("el arroz") == label_key("arroz") == "arroz"


async def test_skill_conversation():
    manager, clock, _ = make()
    skill = TimerSkill(manager)
    said = await skill.handle(Intent("timer.set", {"duration": 600, "name": "el arroz"}))
    assert said.speech == "10 minutos para el arroz."
    await skill.handle(Intent("timer.set", {"duration": 1800, "name": "el horno"}))
    clock.now += 330
    said = await skill.handle(Intent("timer.query", {"name": "arroz"}))
    assert said.speech == "Faltan 5 minutos para el arroz."
    said = await skill.handle(Intent("timer.query"))
    assert said.speech == "Tienes 2: el arroz, 5 minutos y el horno, 25 minutos."
    said = await skill.handle(Intent("timer.cancel"))
    assert said.speech.startswith("¿Cuál?")
    said = await skill.handle(Intent("timer.cancel", {"name": "horno"}))
    assert said.speech == "Cancelé el temporizador del horno."
    said = await skill.handle(Intent("timer.query", {"name": "pastel"}))
    assert said.speech == "No encontré un temporizador de pastel."


async def test_skill_rejects_absurd_durations():
    manager, _, _ = make()
    said = await TimerSkill(manager).handle(Intent("timer.set", {"duration": 3 * 86400}))
    assert said.sound == "error" and not manager.active


def test_phrases():
    assert format_duration(60) == "un minuto"
    assert format_duration(3600) == "una hora"
    assert format_duration(5400) == "una hora y 30 minutos"
    assert format_duration(3725) == "una hora, 2 minutos y 5 segundos"
    assert format_remaining(241) == "5 minutos"
    assert format_remaining(80) == "un minuto y 20 segundos"
    assert falta("un minuto") == "Falta un minuto"
    assert falta("4 minutos") == "Faltan 4 minutos"
    assert of_label("el arroz") == "del arroz"
    assert of_label("la sopa") == "de la sopa"


def test_ring_phrase():
    manager, _, _ = make()
    assert ring_phrase(manager.add(600, "el arroz")) == "¡Terminó el temporizador del arroz!"
    assert ring_phrase(manager.add(300)) == "¡Terminaron los 5 minutos!"


# --- recordatorios a una hora fija ---------------------------------------------------------
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from voxa.nlu.numbers import parse_clock  # noqa: E402
from voxa.skills.timers import next_occurrence  # noqa: E402

NOW = datetime(2026, 10, 24, 15, 20)  # sábado, 3:20 de la tarde


@pytest.mark.parametrize(
    ("said", "tomorrow", "expected"),
    [
        ("siete", False, datetime(2026, 10, 24, 19, 0)),  # sin «de la…»: la próxima vez que sean las 7
        ("tres", False, datetime(2026, 10, 25, 3, 0)),  # las 15:00 ya pasaron
        ("siete de la manana", False, datetime(2026, 10, 25, 7, 0)),
        ("ocho y media de la noche", False, datetime(2026, 10, 24, 20, 30)),
        ("siete menos cuarto", False, datetime(2026, 10, 24, 18, 45)),
        ("19 45", False, datetime(2026, 10, 24, 19, 45)),
        ("mediodia", False, datetime(2026, 10, 25, 12, 0)),
        ("medianoche", False, datetime(2026, 10, 25, 0, 0)),
        ("una de la madrugada", False, datetime(2026, 10, 25, 1, 0)),
        ("una de la tarde", False, datetime(2026, 10, 25, 13, 0)),
        ("siete", True, datetime(2026, 10, 25, 7, 0)),  # «mañana a las 7»: la primera de mañana
        ("diez de la noche", True, datetime(2026, 10, 25, 22, 0)),
    ],
)
def test_next_occurrence(said, tomorrow, expected):
    assert next_occurrence(parse_clock(said), NOW, tomorrow=tomorrow) == expected


def test_impossible_hours_are_rejected():
    assert next_occurrence((15, 0, "manana"), NOW) is None
    assert parse_clock("veinticinco") is None


async def test_reminder_conversation():
    timers = TimerManager(clock=lambda: NOW.timestamp())
    skill = TimerSkill(timers, now=lambda: NOW)
    said = await skill.handle(Intent("timer.remind", {"time": (8, 0, "noche"), "name": "sacar la basura"}))
    assert said.speech == "A las 8 de la noche te recuerdo sacar la basura."
    said = await skill.handle(Intent("timer.remind", {"time": (7, 0, None), "day": "manana"}))
    assert said.speech == "Alarma para mañana a las 7 de la mañana."
    said = await skill.handle(Intent("timer.remind", {"time": (5, 30, "tarde")}))
    assert said.speech == "Alarma para las 5 y media de la tarde."
    basura, alarma, tarde = timers.active[1], timers.active[2], timers.active[0]
    assert basura.is_reminder and basura.ends_at == datetime(2026, 10, 24, 20, 0).timestamp()
    assert ring_phrase(basura) == "Te recuerdo: sacar la basura."
    assert ring_phrase(alarma) == "¡Son las 7 de la mañana!"
    assert ring_phrase(tarde) == "¡Son las 5 y media de la tarde!"
    said = await skill.handle(Intent("timer.cancel", {"name": "basura"}))
    assert "basura" in said.speech and len(timers.active) == 2


def test_reminders_survive_restart(tmp_path):
    store = tmp_path / "timers.json"
    TimerManager(store, clock=lambda: 1000.0).add(3600, "regar", kind="reminder")
    loaded = TimerManager(store, clock=lambda: 1000.0).active[0]
    assert loaded.is_reminder and loaded.label == "regar"
