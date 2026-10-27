import hashlib
import zipfile

import pytest

from voxa import prepare
from voxa.config import Config, VoiceConfig, WakeConfig


def file_url(path):
    return path.resolve().as_uri()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_downloads_are_checked_before_use(tmp_path):
    source = tmp_path / "voz.onnx"
    source.write_bytes(b"modelo")
    target = tmp_path / "modelos" / "voz.onnx"
    seen = []
    prepare.fetch(file_url(source), target, sha(b"modelo"), seen.append, "la voz")
    assert target.read_bytes() == b"modelo"
    with pytest.raises(prepare.PrepareError):
        prepare.fetch(file_url(source), tmp_path / "otro.onnx", sha(b"distinto"), seen.append, "la voz")
    assert not (tmp_path / "otro.onnx").exists() and not (tmp_path / "otro.onnx.parcial").exists()


def config_in(tmp_path):
    return Config(
        voice=VoiceConfig(vosk_model=str(tmp_path / "models/vosk-es"), piper_voice=str(tmp_path / "models/piper/voz.onnx")),
        wake=WakeConfig(feature_dir=str(tmp_path / "models/wakeword")),
    )


def test_missing_lists_what_voxa_needs(tmp_path):
    config = config_in(tmp_path)
    assert prepare.missing(config)[0] == "el reconocimiento de voz"
    assert len(prepare.missing(config)) == 6


def test_models_are_downloaded_and_unzipped(tmp_path, monkeypatch):
    config = config_in(tmp_path)
    archive = tmp_path / "vosk.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("vosk-es/am/final.mdl", "modelo")
    monkeypatch.setattr(prepare, "VOSK_URL", file_url(archive))
    monkeypatch.setattr(prepare, "VOSK_SHA256", sha(archive.read_bytes()))
    files = {}
    for item in prepare.model_downloads(config):
        src = tmp_path / f"src-{item.target.name}"
        src.write_bytes(item.name.encode())
        files[item.target] = (file_url(src), sha(item.name.encode()))
    monkeypatch.setattr(prepare, "model_downloads", lambda c: [
        prepare.Download(t.name, url, digest, t) for t, (url, digest) in files.items()])
    prepare.prepare_models(config, lambda text: None, whisper=False)
    assert (tmp_path / "models/vosk-es/am/final.mdl").exists()
    assert prepare.missing(config) == []


def test_the_lessac_voice_carries_its_own_license(tmp_path, monkeypatch):
    """La voz en inglés no tiene licencia abierta: junto al modelo queda el aviso de sus términos."""
    english = Config(voice=VoiceConfig(language="en", vosk_model=str(tmp_path / "vosk"),
                                       piper_voice=str(tmp_path / "piper/en_US-lessac-medium.onnx")))
    voice = prepare.model_downloads(english)[0]
    assert "Blizzard Challenge 2013" in voice.notice and "AGPL" in voice.notice
    assert all(not d.notice for d in prepare.model_downloads(Config()))  # la voz en español es Apache 2.0
    (tmp_path / "vosk").mkdir()
    voice.target.parent.mkdir(parents=True)
    voice.target.write_bytes(b"voz")  # ya bajada: igual se deja el aviso
    monkeypatch.setattr(prepare, "model_downloads", lambda c: [voice])
    prepare.prepare_models(english, lambda text: None, whisper=False)
    assert "sin uso comercial" in (tmp_path / "piper/en_US-lessac-medium.onnx.LICENCIA.txt").read_text(encoding="utf-8")


def test_zip_with_paths_outside_is_refused(tmp_path, monkeypatch):
    config = config_in(tmp_path)
    archive = tmp_path / "malo.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../../fuera.txt", "no")
    monkeypatch.setattr(prepare, "VOSK_URL", file_url(archive))
    monkeypatch.setattr(prepare, "VOSK_SHA256", sha(archive.read_bytes()))
    with pytest.raises(prepare.PrepareError):
        prepare.prepare_models(config, lambda text: None, whisper=False)
    assert not (tmp_path / "fuera.txt").exists()


def test_spotifast_asset_for_each_pc():
    release = {"assets": [
        {"name": "spotifast-0.14.2-x86_64.AppImage", "browser_download_url": "https://x/a", "digest": "sha256:aa"},
        {"name": "spotifast-0.14.2-aarch64.AppImage", "browser_download_url": "https://x/b", "digest": "sha256:bb"},
        {"name": "spotifast-0.14.2-x86_64.AppImage.zsync", "browser_download_url": "https://x/c", "digest": "sha256:cc"},
    ]}
    assert prepare.spotifast_asset(release, "x86_64") == ("spotifast-0.14.2-x86_64.AppImage", "https://x/a", "aa")
    assert prepare.spotifast_asset(release, "aarch64")[2] == "bb"
    assert prepare.spotifast_asset(release, "riscv64") is None
    assert prepare.spotifast_asset({"assets": [{"name": "spotifast-1-x86_64.AppImage", "browser_download_url": "u"}]},
                                   "x86_64") is None  # sin huella, no
