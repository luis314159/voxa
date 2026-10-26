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
    place: str = ""


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
class RoutineConfig:
    morning_music: str = ""


@dataclass(frozen=True)
class WakeConfig:
    enabled: bool = True
    model: str = ""
    feature_dir: str = "~/.local/share/voxa/models/wakeword"
    threshold: float = 0.0
    patience: int = 2
    verifier: str = ""


@dataclass(frozen=True)
class AiConfig:
    enabled: bool = False
    provider: str = "claude"
    model: str = ""
    endpoint: str = ""
    key_env: str = ""
    effort: str = ""
    web_search: bool = False
    monthly_budget_usd: float = 5.0
    daily_questions: int = 60
    price_input: float = 0.0
    price_output: float = 0.0
    timeout_seconds: float = 15.0
    context: str = ""


@dataclass(frozen=True)
class WebConfig:
    enabled: bool = False
    port: int = 8770


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False


@dataclass(frozen=True)
class CalendarConfig:
    enabled: bool = False


@dataclass(frozen=True)
class UpdateConfig:
    check: bool = True
    automatic: bool = False


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
    wake: WakeConfig = field(default_factory=WakeConfig)
    routine: RoutineConfig = field(default_factory=RoutineConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)
    web: WebConfig = field(default_factory=WebConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    calendar: CalendarConfig = field(default_factory=CalendarConfig)
    config_dir: Path = field(default_factory=lambda: _xdg("XDG_CONFIG_HOME", ".config"))
    state_dir: Path = field(default_factory=lambda: _xdg("XDG_STATE_HOME", ".local/state"))

    @property
    def spotify_token_path(self) -> Path:
        return self.config_dir / "spotify_token.json"

    @property
    def web_key_path(self) -> Path:
        return self.config_dir / "web_clave"

    @property
    def calendar_url_path(self) -> Path:
        """La dirección secreta (iCal) del calendario: quien la tiene puede leerlo."""
        return self.config_dir / "calendario_url"

    @property
    def calendar_cache_path(self) -> Path:
        return _xdg("XDG_CACHE_HOME", ".cache") / "calendario.ics"

    @property
    def telegram_token_path(self) -> Path:
        return self.config_dir / "telegram_token"

    @property
    def telegram_chats_path(self) -> Path:
        return self.config_dir / "telegram_chats.json"

    @property
    def telegram_code_path(self) -> Path:
        return self.state_dir / "telegram_codigo.json"

    @property
    def backgrounds_dir(self) -> Path:
        return _xdg("XDG_DATA_HOME", ".local/share") / "fondos"

    @property
    def ai_key_path(self) -> Path:
        return self.config_dir / "ia_clave"

    @property
    def ai_usage_path(self) -> Path:
        return self.state_dir / "ia_uso.json"

    @property
    def pronunciation_path(self) -> Path:
        return self.config_dir / "pronunciacion.yaml"

    @property
    def wake_recordings_dir(self) -> Path:
        """Grabaciones de la familia para el verificador de «Hey Voxa» (solo en esta PC)."""
        return _xdg("XDG_DATA_HOME", ".local/share") / "activacion"

    @property
    def verifier_path(self) -> Path:
        if self.wake.verifier:
            return Path(self.wake.verifier).expanduser()
        return Path(self.wake.feature_dir).expanduser() / "verificador.npz"

    @property
    def recipe_path(self) -> Path:
        return self.state_dir / "receta.json"

    @property
    def shopping_path(self) -> Path:
        return self.state_dir / "lista_super.json"

    @property
    def timers_path(self) -> Path:
        return self.state_dir / "timers.json"

    @property
    def tts_cache_dir(self) -> Path:
        return _xdg("XDG_CACHE_HOME", ".cache") / "tts"


def config_path() -> Path:
    return Path(os.environ.get("VOXA_CONFIG") or Config().config_dir / "config.toml")


def load_config(path: Path | None = None) -> Config:
    config, warnings = read_config(path or config_path())
    for warning in warnings:
        log.warning("%s", warning)
    return config


def read_config(path: Path) -> tuple[Config, list[str]]:
    """La configuración y los avisos (opciones o secciones que VOXA no conoce: suelen ser erratas).

    Encima de ``config.toml`` van los ajustes que se eligieron en la app (``ajustes.json``).
    """
    from voxa.settings import load_settings, settings_path

    config, warnings = Config(), []
    if path.exists():
        with path.open("rb") as fh:
            config, warnings = _apply(config, tomllib.load(fh), path)
    overlay = settings_path(path)
    config, more = _apply(config, load_settings(overlay), overlay)
    return config, warnings + more


def _apply(config: Config, data: dict, path: Path) -> tuple[Config, list[str]]:
    data = dict(data)
    sections, warnings = {}, []
    for f in fields(Config):
        if f.name not in data or f.name in ("config_dir", "state_dir"):
            continue
        current = getattr(config, f.name)
        known = {sf.name for sf in fields(current)}
        values = data.pop(f.name)
        for unknown in sorted(set(values) - known):
            warnings.append(f"Opción desconocida en {path}: [{f.name}] {unknown}")
        values = {k: tuple(v) if isinstance(v, list) else v for k, v in values.items() if k in known}
        sections[f.name] = replace(current, **values)
    for unknown in data:
        warnings.append(f"Sección desconocida en {path}: [{unknown}]")
    return replace(config, **sections), warnings
