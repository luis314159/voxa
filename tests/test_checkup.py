import hashlib

from voxa.checkup import FAIL, OK, SKIP, WARN, Tools, check_wake, render, run_checkup
from voxa.config import Config, WakeConfig
from voxa.health import Problem
from voxa.services.process import CommandResult


def fake_tools(*, outputs=None, missing=(), modules=True, online=True):
    outputs = outputs or {}

    async def run(args, timeout=5.0):
        return CommandResult(0, outputs.get(" ".join(args), ""))

    async def internet():
        return None if online else Problem("internet", "Sin internet", "sin red")

    return Tools(
        which=lambda name: None if name in missing else f"/usr/bin/{name}",
        run=run,
        has_module=lambda name: modules,
        linux=True,
        internet=internet,
    )


def by_name(findings):
    return {f.name: f for f in findings}


async def test_missing_config_and_typos_are_reported(tmp_path):
    findings = by_name(await run_checkup(tmp_path / "no-existe.toml", fake_tools(modules=False)))
    assert findings["config.toml"].status == WARN
    assert findings["Paquetes de audio"].status == FAIL

    path = tmp_path / "config.toml"
    path.write_text('[voice]\nwhisper_modle = "small"\n[spotfy]\nclient_id = "x"\n', encoding="utf-8")
    findings = await run_checkup(path, fake_tools())
    typos = [f.detail for f in findings if f.name == "Errata"]
    assert any("[voice] whisper_modle" in d for d in typos) and any("[spotfy]" in d for d in typos)


async def test_a_healthy_kitchen(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # el token de Spotify va en tmp_path/voxa
    vosk = tmp_path / "vosk"
    vosk.mkdir()
    piper = tmp_path / "voz.onnx"
    piper.write_bytes(b"x")
    (tmp_path / "voz.onnx.json").write_text("{}")
    (tmp_path / "voxa").mkdir()
    (tmp_path / "voxa" / "spotify_token.json").write_text("{}")
    path = tmp_path / "config.toml"
    path.write_text(
        f'[voice]\nvosk_model = "{vosk.as_posix()}"\npiper_voice = "{piper.as_posix()}"\nstt = "vosk"\n'
        '[spotify]\nclient_id = "abc"\n[weather]\n[wake]\nenabled = false\n',
        encoding="utf-8",
    )
    tools = fake_tools(outputs={
        "wpctl inspect @DEFAULT_AUDIO_SINK@": 'device.api = "bluez5"\napi.bluez5.profile = "a2dp-sink"',
        "playerctl --list-all": "spotifast\nfirefox.instance123",
        "systemctl --user is-active voxa.service": "active",
        "systemctl --user is-active voxa-ui.service": "active",
        "systemctl --user is-enabled voxa-ytdlp.timer": "enabled",
    })
    findings = by_name(await run_checkup(path, tools))
    for name in ("Modelo de Vosk", "Voz de Piper", "Bocina Bluetooth", "Spotify", "Spotifast",
                 "yt-dlp", "voxa.service", "voxa-ui.service", "voxa-ytdlp.timer", "Internet"):
        assert findings[name].status == OK, findings[name]
    assert findings["Activación por voz"].status == SKIP
    assert findings["Clima"].status == WARN


async def test_problems_come_with_a_fix(tmp_path):
    tools = fake_tools(missing=("mpv", "deno"), online=False, outputs={
        "wpctl inspect @DEFAULT_AUDIO_SINK@": 'device.api = "alsa"',
        "playerctl --list-all": "firefox",
        "systemctl --user is-active voxa.service": "failed",
    })
    (tmp_path / "config.toml").write_text('[spotify]\nclient_id = "abc123"\n', encoding="utf-8")
    findings = by_name(await run_checkup(tmp_path / "config.toml", tools))
    assert findings["mpv"].fix == "sudo apt install mpv"
    assert findings["Spotifast"].status == FAIL and "firefox" in findings["Spotifast"].detail
    assert findings["Bocina Bluetooth"].status == WARN
    assert findings["voxa.service"].status == FAIL and "journalctl" in findings["voxa.service"].fix
    assert findings["Internet"].status == FAIL
    text = render(list(findings.values()), color=False)
    assert "✖ mpv — No está instalado\n      → sudo apt install mpv" in text
    assert text.endswith("avisos.")


def test_wake_models_are_checked_by_fingerprint(tmp_path):
    from voxa.audio.wakeword import FEATURE_MODEL_SHA256

    (tmp_path / "melspectrogram.onnx").write_bytes(b"alterado")
    config = Config(wake=WakeConfig(feature_dir=str(tmp_path)))
    findings = by_name(check_wake(config, fake_tools()))
    assert findings["melspectrogram.onnx"].status == FAIL and "huella" in findings["melspectrogram.onnx"].detail
    assert findings["embedding_model.onnx"].status == FAIL
    assert hashlib.sha256(b"alterado").hexdigest() not in FEATURE_MODEL_SHA256.values()


async def test_without_spotify_music_comes_from_youtube(tmp_path):
    findings = by_name(await run_checkup(tmp_path / "config.toml", fake_tools()))
    assert findings["Música"].status == OK and "YouTube" in findings["Música"].detail
    assert findings["Spotify"].status == SKIP
