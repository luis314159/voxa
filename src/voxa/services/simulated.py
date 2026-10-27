"""Backends en memoria para el modo texto sin hardware (``voxa texto --simulado``) y las pruebas."""

from __future__ import annotations

from typing import Callable

from voxa.services.music_backend import NothingFound, NowPlaying, PlayResult, Playlist
from voxa.services.pipewire import VolumeState
from voxa.services.video import Video, VideoNotFound


class SimulatedMusic:
    name = "simulado"

    def __init__(self, devices: tuple[str, ...] = ("VOXA Cocina", "Sala")) -> None:
        self.current: NowPlaying | None = None
        self.liked: list[str] = []
        self.shuffled = False
        self.device = devices[0]
        self._devices = devices
        self.calls: list[str] = []

    async def play(self, query: str, kind: str | None = None) -> PlayResult:
        self.calls.append(f"play:{query}")
        self.current = NowPlaying(query.title(), None, playing=True)
        return PlayResult(query.title(), kind=kind)

    async def pause(self) -> None:
        self.calls.append("pause")
        if self.current:
            self.current = NowPlaying(self.current.title, self.current.artist, playing=False)

    async def resume(self) -> None:
        self.calls.append("resume")
        if self.current:
            self.current = NowPlaying(self.current.title, self.current.artist, playing=True)

    async def next(self) -> None:
        self.calls.append("next")

    async def previous(self) -> None:
        self.calls.append("previous")

    async def seek(self, seconds: int) -> None:
        self.calls.append(f"seek:{seconds}")

    async def shuffle(self, on: bool) -> None:
        self.shuffled = on

    async def like(self) -> None:
        if self.current:
            self.liked.append(self.current.title)

    async def now_playing(self) -> NowPlaying | None:
        return self.current

    async def playlists(self) -> list[Playlist]:
        return [Playlist("Cocina", "spotify:playlist:cocina", "Familia", 42),
                Playlist("Domingo en casa", "spotify:playlist:domingo", "Familia", 31)]

    async def search_playlists(self, query: str) -> list[Playlist]:
        return [Playlist(f"{query.title()} {n}", f"spotify:playlist:{n}", "Spotify", 50) for n in (1, 2)]

    async def play_liked(self) -> PlayResult:
        self.calls.append("liked")
        self.current = NowPlaying("Me gusta", None, playing=True)
        return PlayResult("tus Me gusta", kind="liked")

    async def play_uri(self, uri: str, title: str) -> PlayResult:
        self.calls.append(f"uri:{uri}")
        self.current = NowPlaying(title, None, playing=True)
        return PlayResult(title, kind="playlist")

    async def transfer(self, device: str) -> str:
        for name in self._devices:
            if name.lower() == device.lower():
                self.device = name
                return name
        raise NothingFound(device)


class SimulatedVolume:
    def __init__(self, percent: int = 40) -> None:
        self.state = VolumeState(percent, False)

    async def get(self) -> VolumeState:
        return self.state

    async def set(self, percent: int) -> None:
        self.state = VolumeState(max(0, min(100, percent)), self.state.muted)

    async def mute(self, on: bool) -> None:
        self.state = VolumeState(self.state.percent, on)


class SimulatedVideoSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str) -> Video:
        self.queries.append(query)
        if "no existe" in query:
            raise VideoNotFound(query)
        return Video(f"sim{len(self.queries)}", query[:1].upper() + query[1:], 600.0, "Cocina simulada")


class SimulatedVideoPlayer:
    def __init__(self, on_end: Callable[[], None] | None = None) -> None:
        self.on_end = on_end
        self._current: Video | None = None
        self.paused = False
        self.calls: list[str] = []

    @property
    def current(self) -> Video | None:
        return self._current

    async def play(self, video: Video) -> None:
        self.calls.append(f"play:{video.id}")
        self._current, self.paused = video, False

    async def pause(self) -> None:
        self.calls.append("pause")
        self.paused = True

    async def resume(self) -> None:
        self.calls.append("resume")
        self.paused = False

    async def seek(self, seconds: int) -> None:
        self.calls.append(f"seek:{seconds}")

    async def close(self) -> None:
        self.calls.append("close")
        self._current = None

    async def show_text(self, text: str, seconds: float = 2.0) -> None:
        self.calls.append(f"osd:{text}")

    def finish(self) -> None:
        """El video llegó al final (o lo cerraron con dos toques)."""
        self._current = None
        if self.on_end:
            self.on_end()
