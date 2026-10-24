"""Arma el asistente con sus servicios reales o simulados."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from voxa.config import Config
from voxa.core.assistant import Assistant
from voxa.health import Check, internet_check, player_check, spotify_check
from voxa.nlu.matcher import Matcher, load_matcher
from voxa.services.http import UrllibHttp
from voxa.services.mpris import PlayerctlBackend
from voxa.services.music_backend import LayeredMusicBackend, MusicBackend, NowPlaying
from voxa.services.pipewire import VolumeControl, WpctlVolume
from voxa.services.simulated import SimulatedMusic, SimulatedVideoPlayer, SimulatedVideoSearch, SimulatedVolume
from voxa.services.spotifast_cli import SpotifastCli
from voxa.services.spotify_api import SpotifyWebApi
from voxa.services.spotify_auth import SpotifyAuth
from voxa.services.video import MpvPlayer, VideoPlayer, VideoSearch, YtDlpSearch
from voxa.services.weather import OpenMeteo
from voxa.skills.clock import ClockSkill
from voxa.skills.kitchen import KitchenSkill
from voxa.skills.music import MusicSkill
from voxa.skills.routine import RoutineSkill
from voxa.skills.system import SystemSkill
from voxa.skills.timers import TimerSkill
from voxa.skills.video import VideoSkill
from voxa.skills.volume import VolumeSkill
from voxa.skills.weather import WeatherSkill
from voxa.state.timers import Timer, TimerManager

if TYPE_CHECKING:  # el audio (numpy, sounddevice…) solo se importa al usar la voz
    from voxa.audio.stt import SpeechToText
    from voxa.audio.tts import PiperTts
    from voxa.audio.wakeword import WakeWordDetector
    from voxa.voice import VoiceSession


@dataclass
class App:
    assistant: Assistant
    timers: TimerManager
    matcher: Matcher
    # Para la pantalla: lo que suena, preguntado localmente por MPRIS (sin gastar la Web API).
    now_playing: Callable[[], Awaitable[NowPlaying | None]] | None = None
    weather: OpenMeteo | None = None
    video: VideoPlayer | None = None
    health_checks: list[Check] = field(default_factory=list)
    config: Config = field(default_factory=Config)


class SetupError(Exception):
    """Falta algo para arrancar (modelo, voz…); el mensaje dice qué hacer."""


def _existing(path: str, what: str, hint: str) -> Path:
    if not path:
        raise SetupError(f"Falta configurar {what} en [voice] de config.toml. {hint}")
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise SetupError(f"No encontré {what}: {resolved}. {hint}")
    return resolved


def build_stt(config: Config, matcher: Matcher) -> SpeechToText:
    from voxa.audio.stt import HybridStt, VoskStt, WhisperStt

    voice = config.voice
    vosk_hint = "Descarga vosk-model-small-es de https://alphacephei.com/vosk/models."
    if voice.stt == "vosk":
        return VoskStt(_existing(voice.vosk_model, "el modelo de Vosk", vosk_hint))
    if voice.stt == "whisper":
        return WhisperStt(voice.whisper_model)
    if voice.stt == "hibrido":
        fast = VoskStt(_existing(voice.vosk_model, "el modelo de Vosk", vosk_hint))
        return HybridStt(fast, WhisperStt(voice.whisper_model), matcher.needs_accurate_stt, matcher.understands)
    raise SetupError(f"Motor de STT desconocido: {voice.stt!r} (usa vosk, whisper o hibrido).")


def build_tts(config: Config) -> PiperTts:
    from voxa.audio.pronunciation import DEFAULT_LEXICON, Lexicon
    from voxa.audio.tts import PiperTts

    hint = "Descarga una voz con: python -m piper.download_voices es_MX-claude-high --download-dir models/piper"
    model = _existing(config.voice.piper_voice, "la voz de Piper", hint)
    lexicon = Lexicon.load(DEFAULT_LEXICON, config.pronunciation_path)
    return PiperTts(model, config.tts_cache_dir, config.voice.speech_rate, lexicon)


def build_wake(config: Config) -> WakeWordDetector:
    """«Hey Voxa». ``SetupError`` si faltan los modelos base (VOXA sigue con «toca para hablar»)."""
    from voxa.audio.wakeword import DEFAULT_MODEL, WakeWordDetector

    wake = config.wake
    model = Path(wake.model).expanduser() if wake.model else DEFAULT_MODEL
    if not model.exists():
        raise SetupError(f"No encontré el modelo de «Hey Voxa»: {model}.")
    try:
        return WakeWordDetector.load(
            Path(wake.feature_dir).expanduser(), model, wake.threshold or None, patience=wake.patience
        )
    except FileNotFoundError as exc:
        raise SetupError(f"{exc}.") from exc


def build_voice(config: Config, app: App, *, simulated: bool = False) -> VoiceSession:
    from voxa.audio.devices import SpeakerOutput
    from voxa.audio.ducking import NoDucking, PipeWireDucker
    from voxa.audio.endpoint import EndpointConfig
    from voxa.audio.sounds import make_sounds
    from voxa.voice import VoiceSession

    voice = config.voice
    return VoiceSession(
        app.assistant,
        build_stt(config, app.matcher),
        build_tts(config),
        SpeakerOutput(voice.output_device or None, voice.lead_in_ms),
        make_sounds(),
        NoDucking() if simulated or sys.platform != "linux" else PipeWireDucker(voice.duck_level),
        echo_guard_ms=voice.echo_guard_ms,
        endpoint=EndpointConfig(end_silence_ms=voice.end_silence_ms),
    )


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
    now_playing = music.now_playing if simulated else PlayerctlBackend(config.spotifast.mpris_player).now_playing
    volume: VolumeControl = SimulatedVolume() if simulated else WpctlVolume()
    weather = None
    if config.weather.latitude is not None and config.weather.longitude is not None:
        weather = OpenMeteo(UrllibHttp(), config.weather.latitude, config.weather.longitude)

    video = build_video(config, simulated=simulated)
    skills = {
        "music": MusicSkill(music),
        "volume": VolumeSkill(volume, config.volume.step),
        "timer": TimerSkill(timers),
        "clock": ClockSkill(),
        "weather": WeatherSkill(weather),
        "system": SystemSkill(),
        "kitchen": KitchenSkill(),
        "routine": RoutineSkill(timers, weather, music, config.routine.morning_music),
    }
    player = None
    if video is not None:
        search, player = video
        skills["video"] = VideoSkill(search, player, music)
    checks: list[Check] = []
    if not simulated:
        checks = [
            internet_check(),
            spotify_check(config.spotify.client_id, config.spotify_token_path),
            player_check(now_playing, config.spotifast.mpris_player),
        ]
    matcher = load_matcher()
    video_active = (lambda: player.current is not None) if player is not None else None
    assistant = Assistant(matcher, skills, timers, video_active=video_active)
    return App(assistant, timers, matcher, now_playing, weather, player, checks, config)


def build_video(config: Config, *, simulated: bool = False) -> tuple[VideoSearch, VideoPlayer] | None:
    """yt-dlp + mpv; el control de mpv usa un socket Unix, así que en Windows solo hay simulación."""
    if not config.video.enabled:
        return None
    if simulated:
        return SimulatedVideoSearch(), SimulatedVideoPlayer()
    if sys.platform == "win32":
        return None
    video = config.video
    return YtDlpSearch((video.ytdlp,)), MpvPlayer(video.mpv, video.ytdlp, video.max_height)
