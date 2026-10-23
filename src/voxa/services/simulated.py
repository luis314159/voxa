"""Backends en memoria para el modo texto sin hardware (``voxa texto --simulado``) y las pruebas."""

from __future__ import annotations

from voxa.services.music_backend import NothingFound, NowPlaying, PlayResult
from voxa.services.pipewire import VolumeState


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
