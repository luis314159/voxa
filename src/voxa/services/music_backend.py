"""Interfaz común de música y la combinación en capas (Web API → Spotifast → MPRIS).

Cada backend lanza ``BackendUnavailable`` cuando no puede hacer algo; la capa
siguiente lo intenta. ``NothingFound`` corta la cadena: si Spotify no encontró
la búsqueda, otra capa tampoco la encontrará.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, Sequence

log = logging.getLogger(__name__)


class BackendUnavailable(Exception):
    pass


class NotSupported(BackendUnavailable):
    pass


class AuthRequired(BackendUnavailable):
    pass


class NothingFound(Exception):
    pass


@dataclass(frozen=True)
class PlayResult:
    title: str
    artist: str | None = None
    kind: str | None = None

    def describe(self) -> str:
        if self.kind == "album":
            return f"El álbum {self.title}" + (f", de {self.artist}" if self.artist else "")
        if self.kind == "playlist":
            return f"La playlist {self.title}"
        if self.artist and self.kind == "track":
            return f"{self.title}, de {self.artist}"
        return self.title


@dataclass(frozen=True)
class NowPlaying:
    title: str
    artist: str | None = None
    playing: bool = True


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


# Búsquedas y funciones de cuenta: primero la Web API. Transporte: primero MPRIS (local, sin red).
SEARCH_METHODS = ("play", "like", "now_playing", "transfer", "shuffle")
CONTROL_METHODS = ("pause", "resume", "next", "previous", "seek")


class LayeredMusicBackend:
    name = "capas"

    def __init__(self, search_order: Sequence[MusicBackend], control_order: Sequence[MusicBackend]) -> None:
        self._search = list(search_order)
        self._control = list(control_order)

    async def _first(self, method: str, *args):
        layers = self._search if method in SEARCH_METHODS else self._control
        reasons = []
        for backend in layers:
            try:
                return await getattr(backend, method)(*args)
            except NotSupported:
                continue
            except BackendUnavailable as exc:
                log.info("%s no pudo hacer %s: %s", backend.name, method, exc)
                reasons.append(exc)
        if any(isinstance(r, AuthRequired) for r in reasons):
            raise AuthRequired(method)
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
