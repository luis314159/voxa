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
class MusicConfig:
    provider: str = "auto"
    """«auto»: Spotify si está conectado (y YouTube de respaldo); si no, YouTube. «spotify» o «youtube»."""


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
    language: str = "es"
    """Idioma de la casa: «es» o «en» (gramática, voz, reconocimiento y respuestas)."""
    bilingual: bool = False
    """Casa bilingüe: también entiende el otro idioma y contesta cada frase en el idioma en que se dijo."""
    stt: str = "hibrido"
    vosk_model: str = "~/.local/share/voxa/models/vosk-model-small-es-0.42"
    whisper_model: str = "base"
    piper_voice: str = "~/.local/share/voxa/models/piper/es_MX-claude-high.onnx"
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
    departure: str = ""
    """Hora de salida de la mañana («07:30»; vacío: sin avisos de salida)."""
    departure_days: tuple[int, ...] = (0, 1, 2, 3, 4)
    """Días con salida (0 = lunes)."""
    checklist: str = ""
    """Lo que no hay que olvidar al salir («mochila, lonche, uniforme»)."""


@dataclass(frozen=True)
class KidsConfig:
    enabled: bool = False
    children: tuple[str, ...] = ()
    """Quiénes son niños, como se llaman en «aprende mi voz»: las reglas aplican cuando VOXA reconoce su voz."""
    everyone: bool = False
    """Las reglas aplican a todos (niños chicos, visitas, o si nadie ha grabado su voz)."""
    clean_music: bool = True
    max_volume: int = 70
    video_from: str = ""
    video_until: str = ""
    """Horario en que los niños pueden pedir videos («16:00» a «19:00»); vacío: a cualquier hora."""


@dataclass(frozen=True)
class QuietConfig:
    enabled: bool = False
    start: str = "22:00"
    end: str = "07:00"
    level: float = 0.35
    """Qué tan fuerte salen la voz y los sonidos en esas horas (1 = normal); las alarmas, normal."""


@dataclass(frozen=True)
class MedicineConfig:
    enabled: bool = True
    """Los recordatorios de medicina preguntan «¿ya te la tomaste?» y esperan respuesta."""
    ask_every_minutes: int = 5
    tries: int = 3
    """Cuántas veces pregunta antes de avisar a otra persona."""
    notify_telegram: bool = True
    notify_house: bool = True


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
    enabled: bool = True
    port: int = 8770


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False


@dataclass(frozen=True)
class HouseConfig:
    room: str = "Cocina"
    main: str = ""
    """Dirección de la VOXA principal (``http://IP:8770``); vacío: esta es la principal."""


@dataclass(frozen=True)
class CalendarConfig:
    enabled: bool = False
    remind_minutes: int = 10
    """Avisa en voz alta este tiempo antes de cada evento (0: no avisa)."""


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
    music: MusicConfig = field(default_factory=MusicConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)
    timers: TimersConfig = field(default_factory=TimersConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    wake: WakeConfig = field(default_factory=WakeConfig)
    routine: RoutineConfig = field(default_factory=RoutineConfig)
    kids: KidsConfig = field(default_factory=KidsConfig)
    quiet: QuietConfig = field(default_factory=QuietConfig)
    medicine: MedicineConfig = field(default_factory=MedicineConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)
    web: WebConfig = field(default_factory=WebConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    calendar: CalendarConfig = field(default_factory=CalendarConfig)
    house: HouseConfig = field(default_factory=HouseConfig)
    config_dir: Path = field(default_factory=lambda: _xdg("XDG_CONFIG_HOME", ".config"))
    state_dir: Path = field(default_factory=lambda: _xdg("XDG_STATE_HOME", ".local/state"))

    @property
    def spotify_token_path(self) -> Path:
        return self.config_dir / "spotify_token.json"

    @property
    def web_key_path(self) -> Path:
        return self.config_dir / "web_clave"

    @property
    def house_key_path(self) -> Path:
        """La clave de la VOXA principal (en un cuarto unido a la casa)."""
        return self.config_dir / "casa_clave"

    @property
    def house_rooms_path(self) -> Path:
        return self.state_dir / "cuartos.json"

    @property
    def calendar_url_path(self) -> Path:
        """La dirección secreta (iCal) del calendario: quien la tiene puede leerlo."""
        return self.config_dir / "calendario_url"

    @property
    def calendars_path(self) -> Path:
        """El calendario de cada persona ({nombre: dirección iCal}, 600)."""
        return self.config_dir / "calendarios.json"

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
    def speaker_model_path(self) -> Path:
        return _xdg("XDG_DATA_HOME", ".local/share") / "models" / "speaker" / "wespeaker_en_voxceleb_resnet34_LM.onnx"

    @property
    def voices_path(self) -> Path:
        """Los prototipos de voz de cada persona (para saber quién habla)."""
        return _xdg("XDG_DATA_HOME", ".local/share") / "voces.npz"

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
    return _language_defaults(config), warnings + more


# Los modelos que se usan si no se eligieron otros, según el idioma de la casa.
MODEL_DEFAULTS = {
    "es": ("~/.local/share/voxa/models/vosk-model-small-es-0.42", "~/.local/share/voxa/models/piper/es_MX-claude-high.onnx"),
    "en": ("~/.local/share/voxa/models/vosk-model-small-en-us-0.15", "~/.local/share/voxa/models/piper/en_US-lessac-medium.onnx"),
}


def _language_defaults(config: Config) -> Config:
    """En inglés, los modelos por defecto son los de inglés (si no se eligieron otros a mano)."""
    voice = config.voice
    if voice.language not in MODEL_DEFAULTS or voice.language == "es":
        return config
    vosk_es, piper_es = MODEL_DEFAULTS["es"]
    vosk, piper = MODEL_DEFAULTS[voice.language]
    return replace(config, voice=replace(
        voice,
        vosk_model=vosk if voice.vosk_model == vosk_es else voice.vosk_model,
        piper_voice=piper if voice.piper_voice == piper_es else voice.piper_voice,
    ))


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
