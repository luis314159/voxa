"""Interfaz común de música y la combinación en capas (Web API → Spotifast → MPRIS).

Cada backend lanza ``BackendUnavailable`` cuando no puede hacer algo; la capa
siguiente lo intenta. ``NothingFound`` corta la cadena: si Spotify no encontró
la búsqueda, otra capa tampoco la encontrará.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, Sequence

log = logging.getLogger(__name__)


class BackendUnavailable(Exception):
    pass


class NotSupported(BackendUnavailable):
    pass


class AuthRequired(BackendUnavailable):
    pass


class NeedsPermission(BackendUnavailable):
    """La autorización de Spotify es de antes y no incluye este permiso: hay que volver a conectar."""


class NothingFound(Exception):
    pass


@dataclass(frozen=True)
class PlayResult:
    title: str
    artist: str | None = None
    kind: str | None = None

    def describe(self) -> str:
        from voxa.i18n import tr

        if self.kind == "album":
            if self.artist:
                return tr("El álbum {title}, de {artist}", title=self.title, artist=self.artist)
            return tr("El álbum {title}", title=self.title)
        if self.kind == "playlist":
            return tr("La playlist {title}", title=self.title)
        if self.kind == "liked":
            return tr("Tus Me gusta, en aleatorio")
        if self.artist and self.kind == "track":
            return tr("{title}, de {artist}", title=self.title, artist=self.artist)
        return self.title


@dataclass(frozen=True)
class Playlist:
    name: str
    uri: str
    owner: str = ""
    tracks: int | None = None
    image: str | None = None


@dataclass(frozen=True)
class NowPlaying:
    title: str
    artist: str | None = None
    playing: bool = True
    # Para la pantalla (solo MPRIS los llena; los segundos son flotantes).
    album: str | None = None
    art_url: str | None = None
    position: float | None = None
    length: float | None = None


class MusicBackend(Protocol):
    name: str

    async def play(self, query: str, kind: str | None = None) -> PlayResult: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...
    async def next(self) -> None: ...
    async def previous(self) -> None: ...
    async def seek(self, seconds: int) -> None: ...
    async def shuffle(self, on: bool) -> None: ...
    async def like(self) -> None: ...
    async def now_playing(self) -> NowPlaying | None: ...
    async def transfer(self, device: str) -> str: ...
    # Opcionales (solo la Web API): las capas que no los tienen se saltan.
    async def playlists(self) -> list[Playlist]: ...
    async def search_playlists(self, query: str) -> list[Playlist]: ...
    async def play_uri(self, uri: str, title: str) -> PlayResult: ...
    async def play_liked(self) -> PlayResult: ...


# Búsquedas y funciones de cuenta: primero la Web API. Transporte: primero MPRIS (local, sin red).
SEARCH_METHODS = (
    "play", "like", "now_playing", "transfer", "shuffle", "playlists", "search_playlists", "play_uri", "play_liked",
)
CONTROL_METHODS = ("pause", "resume", "next", "previous", "seek")


class MusicRouter:
    """Spotify (si está configurado) y YouTube de respaldo: los controles van a la que está sonando.

    «Pon Soda Stereo» prueba Spotify y, si no está listo (sin Client ID, sin Premium, Spotifast
    cerrado), YouTube. Lo que es de una cuenta (Me gusta, playlists, pasar la música) es de Spotify.
    """

    name = "musica"

    def __init__(
        self,
        spotify: MusicBackend | None,
        youtube: MusicBackend | None,
        spotify_now_playing: Callable[[], Awaitable[NowPlaying | None]] | None = None,
    ) -> None:
        self._spotify = spotify
        self._youtube = youtube
        self._backends = [b for b in (spotify, youtube) if b is not None]
        self.active: MusicBackend | None = self._backends[0] if self._backends else None
        self._spotify_now_playing = spotify_now_playing

    async def _switch_to(self, backend: MusicBackend) -> None:
        old, self.active = self.active, backend
        if old is not None and old is not backend:
            stop = getattr(old, "stop", None) or old.pause  # YouTube se cierra; Spotify se pausa
            try:
                await stop()
            except BackendUnavailable:
                pass

    async def play(self, query: str, kind: str | None = None) -> PlayResult:
        reasons: list[Exception] = []
        for backend in self._backends:
            try:
                result = await backend.play(query, kind)
            except (BackendUnavailable, NothingFound) as exc:
                log.info("%s no pudo poner «%s»: %s", backend.name, query, exc)
                reasons.append(exc)
                continue
            await self._switch_to(backend)
            return result
        for kind_of in (NothingFound, AuthRequired):
            if any(isinstance(r, kind_of) for r in reasons):
                raise next(r for r in reasons if isinstance(r, kind_of))
        raise BackendUnavailable("no hay música disponible") from (reasons[-1] if reasons else None)

    def _current(self) -> MusicBackend:
        if self.active is None:
            raise BackendUnavailable("no hay música configurada")
        return self.active

    async def pause(self) -> None:
        await self._current().pause()

    async def resume(self) -> None:
        await self._current().resume()

    async def next(self) -> None:
        await self._current().next()

    async def previous(self) -> None:
        await self._current().previous()

    async def seek(self, seconds: int) -> None:
        await self._current().seek(seconds)

    async def shuffle(self, on: bool) -> None:
        await self._current().shuffle(on)

    async def now_playing(self) -> NowPlaying | None:
        return await self._current().now_playing()

    async def display_now_playing(self) -> NowPlaying | None:
        """Para la pantalla: Spotify se pregunta por MPRIS (local, sin gastar la Web API)."""
        if self.active is self._spotify and self._spotify_now_playing is not None:
            return await self._spotify_now_playing()
        return await self._current().now_playing()

    def _account(self) -> MusicBackend:
        if self._spotify is None:
            raise NotSupported("eso es de Spotify, y no está conectado")
        return self._spotify

    async def like(self) -> None:
        if self.active is not self._spotify:
            raise NotSupported("«Me gusta» es de Spotify")
        await self._account().like()

    async def transfer(self, device: str) -> str:
        return await self._account().transfer(device)

    async def playlists(self) -> list[Playlist]:
        return await self._account().playlists()

    async def search_playlists(self, query: str) -> list[Playlist]:
        return await self._account().search_playlists(query)

    async def play_uri(self, uri: str, title: str) -> PlayResult:
        result = await self._account().play_uri(uri, title)
        await self._switch_to(self._account())
        return result

    async def play_liked(self) -> PlayResult:
        result = await self._account().play_liked()
        await self._switch_to(self._account())
        return result


class LayeredMusicBackend:
    name = "capas"

    def __init__(self, search_order: Sequence[MusicBackend], control_order: Sequence[MusicBackend]) -> None:
        self._search = list(search_order)
        self._control = list(control_order)

    async def _first(self, method: str, *args):
        layers = self._search if method in SEARCH_METHODS else self._control
        reasons = []
        for backend in layers:
            call = getattr(backend, method, None)
            if call is None:
                continue
            try:
                return await call(*args)
            except NotSupported:
                continue
            except BackendUnavailable as exc:
                log.info("%s no pudo hacer %s: %s", backend.name, method, exc)
                reasons.append(exc)
        if any(isinstance(r, AuthRequired) for r in reasons):
            raise AuthRequired(method)
        if any(isinstance(r, NeedsPermission) for r in reasons):
            raise NeedsPermission(method)
        raise BackendUnavailable(f"ninguna capa pudo hacer {method}")

    async def play(self, query: str, kind: str | None = None) -> PlayResult:
        return await self._first("play", query, kind)

    async def pause(self) -> None:
        await self._first("pause")

    async def resume(self) -> None:
        await self._first("resume")

    async def next(self) -> None:
        await self._first("next")

    async def previous(self) -> None:
        await self._first("previous")

    async def seek(self, seconds: int) -> None:
        await self._first("seek", seconds)

    async def shuffle(self, on: bool) -> None:
        await self._first("shuffle", on)

    async def like(self) -> None:
        await self._first("like")

    async def now_playing(self) -> NowPlaying | None:
        return await self._first("now_playing")

    async def transfer(self, device: str) -> str:
        return await self._first("transfer", device)

    async def playlists(self) -> list[Playlist]:
        return await self._first("playlists")

    async def search_playlists(self, query: str) -> list[Playlist]:
        return await self._first("search_playlists", query)

    async def play_uri(self, uri: str, title: str) -> PlayResult:
        return await self._first("play_uri", uri, title)

    async def play_liked(self) -> PlayResult:
        return await self._first("play_liked")
