import json

import pytest

from voxa.app import build_app
from voxa.config import Config
from voxa.nlu import load_matcher
from voxa.service import Service
from voxa.services.http import HttpResponse
from voxa.services.music_backend import LayeredMusicBackend, NothingFound
from voxa.services.simulated import SimulatedMusic
from voxa.skills.music import MusicSkill
from voxa.web import WebServer

from test_spotify import DEVICES, Clock, api_with, search_returning, token_path  # noqa: F401
from test_web import KEY, as_json, http, logged_in


def page(names, start, more):
    items = [{"name": n, "uri": f"spotify:playlist:{n.lower()}", "owner": {"display_name": "Luis"},
              "tracks": {"total": 10}} for n in names]
    return HttpResponse(200, {"items": items, "next": "más" if more else None, "offset": start})


def own_playlists(params, *_):
    # 60 playlists en dos páginas: la que importa está en la segunda.
    if params.get("offset", 0) == 0:
        return page([f"Lista {n}" for n in range(50)], 0, more=True)
    return page([f"Lista {n}" for n in range(50, 59)] + ["Cocina"], 50, more=False)


async def test_all_pages_of_own_playlists(token_path):  # noqa: F811
    api, http_ = api_with({("GET", "/me/playlists"): own_playlists}, token_path)
    found = await api.playlists()
    assert len(found) == 60 and found[-1].name == "Cocina" and found[-1].owner == "Luis"
    await api.playlists()
    assert len(http_.calls("GET", "/me/playlists")) == 2  # la segunda vez, de memoria


async def test_own_playlist_wins_when_the_name_matches(token_path):  # noqa: F811
    api, http_ = api_with({
        ("GET", "/me/playlists"): own_playlists,
        ("GET", "/search"): search_returning(tracks=[{"name": "Cocina", "uri": "spotify:track:x", "artists": []}]),
        ("GET", "/me/player/devices"): HttpResponse(200, DEVICES),
        ("PUT", "/me/player/play"): HttpResponse(204),
    }, token_path)
    result = await api.play("cocina")
    assert result.describe() == "La playlist Cocina"
    assert http_.calls("PUT", "/me/player/play")[0]["json"] == {"context_uri": "spotify:playlist:cocina"}
    assert not http_.calls("GET", "/search")
    await api.play("soda stereo")  # sin playlist propia parecida: búsqueda normal
    assert http_.calls("GET", "/search")


async def test_play_uri_only_accepts_spotify_contexts(token_path):  # noqa: F811
    api, http_ = api_with({
        ("GET", "/me/player/devices"): HttpResponse(200, DEVICES),
        ("PUT", "/me/player/play"): HttpResponse(204),
    }, token_path)
    assert (await api.play_uri("spotify:playlist:abc", "Domingo")).describe() == "La playlist Domingo"
    with pytest.raises(NothingFound):
        await api.play_uri("https://evil.example", "x")


async def test_layers_without_playlists_are_skipped():
    class Plain:
        name = "mpris"

    music = SimulatedMusic()
    layered = LayeredMusicBackend([Plain(), music], [music])
    assert [p.name for p in await layered.playlists()] == ["Cocina", "Domingo en casa"]


async def test_what_playlists_do_i_have():
    skill = MusicSkill(SimulatedMusic())
    said = (await skill.handle(load_matcher().match("¿qué playlists tengo?"))).speech
    assert said.startswith("Tienes 2 playlists: Cocina y Domingo en casa.")


@pytest.fixture
async def phone(tmp_path):
    service = Service.create(build_app(Config(), simulated=True))
    server = WebServer(service, KEY, tmp_path / "fondos", host="127.0.0.1", port=0)
    await server.start()
    yield server, service
    await server.close()


async def test_phone_lists_searches_and_plays_playlists(phone):
    server, service = phone
    status, _, body = await http(server.port, "GET", "/api/playlists", headers=logged_in())
    assert status == 200 and [p["nombre"] for p in json.loads(body)["playlists"]] == ["Cocina", "Domingo en casa"]
    status, _, body = await http(server.port, "POST", "/api/playlists/buscar", **as_json({"texto": "salsa"}))
    assert json.loads(body)["playlists"][0]["nombre"] == "Salsa 1"
    status, _, body = await http(server.port, "POST", "/api/playlists/poner",
                                 **as_json({"uri": "spotify:playlist:cocina", "nombre": "Cocina"}))
    assert status == 200 and json.loads(body)["respuesta"] == "Sonando: Cocina."
    assert service.app.music.calls[-1] == "uri:spotify:playlist:cocina"
    status, _, _ = await http(server.port, "GET", "/api/playlists")
    assert status == 403  # sin la clave, nada


def liked_page(params, *_):
    start = params.get("offset", 0)
    items = [{"track": {"uri": f"spotify:track:{n}"}} for n in range(start, start + 50)]
    return HttpResponse(200, {"items": items, "next": "más" if start == 0 else None})


def with_scope(path, scope):
    data = json.loads(path.read_text())
    data["scope"] = scope
    path.write_text(json.dumps(data))


async def test_my_liked_songs_play_shuffled(token_path):  # noqa: F811
    with_scope(token_path, "playlist-read-private user-library-read user-library-modify")
    api, http_ = api_with({
        ("GET", "/me/tracks"): liked_page,
        ("GET", "/me/player/devices"): HttpResponse(200, DEVICES),
        ("PUT", "/me/player/shuffle"): HttpResponse(204),
        ("PUT", "/me/player/play"): HttpResponse(204),
    }, token_path)
    result = await api.play_liked()
    assert result.describe() == "Tus Me gusta, en aleatorio"
    body = http_.calls("PUT", "/me/player/play")[0]["json"]
    assert len(body["uris"]) == 100 and body["uris"] != sorted(body["uris"], key=lambda u: int(u.split(":")[-1]))


async def test_old_authorizations_ask_to_reconnect(token_path):  # noqa: F811
    from voxa.services.music_backend import NeedsPermission

    with_scope(token_path, "playlist-read-private")
    api, http_ = api_with({}, token_path)
    with pytest.raises(NeedsPermission):
        await api.play_liked()
    skill = MusicSkill(LayeredMusicBackend([api], [api]))
    said = (await skill.handle(load_matcher().match("pon mis me gusta"))).speech
    assert "vuelve a conectar Spotify" in said


async def test_like_saves_with_the_web_api_when_allowed(token_path):  # noqa: F811
    with_scope(token_path, "user-library-read user-library-modify")
    api, http_ = api_with({
        ("GET", "/me/player/currently-playing"): HttpResponse(200, {"item": {"id": "abc", "type": "track", "name": "x"}}),
        ("PUT", "/me/tracks"): HttpResponse(200),
    }, token_path)
    await api.like()
    assert http_.calls("PUT", "/me/tracks")[0]["params"] == {"ids": "abc"}


async def test_phone_plays_my_liked_songs(phone):
    server, service = phone
    status, _, body = await http(server.port, "POST", "/api/playlists/poner", **as_json({"uri": "me-gusta"}))
    assert status == 200 and service.app.music.calls[-1] == "liked"
