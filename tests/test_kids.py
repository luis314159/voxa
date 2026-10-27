"""Modo niños: música sin explícitas, volumen con tope, IA para niños y horario de videos."""

from dataclasses import replace
from datetime import datetime

import pytest

from voxa.app import build_app
from voxa.config import Config, KidsConfig
from voxa.core.people import speaking
from voxa.kids import KidsRules, skip_explicit
from voxa.services.music_backend import NowPlaying
from voxa.settings import SettingsError, validate

KIDS = KidsConfig(enabled=True, children=("Sofía",), max_volume=60, video_from="16:00", video_until="19:00")


def rules(config=KIDS, hour=12):
    return KidsRules(config, clock=lambda: datetime(2026, 10, 27, hour, 0))


def test_rules_apply_only_to_the_children():
    kids = rules()
    with speaking("sofia"):  # sin acento, como lo guarda el reconocimiento
        assert kids.applies() and kids.clean_music() and kids.volume(90) == 60
    with speaking("Luis"):
        assert not kids.applies() and kids.volume(90) == 90
    assert not kids.applies()  # nadie reconocido: solo con «para todos»
    assert rules(replace(KIDS, everyone=True)).applies()
    assert not rules(replace(KIDS, enabled=False)).applies()


def test_video_hours():
    with speaking("Sofía"):
        assert rules(hour=12).video_hours() == ("16:00", "19:00")
        assert rules(hour=17).video_hours() is None
        assert rules(replace(KIDS, video_from="20:00", video_until="08:00"), hour=6).video_hours() is None  # cruza la noche
        assert rules(replace(KIDS, video_from=""), hour=12).video_hours() is None  # sin horario
    assert rules(hour=12).video_hours() is None  # los adultos, a cualquier hora


def test_music_is_watched_only_when_a_child_asked():
    kids = rules()
    with speaking("Sofía"):
        kids.music_started()
    assert kids.watching_music()
    with speaking("Luis"):
        kids.music_started()
    assert not kids.watching_music()
    assert rules(replace(KIDS, everyone=True)).watching_music()


class Player:
    def __init__(self, explicit):
        self.current = NowPlaying("Canción", "Artista", explicit=explicit)
        self.skipped = 0

    async def now_playing(self):
        return self.current

    async def next(self):
        self.skipped += 1


async def test_explicit_songs_are_skipped():
    dirty, clean = Player(explicit=True), Player(explicit=False)
    assert await skip_explicit(dirty) and dirty.skipped == 1
    assert not await skip_explicit(clean) and clean.skipped == 0


def kids_app(**changes):
    return build_app(Config(kids=replace(KIDS, **changes)), simulated=True)


async def test_volume_limit_by_voice():
    app = kids_app(everyone=True)
    said = await app.assistant.handle_text("pon el volumen al 100")
    assert said.speech == "Volumen al 60, el máximo del modo niños."
    assert (await app.assistant.handle_text("pon el volumen al 40")).speech == "Volumen al 40."


async def test_kids_mode_on_by_voice_off_only_from_the_phone():
    app = build_app(Config(), simulated=True)
    said = await app.assistant.handle_text("ya vienen los sobrinos")
    assert said.speech.startswith("Listo, modo niños para todos")
    assert app.kids.applies()
    said = await app.assistant.handle_text("quita el modo niños")
    assert said.speech == "El modo niños se apaga desde el celular: Ajustes, Modo niños."
    assert app.kids.applies()


async def test_videos_outside_their_hours(monkeypatch):
    app = kids_app(everyone=True, video_from="00:00", video_until="00:01")
    said = await app.assistant.handle_text("pon un video de cómo hacer pan de elote")
    assert said.speech == "Los videos son de 00:00 a 00:01."


def test_kids_settings_from_the_phone():
    clean = validate("kids", {"enabled": True, "children": [" Sofía ", "Leo"], "max_volume": 50, "video_from": "16:00"})
    assert clean == {"enabled": True, "children": ["Leo", "Sofía"], "max_volume": 50, "video_from": "16:00"}
    with pytest.raises(SettingsError):
        validate("kids", {"max_volume": 150})
    with pytest.raises(SettingsError):
        validate("kids", {"children": "Sofía"})
    with pytest.raises(SettingsError):
        validate("kids", {"video_until": "tarde"})


async def test_the_ai_talks_to_kids(tmp_path, monkeypatch):
    import voxa.app
    from voxa.config import AiConfig
    from voxa.services.ai import AiAnswer

    asked = []

    class Chat:
        name, model = "Prueba", "claude-haiku-5-5"

        async def ask(self, system, messages, tools=(), *, max_tokens=2048):
            asked.append(system)
            return AiAnswer(text="Los dinosaurios eran muy grandes.")

    monkeypatch.setattr(voxa.app, "read_key", lambda config, path: "k")
    monkeypatch.setattr(voxa.app, "build_chat", lambda config, key: Chat())
    app = build_app(Config(kids=KIDS, ai=AiConfig(enabled=True), state_dir=tmp_path, config_dir=tmp_path), simulated=True)
    await app.assistant.handle_text("por qué se extinguieron los dinosaurios")
    with speaking("Sofía"):
        await app.assistant.handle_text("cuánto pesaba un tiranosaurio")
    assert len(asked) == 2, asked
    assert "te habla un niño" not in asked[0] and "te habla un niño" in asked[1]
