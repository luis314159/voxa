import json
import urllib.parse

import pytest

from voxa.services.http import HttpError, HttpResponse
from voxa.services.music_backend import AuthRequired, BackendUnavailable, NothingFound
from voxa.services.spotify_api import SpotifyWebApi
from voxa.services.spotify_auth import SpotifyAuth, challenge_for

DEVICES = {"devices": [{"id": "dev-cocina", "name": "VOXA Cocina"}, {"id": "dev-sala", "name": "Sala"}]}
ARTIST = {"name": "Soda Stereo", "uri": "spotify:artist:soda"}
TRACK = {
    "name": "Persiana americana",
    "uri": "spotify:track:persiana",
    "artists": [{"name": "Soda Stereo"}],
    "album": {"uri": "spotify:album:signos"},
}


class FakeHttp:
    """Responde según (método, ruta); registra cada petición."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    async def request(self, method, url, *, params=None, headers=None, json_body=None, form=None, timeout=8.0):
        path = urllib.parse.urlparse(url).path.removeprefix("/v1")
        self.requests.append({"method": method, "path": path, "params": params, "json": json_body, "form": form})
        handler = self.routes.get((method, path))
        if handler is None:
            return HttpResponse(404, {"error": "sin ruta"})
        result = handler(params or {}, json_body, form) if callable(handler) else handler
        if isinstance(result, Exception):
            raise result
        return result

    def calls(self, method, path):
        return [r for r in self.requests if r["method"] == method and r["path"] == path]


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def token_path(tmp_path):
    path = tmp_path / "spotify_token.json"
    path.write_text(json.dumps({"access_token": "A", "refresh_token": "R", "expires_at": 99999}))
    return path


def api_with(routes, token_path, clock=None):
    http = FakeHttp(routes)
    auth = SpotifyAuth("client", "http://127.0.0.1:8765/callback", token_path, http, clock=clock or Clock())
    return SpotifyWebApi(auth, http, "VOXA Cocina"), http


def search_returning(**results):
    return lambda params, *_: HttpResponse(200, {k: {"items": v} for k, v in results.items()})


async def test_plays_artist_on_kitchen_device(token_path):
    api, http = api_with(
        {
            ("GET", "/search"): search_returning(artists=[ARTIST], tracks=[TRACK]),
            ("GET", "/me/player/devices"): HttpResponse(200, DEVICES),
            ("PUT", "/me/player/play"): HttpResponse(204),
        },
        token_path,
    )
    result = await api.play("soda stereo")
    play = http.calls("PUT", "/me/player/play")[0]
    assert play["params"] == {"device_id": "dev-cocina"}
    assert play["json"] == {"context_uri": "spotify:artist:soda"}
    assert result.describe() == "Soda Stereo"


async def test_song_by_artist_plays_inside_its_album(token_path):
    api, http = api_with(
        {
            ("GET", "/search"): search_returning(tracks=[TRACK]),
            ("GET", "/me/player/devices"): HttpResponse(200, DEVICES),
            ("PUT", "/me/player/play"): HttpResponse(204),
        },
        token_path,
    )
    result = await api.play("persiana americana de soda stereo")
    assert http.calls("GET", "/search")[0]["params"]["q"] == 'track:"persiana americana" artist:"soda stereo"'
    assert http.calls("PUT", "/me/player/play")[0]["json"] == {
        "context_uri": "spotify:album:signos",
        "offset": {"uri": "spotify:track:persiana"},
    }
    assert result.describe() == "Persiana americana, de Soda Stereo"


async def test_own_playlist_is_preferred(token_path):
    playlists = {"items": [{"name": "Cocina 🍳", "uri": "spotify:playlist:mia"}, None]}
    api, http = api_with(
        {
            ("GET", "/me/playlists"): HttpResponse(200, playlists),
            ("GET", "/me/player/devices"): HttpResponse(200, DEVICES),
            ("PUT", "/me/player/play"): HttpResponse(204),
        },
        token_path,
    )
    result = await api.play("cocina", "playlist")
    assert http.calls("PUT", "/me/player/play")[0]["json"] == {"context_uri": "spotify:playlist:mia"}
    assert not http.calls("GET", "/search")
    assert result.kind == "playlist"


async def test_nothing_found(token_path):
    api, _ = api_with({("GET", "/search"): search_returning(artists=[], tracks=[])}, token_path)
    with pytest.raises(NothingFound):
        await api.play("zzzz")


async def test_kitchen_device_missing_means_layer_unavailable(token_path):
    api, _ = api_with(
        {
            ("GET", "/search"): search_returning(artists=[ARTIST]),
            ("GET", "/me/player/devices"): HttpResponse(200, {"devices": []}),
        },
        token_path,
    )
    with pytest.raises(BackendUnavailable, match="VOXA Cocina"):
        await api.play("soda stereo", "artist")


async def test_transfer_to_other_device(token_path):
    api, http = api_with(
        {("GET", "/me/player/devices"): HttpResponse(200, DEVICES), ("PUT", "/me/player"): HttpResponse(204)},
        token_path,
    )
    assert await api.transfer("la sala") == "Sala"
    assert http.calls("PUT", "/me/player")[0]["json"] == {"device_ids": ["dev-sala"], "play": True}


async def test_expired_token_is_refreshed_and_saved(token_path):
    clock = Clock()
    clock.now = 99999  # el token del fixture ya venció
    routes = {
        ("POST", "/api/token"): HttpResponse(200, {"access_token": "B", "expires_in": 3600}),
        ("PUT", "/me/player/pause"): HttpResponse(204),
    }
    api, http = api_with(routes, token_path, clock)
    await api.pause()
    assert http.calls("POST", "/api/token")[0]["form"]["grant_type"] == "refresh_token"
    saved = json.loads(token_path.read_text())
    assert saved["access_token"] == "B" and saved["refresh_token"] == "R"


async def test_rejected_refresh_requires_login(token_path):
    clock = Clock()
    clock.now = 99999
    api, _ = api_with({("POST", "/api/token"): HttpResponse(400, {"error": "invalid_grant"})}, token_path, clock)
    with pytest.raises(AuthRequired):
        await api.pause()


async def test_no_token_requires_login(tmp_path):
    api, _ = api_with({}, tmp_path / "missing.json")
    with pytest.raises(AuthRequired):
        await api.pause()


async def test_network_error_is_unavailable(token_path):
    api, _ = api_with({("PUT", "/me/player/pause"): HttpError("sin red")}, token_path)
    with pytest.raises(BackendUnavailable):
        await api.pause()


def test_pkce_challenge_matches_rfc7636_example():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_authorization_url_has_pkce_and_scopes(token_path):
    auth = SpotifyAuth("client", "http://127.0.0.1:8765/callback", token_path, FakeHttp({}))
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(auth.authorization_url("v" * 64, "st")).query))
    assert query["code_challenge_method"] == "S256"
    assert query["redirect_uri"] == "http://127.0.0.1:8765/callback"
    assert "user-modify-playback-state" in query["scope"]


async def test_playlist_that_cannot_be_played_falls_back_to_the_next_one(token_path):
    editorial = {"name": "Cocinando", "uri": "spotify:playlist:editorial", "owner": {"id": "spotify"}}
    family = {"name": "Música para cocinar", "uri": "spotify:playlist:otra", "owner": {"id": "ana"}}

    def play(params, body, form):
        if body == {"context_uri": "spotify:playlist:editorial"}:
            return HttpResponse(404, {"error": {"status": 404, "message": "Not found"}})
        return HttpResponse(204)

    api, http = api_with(
        {
            ("GET", "/me/playlists"): HttpResponse(200, {"items": []}),
            ("GET", "/search"): search_returning(playlists=[editorial, None, family]),
            ("GET", "/me/player/devices"): HttpResponse(200, DEVICES),
            ("PUT", "/me/player/play"): play,
        },
        token_path,
    )
    result = await api.play("música para cocinar", "playlist")
    assert result.describe() == "La playlist Música para cocinar"
    assert [c["json"] for c in http.calls("PUT", "/me/player/play")] == [
        {"context_uri": "spotify:playlist:editorial"}, {"context_uri": "spotify:playlist:otra"},
    ]


async def test_other_errors_are_not_retried_with_other_playlists(token_path):
    api, http = api_with(
        {
            ("GET", "/search"): search_returning(artists=[ARTIST]),
            ("GET", "/me/player/devices"): HttpResponse(200, DEVICES),
            ("PUT", "/me/player/play"): HttpResponse(502, {}),
        },
        token_path,
    )
    with pytest.raises(BackendUnavailable):
        await api.play("soda stereo")
    assert len(http.calls("PUT", "/me/player/play")) == 1
