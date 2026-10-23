"""Arma el asistente con sus servicios reales o simulados."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from voxa.config import Config
from voxa.core.assistant import Assistant
from voxa.nlu.matcher import load_matcher
from voxa.services.http import UrllibHttp
from voxa.services.mpris import PlayerctlBackend
from voxa.services.music_backend import LayeredMusicBackend, MusicBackend
from voxa.services.pipewire import VolumeControl, WpctlVolume
from voxa.services.simulated import SimulatedMusic, SimulatedVolume
from voxa.services.spotifast_cli import SpotifastCli
from voxa.services.spotify_api import SpotifyWebApi
from voxa.services.spotify_auth import SpotifyAuth
from voxa.services.weather import OpenMeteo
from voxa.skills.clock import ClockSkill
from voxa.skills.music import MusicSkill
from voxa.skills.system import SystemSkill
from voxa.skills.timers import TimerSkill
from voxa.skills.volume import VolumeSkill
from voxa.skills.weather import WeatherSkill
from voxa.state.timers import Timer, TimerManager


@dataclass
class App:
    assistant: Assistant
    timers: TimerManager


def build_music(config: Config) -> MusicBackend:
    """Tres capas: Web API + Connect, CLI de Spotifast y MPRIS (ver plan §6.1)."""
    http = UrllibHttp()
    auth = SpotifyAuth(config.spotify.client_id, config.spotify.redirect_uri, config.spotify_token_path, http)
    web = SpotifyWebApi(auth, http, config.spotify.device_name)
    cli = SpotifastCli(config.spotifast.command)
    mpris = PlayerctlBackend(config.spotifast.mpris_player)
    return LayeredMusicBackend(search_order=[web, cli], control_order=[mpris, cli, web])


def build_app(config: Config, *, simulated: bool = False, on_ring: Callable[[Timer], None] | None = None) -> App:
    timers = TimerManager(
        None if simulated else config.timers_path,
        on_ring=on_ring,
        repeat_seconds=config.timers.alarm_repeat_seconds,
        ring_timeout_seconds=config.timers.alarm_timeout_minutes * 60,
    )
    music: MusicBackend = SimulatedMusic() if simulated else build_music(config)
    volume: VolumeControl = SimulatedVolume() if simulated else WpctlVolume()
    weather = None
    if config.weather.latitude is not None and config.weather.longitude is not None:
        weather = OpenMeteo(UrllibHttp(), config.weather.latitude, config.weather.longitude)

    skills = {
        "music": MusicSkill(music),
        "volume": VolumeSkill(volume, config.volume.step),
        "timer": TimerSkill(timers),
        "clock": ClockSkill(),
        "weather": WeatherSkill(weather),
        "system": SystemSkill(),
    }
    return App(Assistant(load_matcher(), skills, timers), timers)
