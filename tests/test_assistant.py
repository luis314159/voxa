from datetime import datetime

import pytest

from voxa.core.assistant import Assistant
from voxa.nlu import load_matcher
from voxa.services.simulated import SimulatedMusic, SimulatedVolume
from voxa.skills.clock import ClockSkill
from voxa.skills.music import MusicSkill
from voxa.skills.system import SystemSkill
from voxa.skills.timers import TimerSkill
from voxa.skills.volume import VolumeSkill
from voxa.state.timers import TimerManager


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def home():
    clock = Clock()
    music, volume = SimulatedMusic(), SimulatedVolume(40)
    timers = TimerManager(clock=clock)
    skills = {
        "music": MusicSkill(music),
        "volume": VolumeSkill(volume, step=10),
        "timer": TimerSkill(timers),
        "clock": ClockSkill(lambda: datetime(2026, 10, 23, 15, 25)),
        "system": SystemSkill(),
    }
    assistant = Assistant(load_matcher(), skills, timers)
    return assistant, music, volume, timers, clock


async def test_music_flow(home):
    assistant, music, *_ = home
    assert (await assistant.handle_text("Hey Voxa, pon Soda Stereo")).speech == "Soda Stereo."
    assert (await assistant.handle_text("pausa")).sound == "ok"
    assert (await assistant.handle_text("qué canción es esta")).speech == "Soda Stereo."
    await assistant.handle_text("la siguiente")
    await assistant.handle_text("adelanta treinta")
    assert music.calls == ["play:soda stereo", "pause", "next", "seek:30"]


async def test_volume_steps(home):
    assistant, _, volume, *_ = home
    await assistant.handle_text("súbele")
    assert volume.state.percent == 50
    await assistant.handle_text("bájale un poco")
    assert volume.state.percent == 45
    said = await assistant.handle_text("volumen a ciento cincuenta")
    assert said.speech == "Volumen al 100." and volume.state.percent == 100


async def test_stop_words_silence_a_ringing_alarm_instead_of_pausing_music(home):
    assistant, music, _, timers, clock = home
    await assistant.handle_text("temporizador de un minuto para la sopa")
    clock.now += 60
    timers.check()
    assert timers.ringing
    await assistant.handle_text("ya")
    assert not timers.ringing
    assert "pause" not in music.calls
    # Sin alarma, «para» vuelve a ser pausa.
    await assistant.handle_text("para")
    assert music.calls[-1] == "pause"


async def test_repeat_returns_last_spoken_response(home):
    assistant, *_ = home
    first = await assistant.handle_text("qué hora es")
    assert first.speech == "Son las 3 y 25 de la tarde."
    await assistant.handle_text("súbele")  # solo sonido: no reemplaza lo último dicho
    assert (await assistant.handle_text("¿qué dijiste?")) == first


async def test_unknown_and_unimplemented(home):
    assistant, *_ = home
    assert (await assistant.handle_text("el gato está en la azotea")).speech.startswith("No te entendí")
    assert (await assistant.handle_text("pon un video de pozole")).speech.startswith("Todavía no sé poner videos")
    assert (await assistant.handle_text("clima")).speech == "Todavía no sé hacer eso."


async def test_mute_mic_asks_runtime_to_act(home):
    assistant, *_ = home
    assert (await assistant.handle_text("deja de escuchar")).action == "mic.mute"


async def test_skill_crash_is_contained(home):
    assistant, music, *_ = home

    async def boom(*_):
        raise RuntimeError("falla inesperada")

    music.pause = boom
    said = await assistant.handle_text("pausa")
    assert said.sound == "error"
