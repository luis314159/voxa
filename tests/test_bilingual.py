"""Casa bilingüe (bilingual = true en [voice]): entiende los dos idiomas y contesta en el de cada frase."""

import numpy as np

from voxa.app import build_app
from voxa.audio.stt import HybridStt, WhisperStt
from voxa.audio.tts import BilingualTts
from voxa.config import Config, VoiceConfig
from voxa.i18n import guess_language, in_language, language
from voxa.prepare import model_downloads


def bilingual_app(home="es"):
    return build_app(Config(voice=VoiceConfig(language=home, bilingual=True)), simulated=True)


async def test_each_phrase_is_answered_in_its_language():
    app = bilingual_app()
    said = await app.assistant.handle_text("pon un temporizador de diez minutos para el arroz")
    assert said.speech == "10 minutos para el arroz." and said.language == "es"
    said = await app.assistant.handle_text("set a timer for five minutes for the eggs")
    assert said.speech == "5 minutes for eggs." and said.language == "en"
    said = await app.assistant.handle_text("how much time is left on the eggs timer")
    assert said.speech == "5 minutes left for eggs." and said.language == "en"
    assert language() == "es"  # el idioma de la casa no cambia


async def test_the_language_heard_is_tried_first():
    app = bilingual_app("en")
    said = await app.assistant.handle_text("agrega leche a la lista", "es")
    assert said.speech == "Agregué leche a la lista." and said.language == "es"
    said = await app.assistant.handle_text("thanks", "en")
    assert said.speech == "You're welcome!"


async def test_not_understood_in_the_language_it_was_written():
    app = bilingual_app()
    assert (await app.assistant.handle_text("what the heck is going on here")).speech.startswith("Sorry")
    assert (await app.assistant.handle_text("qué onda con todo esto")).speech.startswith("No te entendí")


async def test_screen_buttons_work_in_an_english_home():
    """Los botones mandan «pausa» o «siguiente paso» en español; la casa en inglés igual los entiende."""
    app = build_app(Config(voice=VoiceConfig(language="en")), simulated=True)
    await app.assistant.handle_text("play soda stereo")
    assert (await app.assistant.handle_text("pausa", button=True)).sound == "ok"
    said = await app.assistant.handle_text("siguiente paso", button=True)
    assert said.speech.startswith("No recipe is open.")  # contesta en el idioma de la casa
    assert (await app.assistant.handle_text("pausa")).speech.startswith("Sorry")  # sin botón, solo inglés


def test_typed_text_language_guess():
    assert guess_language("how do I keep the rice from sticking") == "en"
    assert guess_language("¿con qué sustituyo el huevo en un pastel?") == "es"
    assert guess_language("pozole") == "es"  # sin pistas: el de la casa


class FakeWhisper:
    def __init__(self, scores):
        self.scores = scores
        self.languages = []

    def detect_language(self, audio):
        best = max(self.scores, key=lambda pair: pair[1])
        return best[0], best[1], self.scores

    def transcribe(self, audio, language, **options):
        self.languages.append(language)
        return [type("Segment", (), {"text": " hello there "})()], None


def test_whisper_picks_one_of_the_home_languages():
    model = FakeWhisper([("pt", 0.5), ("es", 0.3), ("en", 0.2)])  # el portugués no es de la casa
    stt = WhisperStt(language="en", also=("es",), model_obj=model)
    assert stt.transcribe(np.zeros(1600, np.int16)) == "hello there"
    assert stt.last_language == "es" and model.languages == ["es"]
    single = WhisperStt(language="es", model_obj=FakeWhisper([("en", 0.9)]))
    single.transcribe(np.zeros(1600, np.int16))
    assert single.last_language == "es"  # una sola lengua: ni se detecta


class Fixed:
    name = "vosk"

    def __init__(self, text):
        self.text = text

    def transcribe(self, samples):
        return self.text


def test_hybrid_lets_whisper_decide_the_other_language():
    whisper = WhisperStt(language="es", also=("en",), model_obj=FakeWhisper([("en", 0.8), ("es", 0.2)]))
    stt = HybridStt(Fixed("pon la"), whisper, lambda text: True, lambda text: False)
    assert stt.transcribe(np.zeros(1600, np.int16)) == "hello there"
    assert stt.last_language == "en"


class Voice:
    def __init__(self, name):
        self.name = name

    def synthesize(self, text):
        return f"{self.name}: {text}"


def test_each_answer_with_the_voice_of_its_language():
    tts = BilingualTts({"es": Voice("claude"), "en": Voice("lessac")}, "es")
    assert tts.synthesize("Hola") == "claude: Hola"
    with in_language("en"):
        assert tts.synthesize("Hi") == "lessac: Hi"


def test_a_bilingual_home_downloads_both_voices():
    names = [d.target.name for d in model_downloads(Config(voice=VoiceConfig(language="es", bilingual=True)))]
    assert "es_MX-claude-high.onnx" in names and "en_US-lessac-medium.onnx" in names
    assert "en_US-lessac-medium.onnx" not in [d.target.name for d in model_downloads(Config())]


async def test_a_timer_set_in_one_language_is_found_in_the_other():
    app = bilingual_app()
    await app.assistant.handle_text("pon un temporizador de diez minutos para el arroz")
    await app.assistant.handle_text("pon un temporizador de tres minutos para los huevos")
    said = await app.assistant.handle_text("how much time is left on the rice timer")
    assert said.speech == "10 minutes left for arroz."
    assert app.timers.find("chicken") == []
    assert (await app.assistant.handle_text("cancel the rice timer")).speech == "Canceled the arroz timer."


def test_slower_voice_reaches_both_languages():
    tts = BilingualTts({"es": Voice("claude"), "en": Voice("lessac")}, "es")
    tts.slower = lambda: True
    assert tts._voices["en"].slower() and tts.slower()
