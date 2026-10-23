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
