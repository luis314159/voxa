import json
import urllib.parse
from dataclasses import replace

import pytest

from voxa.app import build_app
from voxa.checkup import Finding
from voxa.config import Config, read_config
from voxa.service import Service
from voxa.services.http import HttpResponse
from voxa.settings import settings_path
from voxa.telegram import Chats
from voxa.web import WebServer
from voxa.web_settings import RESTART_BY_HAND, RESTARTING, SettingsApi

from test_calendar import ICS
from test_web import KEY, as_json, http, logged_in


class FakeInternet:
    def __init__(self):
        self.requests = []

    async def request(self, method, url, *, params=None, headers=None, json_body=None, form=None, timeout=8.0):
        self.requests.append((method, url, params, form))
        if "geocoding" in url:
            return HttpResponse(200, {"results": [
                {"name": "Monterrey", "admin1": "Nuevo León", "country": "México", "latitude": 25.67, "longitude": -100.31},
            ]})
        if "api.telegram.org/bot123:bueno/" in url:
            return HttpResponse(200, {"ok": True, "result": {"username": "cocina_bot"}})
        if "api.telegram.org" in url:
            return HttpResponse(401, {"ok": False, "description": "Unauthorized"})
        if url.endswith(".ics"):
            return HttpResponse(200, ICS)
        if "accounts.spotify.com/api/token" in url:
            return HttpResponse(200, {"access_token": "a", "refresh_token": "r", "expires_in": 3600})
        return HttpResponse(404, "no")


@pytest.fixture
def kitchen(tmp_path):
    config_file = tmp_path / "config.toml"
    config = Config(config_dir=tmp_path, state_dir=tmp_path / "estado")
    service = Service.create(build_app(config, simulated=True))
    restarts = []

    async def restart():
        restarts.append(1)
        return True

    async def checkup(path):
        return [Finding("Música", "Spotify", "falla", "falta el Client ID", "Ajustes → Spotify")]

    api = SettingsApi(service, config_file, http=FakeInternet(), restart=restart, checkup=checkup)
    return api, service, config_file, restarts


def reloaded(config_file, tmp_path):
    """Lo que VOXA leería al reiniciarse (con las carpetas de la prueba)."""
    return replace(read_config(config_file)[0], config_dir=tmp_path, state_dir=tmp_path / "estado")


async def test_summary_has_no_secrets(kitchen, tmp_path):
    api, service, *_ = kitchen
    (tmp_path / "ia_clave").write_text("sk-secreta\n")
    summary = api.summary()
    assert summary["ia"]["llave"] is True
    assert "sk-secreta" not in json.dumps(summary)
    assert summary["voz"]["lista"] is False  # modo simulado: sin micrófono


async def test_choose_the_city_by_name(kitchen):
    api, _, config_file, restarts = kitchen
    status, found = await api.post("/api/clima/buscar", {"texto": "Monterrey"})
    assert status == 200 and found["lugares"][0]["nombre"] == "Monterrey, Nuevo León, México"
    place = found["lugares"][0]
    status, saved = await api.post("/api/ajustes", {"seccion": "weather", "valores": {
        "latitude": place["lat"], "longitude": place["lon"], "place": place["nombre"]}})
    assert status == 200 and saved["respuesta"] == RESTARTING and restarts
    assert read_config(config_file)[0].weather.place == "Monterrey, Nuevo León, México"


async def test_bad_settings_are_refused(kitchen):
    api, *_ = kitchen
    assert (await api.post("/api/ajustes", {"seccion": "voice", "valores": {"vosk_model": "/x"}}))[0] == 400
    assert (await api.post("/api/ajustes", {"seccion": "ai", "valores": "no"}))[0] == 400


async def test_secrets_are_saved_privately_and_turn_the_feature_on(kitchen, tmp_path):
    api, _, config_file, _ = kitchen
    assert (await api.post("/api/secreto", {"tipo": "ia", "valor": " sk-123 "}))[0] == 200
    assert (tmp_path / "ia_clave").read_text().strip() == "sk-123"

    status, error = await api.post("/api/secreto", {"tipo": "telegram", "valor": "123:malo"})
    assert status == 400 and "no aceptó" in error["error"]
    status, ok = await api.post("/api/secreto", {"tipo": "telegram", "valor": "123:bueno"})
    assert status == 200 and ok["bot"] == "cocina_bot"

    assert (await api.post("/api/secreto", {"tipo": "calendario", "valor": "calendario"}))[0] == 400
    status, ok = await api.post("/api/secreto", {"tipo": "calendario",
                                                 "valor": "https://calendar.google.com/calendar/ical/x/basic.ics"})
    assert status == 200 and ok["eventos"] == 7

    config = read_config(config_file)[0]
    assert config.ai.enabled and config.telegram.enabled and config.calendar.enabled


