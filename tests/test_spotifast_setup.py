import json

from voxa.services.spotifast_setup import configure, settings_file


def test_spotifast_gets_the_same_client_id_and_the_room_name(tmp_path):
    path = tmp_path / "spotifast" / "settings.json"
    assert configure("abc123", "VOXA Cocina", path)
    assert json.loads(path.read_text()) == {"web_client_id": "abc123", "device_name": "VOXA Cocina"}
    assert not configure("abc123", "VOXA Cocina", path)  # nada que cambiar

    data = json.loads(path.read_text())
    data["bitrate"] = 160  # lo que la familia eligió en Spotifast se respeta
    path.write_text(json.dumps(data))
    assert configure("abc123", "VOXA Sala", path)
    assert json.loads(path.read_text())["bitrate"] == 160


def test_broken_spotifast_settings_are_left_alone(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{roto")
    assert not configure("abc", "VOXA Cocina", path)
    assert path.read_text() == "{roto"


def test_settings_file_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert settings_file() == tmp_path / "spotifast" / "settings.json"
