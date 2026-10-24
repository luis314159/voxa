"""Configuración: valores por defecto + ``~/.config/voxa/config.toml`` (ver ``config/default.toml``)."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

log = logging.getLogger(__name__)


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback) / "voxa"


@dataclass(frozen=True)
class SpotifyConfig:
    client_id: str = ""
    device_name: str = "VOXA Cocina"
    redirect_uri: str = "http://127.0.0.1:8765/callback"


@dataclass(frozen=True)
class SpotifastConfig:
    command: tuple[str, ...] = ("spotifast",)
    mpris_player: str = "spotifast"


@dataclass(frozen=True)
class VolumeConfig:
    step: int = 10


@dataclass(frozen=True)
class TimersConfig:
    alarm_repeat_seconds: int = 30
    alarm_timeout_minutes: int = 10


@dataclass(frozen=True)
class WeatherConfig:
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class VoiceConfig:
    stt: str = "hibrido"
    vosk_model: str = ""
    whisper_model: str = "base"
    piper_voice: str = ""
    speech_rate: float = 1.0
    input_device: str = ""
    output_device: str = ""
    lead_in_ms: int = 0
    echo_guard_ms: int = 240
    duck_level: float = 0.2
    end_silence_ms: int = 720


@dataclass(frozen=True)
class VideoConfig:
    enabled: bool = True
    ytdlp: str = "yt-dlp"
    mpv: tuple[str, ...] = ("mpv",)
    max_height: int = 720


@dataclass(frozen=True)
class DisplayConfig:
    enabled: bool = True
    port: int = 8766


@dataclass(frozen=True)
class Config:
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)
    spotifast: SpotifastConfig = field(default_factory=SpotifastConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)
    timers: TimersConfig = field(default_factory=TimersConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    config_dir: Path = field(default_factory=lambda: _xdg("XDG_CONFIG_HOME", ".config"))
    state_dir: Path = field(default_factory=lambda: _xdg("XDG_STATE_HOME", ".local/state"))

    @property
    def spotify_token_path(self) -> Path:
        return self.config_dir / "spotify_token.json"

    @property
    def pronunciation_path(self) -> Path:
        return self.config_dir / "pronunciacion.yaml"

    @property
    def timers_path(self) -> Path:
        return self.state_dir / "timers.json"

    @property
    def tts_cache_dir(self) -> Path:
        return _xdg("XDG_CACHE_HOME", ".cache") / "tts"


def load_config(path: Path | None = None) -> Config:
    config = Config()
    path = path or Path(os.environ.get("VOXA_CONFIG") or config.config_dir / "config.toml")
    if not path.exists():
        return config
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    sections = {}
    for f in fields(Config):
        if f.name not in data or f.name in ("config_dir", "state_dir"):
            continue
        current = getattr(config, f.name)
        known = {sf.name for sf in fields(current)}
        values = data.pop(f.name)
        for unknown in set(values) - known:
            log.warning("Opción desconocida en %s: [%s] %s", path, f.name, unknown)
        values = {k: tuple(v) if isinstance(v, list) else v for k, v in values.items() if k in known}
        sections[f.name] = replace(current, **values)
    for unknown in data:
        log.warning("Sección desconocida en %s: [%s]", path, unknown)
    return replace(config, **sections)
