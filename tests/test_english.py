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


@pytest.mark.parametrize("said, answer", [
    ("how many grams is a cup of flour", "A cup of flour is about 125 grams."),
    ("how many tablespoons are in a quarter cup", "A quarter cup is 4 tablespoons."),
    ("200 grams of butter in cups", "200 grams of butter is about a cup."),
    ("two and a half cups of rice in grams", "2 and a half cups of rice is about 460 grams."),
    ("a cup and a half of milk in milliliters", "A cup and a half of milk is 360 milliliters."),
    ("how much does half a cup of brown sugar weigh in grams", "Half a cup of brown sugar is about 110 grams."),
    ("how many ounces is a pound", "A pound is 16 ounces."),
    ("350 degrees fahrenheit in celsius", "350 degrees Fahrenheit is 177 degrees Celsius."),
    ("what is 180 degrees in fahrenheit", "180 degrees Celsius is 356 degrees Fahrenheit."),
])
async def test_kitchen_conversions_in_english(said, answer):
    app = build_app(Config(voice=VoiceConfig(language="en")), simulated=True)
    assert (await app.assistant.handle_text(said)).speech == answer


async def test_unknown_ingredient_in_english():
    app = build_app(Config(voice=VoiceConfig(language="en")), simulated=True)
    said = (await app.assistant.handle_text("how many grams is a cup of gravel")).speech
    assert said == "I don't know how much a cup of gravel weighs. Try flour, sugar, rice or butter."


class FakeChat:
    name = "Prueba · modelo"
    model = "claude-haiku-5-5"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    async def ask(self, system, messages, tools=(), *, max_tokens=2048):
        self.asked.append({"system": system, "messages": messages})
        return self.answers.pop(0)


PANCAKES = {
    "titulo": "Pancakes",
    "porciones": 4,
    "ingredientes": [{"texto": "1 cup of flour", "nombre": "flour"}, {"texto": "1 egg", "nombre": "eggs"}],
    "pasos": [{"texto": "Mix everything", "minutos": 0}, {"texto": "Cook each side.", "minutos": 2}],
}


async def test_recipe_step_by_step_in_english(tmp_path, monkeypatch):
    import voxa.app
    from voxa.config import AiConfig
    from voxa.services.ai import AiAnswer

    chat = FakeChat(AiAnswer(calls=[("mostrar_receta", PANCAKES)]))
    monkeypatch.setattr(voxa.app, "read_key", lambda config, path: "k")
    monkeypatch.setattr(voxa.app, "build_chat", lambda config, key: chat)
    app = build_app(Config(voice=VoiceConfig(language="en"), ai=AiConfig(enabled=True), state_dir=tmp_path,
                           config_dir=tmp_path), simulated=True)

    async def say(text):
        return (await app.assistant.handle_text(text)).speech

    assert await say("give me a recipe for pancakes") == (
        "Pancakes, for 4 servings: 2 ingredients and 2 steps. "
        "Say «the ingredients» and I'll read them, or «next step» to start.")
    assert "escribe la receta (título, ingredientes y pasos) en inglés" in chat.asked[0]["system"]
    assert await say("what ingredients do i need") == "For pancakes you need: 1 cup of flour and 1 egg."
    assert await say("lets start") == "Step 1 of 2: Mix everything."
    assert await say("next step") == (
        "Step 2 of 2: Cook each side. If you want, say «start the timer» and I'll count 2 minutes.")
    assert await say("start the timer") == "Done: 2 minutes for recipe step 2."
    assert await say("go to step 7") == "The recipe has 2 steps."
    assert await say("add the ingredients to the shopping list") == "Added 2 things to the list."
    assert await say("finish the recipe") == "I closed the pancakes recipe."


async def test_ai_commands_work_in_an_english_home(tmp_path, monkeypatch):
    """En inglés la IA ordena en inglés; si se le escapa una orden en español, VOXA también la ejecuta."""
    import voxa.app
    from voxa.config import AiConfig
    from voxa.services.ai import AiAnswer

    chat = FakeChat(AiAnswer(commands=["set a timer for 12 minutes for the pasta"]),
                    AiAnswer(commands=["pon un temporizador de 5 minutos"]))
    monkeypatch.setattr(voxa.app, "read_key", lambda config, path: "k")
    monkeypatch.setattr(voxa.app, "build_chat", lambda config, key: chat)
    app = build_app(Config(voice=VoiceConfig(language="en"), ai=AiConfig(enabled=True), state_dir=tmp_path,
                           config_dir=tmp_path), simulated=True)
    said = await app.assistant.handle_text("keep an eye on the pasta for about twelve minutes")
    assert said.speech == "12 minutes for pasta."
    assert "«set a timer for 12 minutes for the pasta»" in chat.asked[0]["system"]
    assert (await app.assistant.handle_text("start a little countdown for the eggs")).speech == "5 minutes. Starting now."
    assert sorted(t.duration for t in app.timers.active) == [300, 720]


def test_rooms_are_said_in_english():
    from voxa.house import _spoken, english_room, place_name, same_room
    from voxa.i18n import set_language

    assert english_room("Sala") == "living room" and english_room("Recámara de Ana") == "Ana's bedroom"
    assert english_room("Game room") == "Game room"  # los que ya están en inglés, como están
    assert same_room("the living room", "Sala") and same_room("Ana's room", "cuarto de Ana")
    assert not same_room("kitchen", "Sala")
    set_language("en")
    assert place_name("Cuarto de Ana") == "Ana's room" and place_name("Cuarto de la tele") == "the TV room"
    assert _spoken("Dinner is ready.", "Cocina") == "Message from the kitchen: Dinner is ready."