async def test_telegram_pairing_code_from_the_phone(kitchen, tmp_path):
    api, service, config_file, _ = kitchen
    await api.post("/api/secreto", {"tipo": "telegram", "valor": "123:bueno"})
    service.app.config = reloaded(config_file, tmp_path)  # como tras el reinicio
    status, code = await api.post("/api/telegram/codigo", {})
    assert status == 200 and len(code["codigo"]) == 6 and code["bot"] == "cocina_bot"
    chats = Chats(tmp_path / "telegram_chats.json", tmp_path / "estado" / "telegram_codigo.json")
    assert chats.try_pair(55, "Ana", code["codigo"])
    assert (await api.post("/api/telegram/quitar", {"id": 55}))[0] == 200
    assert chats.all() == {}


async def test_spotify_from_the_phone(kitchen, tmp_path):
    api, service, config_file, restarts = kitchen
    assert (await api.post("/api/spotify/autorizar", {}))[0] == 400  # falta el Client ID
    await api.post("/api/ajustes", {"seccion": "spotify", "valores": {"client_id": "abc123def456"}})
    config = reloaded(config_file, tmp_path)
    service.app.config = replace(config, spotify=replace(config.spotify, redirect_uri="http://127.0.0.1:0/callback"))
    status, start = await api.post("/api/spotify/autorizar", {})
    assert status == 200 and start["url"].startswith("https://accounts.spotify.com/authorize?")
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(start["url"]).query)["state"][0]

    bad = await api.post("/api/spotify/codigo", {"direccion": "http://127.0.0.1:0/callback?code=x&state=otro"})
    assert bad[0] == 400
    status, done = await api.post("/api/spotify/codigo",
                                  {"direccion": f"http://127.0.0.1:0/callback?code=x&state={state}"})
    assert status == 200
    assert json.loads((tmp_path / "spotify_token.json").read_text())["refresh_token"] == "r"
    assert (await api.post("/api/spotify/codigo", {"direccion": f"http://x/callback?code=x&state={state}"}))[0] == 400


async def test_review_and_enroll(kitchen):
    api, service, *_ = kitchen
    status, review = await api.post("/api/ajustes/revisar", {})
    assert review["hallazgos"][0]["arreglo"] == "Ajustes → Spotify"
    status, error = await api.post("/api/voz/aprender", {"nombre": "Ana"})
    assert status == 400 and "micrófono" in error["error"]


async def test_without_systemd_it_asks_to_restart_by_hand(kitchen):
    api, *_ = kitchen

    async def no_restart():
        return False

    api._restart = no_restart
    status, saved = await api.post("/api/ajustes", {"seccion": "video", "valores": {"enabled": False}})
    assert saved["respuesta"] == RESTART_BY_HAND


async def test_settings_need_the_key_over_http(kitchen, tmp_path):
    api, service, *_ = kitchen
    server = WebServer(service, KEY, tmp_path / "fondos", host="127.0.0.1", port=0, settings=api)
    await server.start()
    try:
        status, _, _ = await http(server.port, "GET", "/api/ajustes")
        assert status == 403
        status, _, body = await http(server.port, "GET", "/api/ajustes", headers=logged_in())
        assert status == 200 and json.loads(body)["version"]
        status, _, body = await http(server.port, "POST", "/api/clima/buscar", **as_json({"texto": "Monterrey"}))
        assert status == 200 and json.loads(body)["lugares"]
    finally:
        await server.close()


async def test_each_person_connects_their_spotify(kitchen, tmp_path):
    """Spotify por persona: la cuenta de Ana se guarda aparte, con menos permisos, y sin reiniciar VOXA."""
    api, service, config_file, restarts = kitchen
    await api.post("/api/ajustes", {"seccion": "spotify", "valores": {"client_id": "abc123def456"}})
    config = reloaded(config_file, tmp_path)
    service.app.config = replace(config, spotify=replace(config.spotify, redirect_uri="http://127.0.0.1:0/callback"))
    status, error = await api.post("/api/spotify/autorizar", {"persona": "Ana"})
    assert status == 400 and "la cuenta de la casa" in error["error"]
    (tmp_path / "spotify_token.json").write_text('{"access_token": "A", "refresh_token": "R", "expires_at": 1}')
    status, start = await api.post("/api/spotify/autorizar", {"persona": "Ana"})
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(start["url"]).query)
    assert query["scope"] == ["playlist-read-private user-library-read user-library-modify"]
    before = len(restarts)
    status, done = await api.post("/api/spotify/codigo",
                                  {"direccion": f"http://127.0.0.1:0/callback?code=x&state={query['state'][0]}"})
    assert status == 200 and done["respuesta"] == "Listo: ya está la cuenta de Ana." and len(restarts) == before
    assert service.app.config.spotify_people() == ["Ana"]
    assert (await api.post("/api/spotify/quitar", {"persona": "Ana"}))[0] == 200
    assert service.app.config.spotify_people() == []
