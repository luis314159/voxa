import numpy as np
import pytest

from voxa.core.types import Response
from voxa.enroll import NotEnoughRecordings, Training, VoiceEnrollment, folder_name, people
from voxa.nlu import load_matcher

MATCHER = load_matcher()
VOICE = (np.sin(np.arange(16000) / 5) * 3000).astype(np.int16)
SILENCE = np.zeros(16000, np.int16)


def test_names_become_simple_folders():
    assert folder_name("María José") == "maria-jose"
    assert folder_name("  ") == "familia"


@pytest.mark.parametrize("text, name", [
    ("Hey Voxa, aprende mi voz", None),
    ("aprende la voz de Ana", "ana"),
    ("soy Luis, aprende mi voz", "luis"),
    ("apréndete a reconocerme", None),
])
def test_enroll_is_understood(text, name):
    intent = MATCHER.match(text)
    assert intent.name == "voice.enroll"
    assert intent.slots.get("name") == name


class Kitchen:
    def __init__(self, takes, trained=Training(0.95, 0.99, 1)):
        self.takes = list(takes)
        self.said = []
        self.shown = []
        self.trained = trained
        self.trainings = 0

    async def record(self, seconds):
        return self.takes.pop(0) if self.takes else VOICE

    async def say(self, response):
        self.said.append(response.speech or f"<{response.sound}>")

    async def train(self):
        self.trainings += 1
        if isinstance(self.trained, Exception):
            raise self.trained
        return self.trained


def enrollment(tmp_path, kitchen):
    return VoiceEnrollment(tmp_path, kitchen.record, kitchen.say, kitchen.train, kitchen.shown.append,
                           times=3, talk_seconds=1)


async def test_guided_recording_saves_samples_and_trains(tmp_path):
    kitchen = Kitchen([VOICE, SILENCE, VOICE, VOICE])
    response = await enrollment(tmp_path, kitchen).run("Ana")
    assert response.speech == "Listo, ya reconozco tu voz."
    assert len(list((tmp_path / "ana").glob("si_*.wav"))) == 3  # el silencio no cuenta
    assert len(list((tmp_path / "ana").glob("no_*.wav"))) == 1
    assert "No te oí. Otra vez, un poco más fuerte." in kitchen.said
    assert kitchen.said[0].startswith("Vamos a grabar tu voz, Ana.")
    assert "Di «Hey Voxa» (3 de 3)" in kitchen.shown
    assert kitchen.trainings == 1
    assert people(tmp_path) == ["ana"]


async def test_nobody_talking_gives_up_politely(tmp_path):
    kitchen = Kitchen([SILENCE] * 5)
    response = await enrollment(tmp_path, kitchen).run("")
    assert response.sound == "error" and "Acércate" in response.speech
    assert kitchen.trainings == 0


async def test_not_enough_recordings_is_explained(tmp_path):
    kitchen = Kitchen([], trained=NotEnoughRecordings("faltan"))
    response = await enrollment(tmp_path, kitchen).run("Luis")
    assert "me faltan grabaciones" in response.speech


async def test_a_weak_verifier_says_so(tmp_path):
    kitchen = Kitchen([], trained=Training(0.6, 0.99, 2))
    response = await enrollment(tmp_path, kitchen).run("Luis")
    assert "te confundo" in response.speech


async def test_skill_asks_the_service_to_record(tmp_path):
    from voxa.skills.enroll import ENROLL_ACTION, EnrollSkill

    skill = EnrollSkill()
    intent = MATCHER.match("aprende la voz de ana")
    assert (await skill.handle(intent)).sound == "error"  # sin micrófono (modo texto)
    skill.ready = lambda: True
    response = await skill.handle(intent)
    assert response == Response(action=ENROLL_ACTION, target="Ana")


async def test_guided_recording_in_english(tmp_path):
    from voxa.i18n import set_language

    set_language("en")
    kitchen = Kitchen([VOICE, SILENCE, VOICE, VOICE])
    response = await enrollment(tmp_path, kitchen).run("Ana")
    assert response.speech == "Done, I know your voice now."
    assert kitchen.said[0].startswith("Let's record your voice, Ana.")
    assert "I didn't hear you. Once more, a little louder." in kitchen.said
    assert any(s.startswith("Now talk to me about anything") for s in kitchen.said)
    assert kitchen.shown[:1] == ["Say «Hey Voxa» (1 of 3)"] and "Learning your voice…" in kitchen.shown
