import numpy as np

from voxa.audio.clip import Clip
from voxa.audio.devices import SilentOutput
from voxa.audio.sounds import make_sounds
from voxa.core.assistant import Assistant
from voxa.nlu import load_matcher
from voxa.services.simulated import SimulatedMusic
from voxa.skills.music import MusicSkill
from voxa.voice import VoiceSession

SOUNDS = make_sounds()


class FakeMic:
    def __init__(self, audio):
        self.audio = audio
        self.skipped = None

    async def record_utterance(self, collector, skip_ms=0, clear=True):
        self.skipped, self.cleared = skip_ms, clear
        return self.audio


class FakeStt:
    name = "fake"

    def __init__(self, text):
        self.text = text

    def transcribe(self, samples):
        return self.text


class FakeTts:
    def __init__(self):
        self.said = []

    def synthesize(self, text):
        self.said.append(text)
        return Clip(np.zeros(100, dtype=np.float32), 22050)


class RecordingDucker:
    def __init__(self):
        self.events = []

    async def duck(self):
        self.events.append("duck")

    async def restore(self):
        self.events.append("restore")


def session(text, tts=None):
    music = SimulatedMusic()
    assistant = Assistant(load_matcher(), {"music": MusicSkill(music)})
    output, ducker = SilentOutput(), RecordingDucker()
    voice = VoiceSession(assistant, FakeStt(text), tts, output, SOUNDS, ducker, echo_guard_ms=320)
    return voice, output, ducker, music


async def test_full_turn_speaks_answer_with_music_ducked():
    tts = FakeTts()
    voice, output, ducker, music = session("pon soda stereo", tts)
    mic = FakeMic(np.ones(16000, dtype=np.int16))
    result = await voice.turn(mic)
    assert result.heard == "pon soda stereo"
    assert result.response.speech == "Soda Stereo."
    assert tts.said == ["Soda Stereo."]
    assert output.played[0] is SOUNDS["listening"]
    assert mic.skipped == 320
    assert ducker.events == ["duck", "restore"]
    assert music.calls == ["play:soda stereo"]


async def test_sound_only_answer_plays_earcon():
    voice, output, _, _ = session("pausa", FakeTts())
    await voice.turn(FakeMic(np.ones(16000, dtype=np.int16)))
    assert output.played[-1] is SOUNDS["ok"]


async def test_silence_plays_cancel_and_restores_music():
    voice, output, ducker, _ = session("pausa")
    result = await voice.turn(FakeMic(None))
    assert result.heard is None and output.played[-1] is SOUNDS["cancel"]
    assert ducker.events == ["duck", "restore"]


async def test_unintelligible_audio_plays_error():
    voice, output, _, _ = session("")
    result = await voice.turn(FakeMic(np.ones(100, dtype=np.int16)))
    assert result.heard == "" and output.played[-1] is SOUNDS["error"]


async def test_alarm_announcement():
    tts = FakeTts()
    voice, output, ducker, _ = session("", tts)
    await voice.announce("¡Terminó el temporizador del arroz!")
    assert output.played[0] is SOUNDS["alarm"]
    assert tts.said == ["¡Terminó el temporizador del arroz!"]
    assert ducker.events == ["duck", "restore"]


async def test_turn_after_wake_word_keeps_the_queued_audio():
    """«Hey Voxa, pon Soda Stereo» de corrido: lo que ya está en la cola es la orden."""
    voice, output, ducker, music = session("pon soda stereo", FakeTts())
    mic = FakeMic(np.ones(16000, dtype=np.int16))
    result = await voice.turn(mic, after_wake=True)
    assert result.response.speech == "Soda Stereo."
    assert (mic.skipped, mic.cleared) == (0, False)
    assert output.played[0] is SOUNDS["listening"]
    assert ducker.events == ["duck", "restore"]
