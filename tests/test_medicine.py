"""Medicinas con confirmación: pregunta, anota y, si nadie contesta, avisa a otra persona."""

import asyncio

from voxa.app import build_app
from voxa.config import Config, MedicineConfig
from voxa.core.people import speaking
from voxa.medicine import MedicineLog, MedicineTracker, is_medicine, missed_phrase, ring_phrase
from voxa.state.timers import TimerManager


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_which_reminders_are_medicine():
    assert is_medicine("tomar la pastilla de la presión") and is_medicine("la insulina")
    assert is_medicine("take my pills") and not is_medicine("sacar la basura") and not is_medicine(None)


def tracked(**config):
    clock = Clock()
    timers = TimerManager(clock=clock, repeat_seconds=30, ring_timeout_seconds=600)
    tracker = MedicineTracker(MedicineConfig(**config), timers, MedicineLog(clock=clock))
    return clock, timers, tracker


def test_it_asks_again_every_few_minutes_and_then_gives_up():
    clock, timers, tracker = tracked(ask_every_minutes=5, tries=3)
    rang = []
    timers.on_ring = lambda timer: rang.append(ring_phrase(timer))
    timer = timers.add_at(clock.now + 1, "tomar la medicina", kind="reminder", person="Ana")
    clock.now += 2
    timers.check()
    clock.now += 60  # una alarma normal ya habría repetido; la medicina espera 5 minutos
    timers.check()
    assert len(rang) == 1 and rang[0].startswith("Ana, es hora de tu medicina")
    clock.now += 240
    timers.check()
    assert rang[1] == "Ana, ¿ya te tomaste la medicina? la medicina."
    clock.now += 600
    timers.check()
    assert timer not in timers.ringing
    dose = tracker.log.today()[0]
    assert dose.missed and dose.taken is None and dose.person == "Ana"
    assert missed_phrase(timer).startswith("Ana no ha confirmado su medicina de las ")


def test_turning_the_alarm_off_counts_as_taken():
    clock, timers, tracker = tracked()
    timers.add_at(clock.now + 1, "la pastilla", kind="reminder")
    clock.now += 2
    timers.check()
    timers.stop_ringing()
    assert tracker.log.today()[0].taken == clock.now


def test_a_missed_dose_tells_someone_else():
    clock, timers, tracker = tracked(tries=1)
    told = []

    async def notify(text):
        told.append(text)

    tracker.notify = notify

    async def run():
        timers.add_at(clock.now + 1, "la pastilla", kind="reminder", person="Ana")
        clock.now += 2
        timers.check()
        clock.now += 301
        timers.check()
        await asyncio.sleep(0)

    asyncio.run(run())
    assert told and told[0].startswith("Ana no ha confirmado su medicina")


async def test_by_voice(tmp_path):
    app = build_app(Config(state_dir=tmp_path), simulated=True)
    say = app.assistant.handle_text
    assert (await say("recuérdale a Ana que se tome la pastilla de la presión a las 8")).speech
    timer = app.timers.active[0]
    app.timers.snooze(timer, 0)
    app.timers.check()
    assert app.medicine.ringing()
    said = await say("todavía no")
    assert said.speech == "Va, te pregunto otra vez en 5 minutos." and not app.timers.ringing
    app.timers.snooze(timer, 0)
    app.timers.check()
    with speaking("Ana"):
        assert (await say("ya me la tomé")).speech == "¡Muy bien, Ana! Lo anoté."
    assert not app.timers.ringing
    said = await say("¿ya se tomó Ana la medicina?")
    assert said.speech.startswith("Sí: la pastilla de la presión, a las ")


async def test_without_an_alarm_it_is_only_a_question():
    app = build_app(Config(), simulated=True)
    assert (await app.assistant.handle_text("ya me tomé la pastilla")).speech == "Hoy no tengo medicinas anotadas."
    assert app.medicine.log.today() == []


def test_confirmation_can_be_turned_off():
    clock, timers, tracker = tracked(enabled=False)
    timer = timers.add_at(clock.now + 1, "la pastilla", kind="reminder")
    assert not tracker.watches(timer) and timers.ring_rules(timer) is None
