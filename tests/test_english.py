"""VOXA en inglés (language = "en"): entiende y contesta en inglés lo de todos los días."""

import pytest

from voxa.app import build_app
from voxa.config import Config, VoiceConfig, read_config
from voxa.nlu import load_matcher
from voxa.nlu.numbers_en import parse_clock, parse_duration, parse_number

EN = load_matcher(language="en")


@pytest.mark.parametrize("text, seconds", [
    ("ten minutes", 600), ("an hour and a half", 5400), ("half an hour", 1800),
    ("a quarter of an hour", 900), ("90 seconds", 90), ("two hours and thirty minutes", 9000),
])
def test_durations(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text, clock", [
    ("seven thirty pm", (7, 30, "tarde")), ("half past 7", (7, 30, None)), ("a quarter to 8", (8, -15, None)),
    ("noon", (12, 0, "dia")), ("7 in the evening", (7, 0, "noche")), ("6 am", (6, 0, "manana")),
])
def test_clock(text, clock):
    assert parse_clock(text) == clock


def test_numbers():
    assert parse_number("thirty five") == 35 and parse_number("seventy percent") == 70


@pytest.mark.parametrize("text, intent, slots", [
    ("Hey Voxa, set a timer for ten minutes", "timer.set", {"duration": 600}),
    ("set a 5 minute timer for the pasta", "timer.set", {"duration": 300, "name": "pasta"}),
    ("give it five more minutes", "timer.adjust", {"duration": 300, "sign": 1}),
    ("remind me to take out the trash at 8 pm", "timer.remind", {"name": "take out the trash"}),
    ("remind Ana to take her medicine at 9 pm", "timer.remind", {"person": "ana"}),
    ("wake me up on weekdays at 6", "timer.remind", {}),
    ("what's the weather like", "weather.current", {}),
    ("add milk and eggs to the shopping list", "shopping.add", {"query": "milk and eggs"}),
    ("play my likes", "music.play", {"kind": "liked"}),
    ("tell everyone that dinner is ready", "house.announce", {"query": "dinner is ready"}),
    ("how long until we leave", "routine.departure", {}),
])
def test_english_commands(text, intent, slots):
    found = EN.match(text)
    assert found is not None and found.name == intent
    for key, value in slots.items():
        assert found.slots[key] == value


async def test_english_answers():
    app = build_app(Config(voice=VoiceConfig(language="en")), simulated=True)

    async def say(text):
        return (await app.assistant.handle_text(text)).speech

    assert await say("set a timer for ten minutes for the rice") == "10 minutes for rice."
    assert await say("add five more minutes to the rice") == "Added 5 minutes to the rice timer: 15 minutes left."
    assert await say("cancel the rice timer") == "Canceled the rice timer."
    assert await say("add milk and eggs to the shopping list") == "Added milk and eggs to the list."
    assert await say("we bought the milk") == "Removed milk from the list."
    assert await say("set the volume to 30") == "Volume at 30."
    assert (await say("blah blah")).startswith("Sorry, I didn't get that.")
    assert await say("thanks") == "You're welcome!"


def test_english_uses_english_models(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[voice]\nlanguage = "en"\n', encoding="utf-8")
    voice = read_config(path)[0].voice
    assert voice.vosk_model.endswith("vosk-model-small-en-us-0.15")
    assert voice.piper_voice.endswith("en_US-lessac-medium.onnx")
