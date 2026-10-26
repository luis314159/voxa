"""Spotify Web API + Connect: buscar y reproducir en «VOXA Cocina» u otro dispositivo.

Notas de las reglas de Development Mode (febrero 2026): la búsqueda devuelve
como máximo 10 resultados por tipo y ya no existe «top tracks» de artista, así
que «pon a X» reproduce el contexto del artista.
"""

from __future__ import annotations

import difflib
import logging
from typing import Any

from voxa.nlu.normalize import normalize
from voxa.services.http import Http, HttpError
from voxa.services.music_backend import (
    AuthRequired,
    BackendUnavailable,
    NotSupported,
    NothingFound,
    NowPlaying,
    PlayResult,
)
from voxa.services.spotify_auth import SpotifyAuth

log = logging.getLogger(__name__)

API = "https://api.spotify.com/v1"
_ARTIST_MATCH = 0.8
_PLAYLIST_MATCH = 0.6


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def _artists(item: dict) -> str | None:
    names = [a["name"] for a in item.get("artists") or [] if a]
    return ", ".join(names) or None


class SpotifyWebApi:
    name = "web-api"

    def __init__(self, auth: SpotifyAuth, http: Http, device_name: str) -> None:
        self._auth = auth
        self._http = http
        self.device_name = device_name

    async def _api(self, method: str, path: str, *, params=None, body=None, retry: bool = True) -> Any:
        headers = {"Authorization": f"Bearer {await self._auth.access_token()}"}
        try:
            resp = await self._http.request(method, f"{API}{path}", params=params, headers=headers, json_body=body)
        except HttpError as exc:
            raise BackendUnavailable(f"sin conexión con Spotify: {exc}") from exc
        if resp.status == 401 and retry:
            await self._auth.refresh()
            return await self._api(method, path, params=params, body=body, retry=False)
        if resp.status == 401:
            raise AuthRequired("Spotify rechazó el token")
        if resp.status == 404:
            raise BackendUnavailable("no hay dispositivo activo en Spotify Connect")
        if resp.status == 429:
            raise BackendUnavailable("Spotify pide esperar (límite de peticiones)")
        if resp.status >= 400:
            raise BackendUnavailable(f"Spotify respondió {resp.status}: {resp.data}")
        return resp.data

    # --- dispositivos ----------------------------------------------------
    async def devices(self) -> list[dict]:
        data = await self._api("GET", "/me/player/devices")
        return (data or {}).get("devices", [])

    async def _find_device(self, name: str) -> dict | None:
        devices = await self.devices()
        scored = [(similarity(name, d.get("name", "")), d) for d in devices]
        best = max(scored, key=lambda pair: pair[0], default=(0.0, None))
        return best[1] if best[0] >= 0.6 else None

    async def _home_device_id(self) -> str:
        device = await self._find_device(self.device_name)
        if device is None:
            raise BackendUnavailable(f"«{self.device_name}» no aparece en Spotify Connect")
        return device["id"]

    # --- búsqueda --------------------------------------------------------
    async def _search(self, query: str, types: str, limit: int = 5) -> dict:
        params = {"q": query, "type": types, "limit": limit, "market": "from_token"}
        return await self._api("GET", "/search", params=params) or {}

    @staticmethod
    def _items(results: dict, key: str) -> list[dict]:
        # La API a veces incluye None en las listas (p. ej. playlists borradas).
        return [i for i in (results.get(key) or {}).get("items", []) if i]

    async def _choose(self, query: str, kind: str | None) -> tuple[dict, PlayResult]:
        if kind == "playlist":
            if own := await self._own_playlist(query):
                return {"context_uri": own["uri"]}, PlayResult(own["name"], kind="playlist")

        if kind is None and " de " in query:
            # «persiana americana de soda stereo»: canción de un artista.
            title, artist = query.rsplit(" de ", 1)
            tracks = self._items(await self._search(f'track:"{title}" artist:"{artist}"', "track", 1), "tracks")
            if tracks:
                return self._track_body(tracks[0]), PlayResult(tracks[0]["name"], _artists(tracks[0]), "track")

        types = {"artist": "artist", "track": "track", "album": "album", "playlist": "playlist"}.get(
            kind or "", "artist,track,album,playlist"
        )
        results = await self._search(query, types)
        artists = self._items(results, "artists")
        tracks = self._items(results, "tracks")
        albums = self._items(results, "albums")
        playlists = self._items(results, "playlists")

        if kind == "artist" and artists:
            return {"context_uri": artists[0]["uri"]}, PlayResult(artists[0]["name"], kind="artist")
        if kind == "album" and albums:
            return {"context_uri": albums[0]["uri"]}, PlayResult(albums[0]["name"], _artists(albums[0]), "album")
        if kind == "playlist" and playlists:
            return {"context_uri": playlists[0]["uri"]}, PlayResult(playlists[0]["name"], kind="playlist")
        if kind == "track" and tracks:
            return self._track_body(tracks[0]), PlayResult(tracks[0]["name"], _artists(tracks[0]), "track")

        if kind is None:
            if artists and similarity(query, artists[0]["name"]) >= _ARTIST_MATCH:
                return {"context_uri": artists[0]["uri"]}, PlayResult(artists[0]["name"], kind="artist")
            if tracks:
                return self._track_body(tracks[0]), PlayResult(tracks[0]["name"], _artists(tracks[0]), "track")
            if playlists:
                return {"context_uri": playlists[0]["uri"]}, PlayResult(playlists[0]["name"], kind="playlist")
            if albums:
                return {"context_uri": albums[0]["uri"]}, PlayResult(albums[0]["name"], _artists(albums[0]), "album")
        raise NothingFound(query)

    @staticmethod
    def _track_body(track: dict) -> dict:
        # Se reproduce dentro de su álbum para que la música siga después de la canción.
        album_uri = (track.get("album") or {}).get("uri")
        if album_uri:
            return {"context_uri": album_uri, "offset": {"uri": track["uri"]}}
        return {"uris": [track["uri"]]}

    async def _own_playlist(self, query: str) -> dict | None:
        try:
            data = await self._api("GET", "/me/playlists", params={"limit": 50})
        except BackendUnavailable as exc:
            log.info("No pude leer las playlists propias: %s", exc)
            return None
        playlists = [p for p in (data or {}).get("items", []) if p]
        scored = [(similarity(query, p.get("name", "")), p) for p in playlists]
        best = max(scored, key=lambda pair: pair[0], default=(0.0, None))
        return best[1] if best[0] >= _PLAYLIST_MATCH else None

    # --- MusicBackend ----------------------------------------------------
    async def play(self, query: str, kind: str | None = None) -> PlayResult:
        body, result = await self._choose(query, kind)
        device_id = await self._home_device_id()
        try:
            await self._api("PUT", "/me/player/play", params={"device_id": device_id}, body=body)
        except BackendUnavailable as exc:
            if result.kind != "playlist":
                raise
            # Algunas playlists editoriales de Spotify no se dejan poner desde apps nuevas de la Web
            # API: con el dispositivo ya encontrado, se prueba con las siguientes de la búsqueda.
            log.info("No se pudo poner la playlist «%s» (%s); pruebo otras", result.title, exc)
            return await self._other_playlist(query, device_id, body.get("context_uri"), exc)
        return result

    async def _other_playlist(self, query: str, device_id: str, failed: str | None, error: Exception) -> PlayResult:
        tried = 0
        for playlist in self._items(await self._search(query, "playlist"), "playlists"):
            if playlist.get("uri") == failed or tried >= 2:
                continue
            tried += 1
            try:
                body = {"context_uri": playlist["uri"]}
                await self._api("PUT", "/me/player/play", params={"device_id": device_id}, body=body)
            except BackendUnavailable as exc:
                error = exc
                continue
            return PlayResult(playlist["name"], kind="playlist")
        raise error

    async def pause(self) -> None:
        await self._api("PUT", "/me/player/pause")

    async def resume(self) -> None:
        await self._api("PUT", "/me/player/play")

    async def next(self) -> None:
        await self._api("POST", "/me/player/next")

    async def previous(self) -> None:
        await self._api("POST", "/me/player/previous")

    async def seek(self, seconds: int) -> None:
        raise NotSupported("la Web API necesita la posición actual; se usa Spotifast/MPRIS")

    async def shuffle(self, on: bool) -> None:
        await self._api("PUT", "/me/player/shuffle", params={"state": "true" if on else "false"})

    async def like(self) -> None:
        raise NotSupported("se guarda con Spotifast")

    async def now_playing(self) -> NowPlaying | None:
        data = await self._api("GET", "/me/player/currently-playing", params={"market": "from_token"})
        item = (data or {}).get("item")
        if not item:
            return None
        return NowPlaying(item["name"], _artists(item), playing=bool(data.get("is_playing")))

    async def transfer(self, device: str) -> str:
        target = await self._find_device(device)
        if target is None:
            raise NothingFound(device)
        await self._api("PUT", "/me/player", body={"device_ids": [target["id"]], "play": True})
        return target["name"]
