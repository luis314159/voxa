import pytest

from voxa.config import load_config
from voxa.core.types import Intent
from voxa.services.http import HttpResponse
from voxa.services.pipewire import VolumeUnavailable, WpctlVolume
from voxa.services.process import CommandResult
from voxa.services.weather import OpenMeteo
from voxa.skills.weather import WeatherSkill


class FakeRunner:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.calls = []

    async def __call__(self, args, timeout=5.0):
        self.calls.append(list(args))
        return CommandResult(0, self.stdout)


async def test_wpctl_volume_parsing_and_commands():
    run = FakeRunner("Volume: 0.40 [MUTED]\n")
    volume = WpctlVolume(run=run)
    state = await volume.get()
    assert (state.percent, state.muted) == (40, True)
    await volume.set(130)
    assert run.calls[-1] == ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "1.00"]
    await volume.mute(False)
    assert run.calls[-1] == ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"]


async def test_wpctl_unexpected_output():
    with pytest.raises(VolumeUnavailable):
        await WpctlVolume(run=FakeRunner("???")).get()


class WeatherHttp:
    def __init__(self, rain):
        self.rain = rain

    async def request(self, method, url, **kwargs):
        return HttpResponse(
            200,
            {
                "current": {"temperature_2m": 21.6, "weather_code": 3},
                "daily": {
                    "temperature_2m_max": [26.2],
                    "temperature_2m_min": [12.8],
                    "precipitation_probability_max": [self.rain],
                },
            },
        )


async def test_weather_phrases():
    skill = WeatherSkill(OpenMeteo(WeatherHttp(70), 19.4, -99.1))
    said = await skill.handle(Intent("weather.current"))
    assert said.speech == (
        "Ahora hay 22 grados y está nublado. Hoy, máxima de 26 y mínima de 13. Probabilidad de lluvia: 70 %."
    )
    said = await skill.handle(Intent("weather.rain"))
    assert said.speech.startswith("Sí, probablemente")
    said = await WeatherSkill(OpenMeteo(WeatherHttp(10), 0, 0)).handle(Intent("weather.rain"))
    assert said.speech.startswith("No parece")


async def test_weather_without_location():
    said = await WeatherSkill(None).handle(Intent("weather.current"))
    assert said.sound == "error"


def test_config_overrides_and_defaults(tmp_path, caplog):
    path = tmp_path / "config.toml"
    path.write_text(
        '[spotify]\nclient_id = "abc"\n[spotifast]\ncommand = ["flatpak", "run", "x"]\n'
        "[weather]\nlatitude = 19.4\nlongitude = -99.1\n[volume]\npaso = 5\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.spotify.client_id == "abc"
    assert config.spotify.device_name == "VOXA Cocina"
    assert config.spotifast.command == ("flatpak", "run", "x")
    assert config.weather.latitude == 19.4
    assert "paso" in caplog.text


def test_shipped_default_config_loads():
    from pathlib import Path

    config = load_config(Path(__file__).parents[1] / "config" / "default.toml")
    assert config.spotify.redirect_uri == "http://127.0.0.1:8765/callback"
