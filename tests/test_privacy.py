"""Privacidad visible: qué se queda en la PC y qué sale a internet, según lo que la casa tiene encendido."""

from voxa.app import build_app
from voxa.config import AiConfig, Config, MusicConfig, SpotifyConfig, WeatherConfig
from voxa.i18n import set_language
from voxa.privacy import privacy_report
from voxa.service import Service


def test_only_what_is_turned_on_goes_out():
    plain = privacy_report(Config(music=MusicConfig(provider="youtube")))
    assert any("el audio se reconoce en esta PC" in t for t in plain["local"])
    assert not any(t.startswith(("IA", "Spotify", "El clima")) for t in plain["internet"])
    assert any(t.startswith("YouTube") for t in plain["internet"])
    full = privacy_report(Config(ai=AiConfig(enabled=True, provider="claude"), spotify=SpotifyConfig(client_id="x"),
                                 weather=WeatherConfig(latitude=19.4, longitude=-99.1)))
    ai = next(t for t in full["internet"] if t.startswith("IA"))
    assert "Anthropic (Claude)" in ai and "nunca el audio" in ai
    assert any(t.startswith("Spotify") for t in full["internet"]) and any("Open-Meteo" in t for t in full["internet"])


def test_in_english():
    set_language("en")
    report = privacy_report(Config(ai=AiConfig(enabled=True, provider="openai")))
    assert report["local"][0].startswith("What you say")
    assert any("goes to OpenAI" in t for t in report["internet"])


def test_the_screen_marks_the_ai_only_when_it_is_on():
    app = build_app(Config(), simulated=True)
    assert Service.create(app).display.snapshot()["ai"] is False
