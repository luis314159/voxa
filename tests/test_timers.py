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
