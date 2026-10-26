import json
import os
import stat
import sys

import pytest

from voxa.config import read_config
from voxa.services.process import CommandResult
from voxa.settings import SettingsError, load_settings, restart_soon, save_settings, settings_path, validate


def test_app_settings_go_on_top_of_config_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[spotify]\nclient_id = "del-archivo"\ndevice_name = "Cocina"\n', encoding="utf-8")
    save_settings(settings_path(config_file), "spotify", {"client_id": "de-la-app"})
    save_settings(settings_path(config_file), "weather", {"latitude": 25.67, "longitude": -100.31, "place": "Monterrey"})
    config, warnings = read_config(config_file)
    assert config.spotify.client_id == "de-la-app"
    assert config.spotify.device_name == "Cocina"  # lo que la app no tocó se queda
    assert (config.weather.latitude, config.weather.place) == (25.67, "Monterrey")
    assert warnings == []


def test_settings_work_without_config_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    save_settings(settings_path(config_file), "ai", {"enabled": True, "provider": "openai"})
    config, _ = read_config(config_file)
    assert config.ai.enabled and config.ai.provider == "openai"


@pytest.mark.parametrize("section, values", [
    ("voice", {"vosk_model": "/tmp/x"}),  # rutas del sistema: solo en config.toml
    ("secreto", {"x": 1}),
    ("ai", {"provider": "otro"}),
    ("ai", {"enabled": "sí"}),
    ("ai", {"monthly_budget_usd": -3}),
    ("weather", {"latitude": 123.0, "longitude": 0.0}),
    ("spotify", {"client_id": "x" * 400}),
])
def test_only_known_settings_with_the_right_type(section, values):
    with pytest.raises(SettingsError):
        validate(section, values)


def test_numbers_are_converted_and_text_trimmed():
    assert validate("ai", {"daily_questions": 30.0, "model": "  gpt-5 "}) == {"daily_questions": 30, "model": "gpt-5"}


def test_settings_file_is_private_and_readable(tmp_path):
    path = tmp_path / "ajustes.json"
    save_settings(path, "telegram", {"enabled": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"telegram": {"enabled": True}}
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    path.write_text("{roto", encoding="utf-8")
    assert load_settings(path) == {}


async def test_restart_only_under_systemd(monkeypatch):
    calls = []

    async def run(args, timeout=5.0):
        calls.append(list(args))
        return CommandResult(0, "")

    monkeypatch.delenv("INVOCATION_ID", raising=False)
    assert not await restart_soon(run)
    monkeypatch.setenv("INVOCATION_ID", "abc")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    assert await restart_soon(run)
    assert calls[0][-4:] == ["systemctl", "--user", "restart", "voxa.service"]
