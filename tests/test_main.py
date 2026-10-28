import builtins

import pytest

from voxa.main import main


def test_help_exits_cleanly():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_text_mode_runs_commands(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.toml"
    config.write_text("[display]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setenv("VOXA_CONFIG", str(config))
    lines = iter(["pon un temporizador de un minuto para el té", "salir"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    assert main(["texto", "--simulado"]) == 0
    assert "Un minuto para el té." in capsys.readouterr().out


async def test_the_phone_address_and_the_qr_on_the_screen(tmp_path, capsys):
    import asyncio
    import json

    from voxa.config import Config, DisplayConfig
    from voxa.main import show_phone

    received = asyncio.Queue()

    async def screen(reader, writer):
        received.put_nowait(json.loads(await reader.readline()))
        writer.close()

    server = await asyncio.start_server(screen, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    config = Config(config_dir=tmp_path, display=DisplayConfig(port=port))
    assert await show_phone(config) == 1  # VOXA todavía no ha creado su clave
    (tmp_path / "web_clave").write_text("abc123\n", encoding="utf-8")
    assert await show_phone(config) == 0
    assert ":8770/?k=abc123" in capsys.readouterr().out
    assert await asyncio.wait_for(received.get(), 2) == {"type": "say", "text": "conecta mi celular"}
    server.close()


def test_loudness_tells_silence_from_a_voice():
    import numpy as np

    from voxa.main import loudness

    t = np.arange(1280) / 16000
    voice = (3000 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)
    assert loudness(np.zeros(1280, dtype=np.int16)) == 0.0
    assert loudness(voice) > 0.6


def test_the_settings_open_in_this_pcs_browser(tmp_path, monkeypatch):
    import webbrowser

    from voxa.config import Config
    from voxa.main import open_settings

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr("voxa.main.shutil.which", lambda name: None)
    config = Config(config_dir=tmp_path)
    assert open_settings(config) == 1 and opened == []  # VOXA todavía no arranca
    (tmp_path / "web_clave").write_text("abc123", encoding="utf-8")
    assert open_settings(config) == 0
    assert opened == ["http://127.0.0.1:8770/?k=abc123#ajustes"]
