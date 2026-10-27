"""Arma el asistente con sus servicios reales o simulados."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from voxa.config import MODEL_DEFAULTS, Config, config_path
from voxa.core.assistant import Assistant
from voxa.health import Check, internet_check, player_check, spotify_check
from voxa.nlu.matcher import Matcher, load_matcher
from voxa.services.ai import AiSetupError, build_chat, prices_for, read_key
from voxa.services.calendar import Calendar, personal_calendars
from voxa.services.http import UrllibHttp
from voxa.services.mpris import PlayerctlBackend
from voxa.services.music_backend import LayeredMusicBackend, MusicBackend, MusicRouter, NowPlaying
from voxa.services.pipewire import VolumeControl, WpctlVolume
from voxa.services.simulated import SimulatedMusic, SimulatedVideoPlayer, SimulatedVideoSearch, SimulatedVolume
from voxa.services.spotifast_cli import SpotifastCli
from voxa.services.spotify_api import SpotifyWebApi
from voxa.services.spotify_auth import SpotifyAuth
from voxa.services.video import MpvPlayer, VideoPlayer, VideoSearch, YtDlpSearch
from voxa.services.weather import OpenMeteo
from voxa.services.youtube_music import YouTubeMusic
from voxa.skills.ai import AiFallback
from voxa.skills.clock import ClockSkill
from voxa.skills.kids import KidsSkill
from voxa.skills.kitchen import KitchenSkill
from voxa.skills.music import MusicSkill
from voxa.skills.recipe import RecipeSkill
from voxa.skills.routine import RoutineSkill
from voxa.departure import Departure
from voxa.house import SHARED_DOMAINS, House
from voxa.i18n import other_language, set_language
from voxa.kids import KidsRules
from voxa.kids import saver as kids_saver
from voxa.skills.calendar import CalendarSkill
from voxa.skills.house import HouseSkill, RemoteSkill
from voxa.skills.enroll import EnrollSkill
from voxa.skills.screen import ScreenSkill
from voxa.skills.shopping import ShoppingSkill
from voxa.skills.tasks import TasksSkill
from voxa.skills.system import SystemSkill
from voxa.skills.timers import TimerSkill
from voxa.skills.updates import UpdateSkill
from voxa.skills.video import VideoSkill
from voxa.skills.volume import VolumeSkill
from voxa.skills.weather import WeatherSkill
from voxa.settings import read_secret
from voxa.state.ai_usage import AiUsage
from voxa.state.recipe import RecipeSession
from voxa.state.shopping import ShoppingList
from voxa.state.tasks import TaskList
from voxa.state.timers import Timer, TimerManager
from voxa.update import Updater

if TYPE_CHECKING:  # el audio (numpy, sounddevice…) solo se importa al usar la voz
    from voxa.audio.stt import SpeechToText
    from voxa.audio.tts import BilingualTts, PiperTts
    from voxa.audio.wakeword import WakeWordDetector
    from voxa.voice import VoiceSession

log = logging.getLogger(__name__)


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
    shopping: ShoppingList = field(default_factory=ShoppingList)
    recipe: RecipeSession = field(default_factory=RecipeSession)
    updater: Updater | None = None
    ai: AiFallback | None = None
    ai_problem: str | None = None
    """Por qué la IA activada no pudo arrancar (falta la llave, el SDK…)."""
    music: MusicBackend | None = None
    """Para el celular: las playlists de la cuenta y ponerlas con un toque."""
    house: House | None = None
    tasks: TaskList = field(default_factory=TaskList)
    kids: KidsRules | None = None


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
    also = (other_language(voice.language),) if voice.bilingual else ()  # Whisper detecta el idioma
    if voice.stt == "whisper":
        return WhisperStt(voice.whisper_model, language=voice.language, also=also)
    if voice.stt == "hibrido":
        fast = VoskStt(_existing(voice.vosk_model, "el modelo de Vosk", vosk_hint))
        closed = VoskStt(Path(voice.vosk_model).expanduser(), matcher.vocabulary, model=fast.model)
        return HybridStt(
            fast, WhisperStt(voice.whisper_model, language=voice.language, also=also), matcher.needs_accurate_stt,
            matcher.understands, closed=closed
        )
    raise SetupError(f"Motor de STT desconocido: {voice.stt!r} (usa vosk, whisper o hibrido).")


def build_tts(config: Config) -> PiperTts | BilingualTts:
    from voxa.audio.pronunciation import DEFAULT_LEXICON, Lexicon
    from voxa.audio.tts import BilingualTts, PiperTts

    hint = "Descarga una voz con: python -m piper.download_voices es_MX-claude-high --download-dir models/piper"
    voice = config.voice
    model = _existing(voice.piper_voice, "la voz de Piper", hint)
    lexicon = Lexicon.load(DEFAULT_LEXICON, config.pronunciation_path)
    home = PiperTts(model, config.tts_cache_dir, voice.speech_rate, lexicon)
    if not voice.bilingual:
        return home
    other = other_language(voice.language)
    second = Path(MODEL_DEFAULTS[other][1]).expanduser()
    if not second.exists():
        log.warning("Casa bilingüe sin la voz de %s (%s): «voxa preparar» la baja", other, second)
        return home
    return BilingualTts({voice.language: home, other: PiperTts(second, config.tts_cache_dir, voice.speech_rate, lexicon)},
                        voice.language)


def build_wake(config: Config) -> WakeWordDetector:
    """«Hey Voxa». ``SetupError`` si faltan los modelos base (VOXA sigue con «toca para hablar»)."""
    from voxa.audio.wakeword import DEFAULT_MODEL, WakeWordDetector

    wake = config.wake
    model = Path(wake.model).expanduser() if wake.model else DEFAULT_MODEL
    if not model.exists():
        raise SetupError(f"No encontré el modelo de «Hey Voxa»: {model}.")
    try:
        return WakeWordDetector.load(
            Path(wake.feature_dir).expanduser(),
            model,
            wake.threshold or None,
            verifier=config.verifier_path,
            patience=wake.patience,
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
    session = VoiceSession(
        app.assistant,
        build_stt(config, app.matcher),
        build_tts(config),
        SpeakerOutput(voice.output_device or None, voice.lead_in_ms),
        make_sounds(),
        NoDucking() if simulated or sys.platform != "linux" else PipeWireDucker(voice.duck_level),
        echo_guard_ms=voice.echo_guard_ms,
        endpoint=EndpointConfig(end_silence_ms=voice.end_silence_ms),
    )
    if not simulated:
        from voxa.audio.speaker import SpeakerIdentifier

        session.identify = SpeakerIdentifier(config.speaker_model_path, config.voices_path)
    return session


def build_spotify(config: Config, clean: Callable[[], bool] | None = None) -> MusicBackend:
    """Tres capas: Web API + Connect, CLI de Spotifast y MPRIS (ver plan §6.1).

    ``clean``: si hay que evitar canciones explícitas (modo niños).
    """
    http = UrllibHttp()
    auth = SpotifyAuth(config.spotify.client_id, config.spotify.redirect_uri, config.spotify_token_path, http)
    web = SpotifyWebApi(auth, http, config.spotify.device_name)
    if clean is not None:
        web.clean = clean
    cli = SpotifastCli(config.spotifast.command)
    mpris = PlayerctlBackend(config.spotifast.mpris_player)
    return LayeredMusicBackend(search_order=[web, cli], control_order=[mpris, cli, web])


def spotify_ready(config: Config) -> bool:
    return bool(config.spotify.client_id) and config.spotify_token_path.exists()


def build_music(config: Config, clean: Callable[[], bool] | None = None) -> MusicRouter:
    """Spotify si está conectado (o se pidió), y YouTube (sin cuenta) de respaldo o como única música."""
    provider = config.music.provider
    spotify = None
    if provider == "spotify" or (provider == "auto" and spotify_ready(config)):
        spotify = build_spotify(config, clean)
    youtube = None if provider == "spotify" else YouTubeMusic(ytdlp=(config.video.ytdlp,), mpv=config.video.mpv)
    mpris = PlayerctlBackend(config.spotifast.mpris_player)
    return MusicRouter(spotify, youtube, spotify_now_playing=mpris.now_playing)


def build_app(config: Config, *, simulated: bool = False, on_ring: Callable[[Timer], None] | None = None) -> App:
    timers = TimerManager(
        None if simulated else config.timers_path,
        on_ring=on_ring,
        repeat_seconds=config.timers.alarm_repeat_seconds,
        ring_timeout_seconds=config.timers.alarm_timeout_minutes * 60,
    )
    kids = KidsRules(config.kids, save=None if simulated else kids_saver(config_path()))
    music: MusicBackend = SimulatedMusic() if simulated else build_music(config, kids.clean_music)
    now_playing = music.now_playing if simulated else music.display_now_playing
    volume: VolumeControl = SimulatedVolume() if simulated else WpctlVolume()
    calendar, personal = None, {}
    if config.calendar.enabled:
        if read_secret(config.calendar_url_path):
            calendar = Calendar(lambda: read_secret(config.calendar_url_path), UrllibHttp(), config.calendar_cache_path)
        for i, (person, url) in enumerate(sorted(personal_calendars(config).items())):
            cache = config.calendar_cache_path.with_name(f"calendario-{i}.ics")
            personal[person] = Calendar(lambda url=url: url, UrllibHttp(), cache)
    agenda = CalendarSkill(calendar, personal=personal)
    weather = None
    if config.weather.latitude is not None and config.weather.longitude is not None:
        weather = OpenMeteo(UrllibHttp(), config.weather.latitude, config.weather.longitude)

    video = build_video(config, simulated=simulated)
    shopping = ShoppingList(None if simulated else config.shopping_path)
    tasks = TaskList(None if simulated else config.state_dir / "pendientes.json")
    tasks_skill = TasksSkill(tasks)
    skills = {
        "music": MusicSkill(music, kids),
        "volume": VolumeSkill(volume, config.volume.step, kids),
        "kids": KidsSkill(kids),
        "timer": TimerSkill(timers),
        "clock": ClockSkill(),
        "weather": WeatherSkill(weather),
        "system": SystemSkill(),
        "kitchen": KitchenSkill(),
        "routine": RoutineSkill(timers, weather, music, config.routine.morning_music,
                                agenda=agenda.today_for_morning if agenda.has_any() else None,
                                pending=tasks_skill.morning, departure=Departure.from_config(config.routine)),
        "tasks": tasks_skill,
        "calendar": agenda,
        "shopping": ShoppingSkill(shopping),
        "display": ScreenSkill(),
        "voice": EnrollSkill(),
    }
    house = House(config.house.room, UrllibHttp(), config.house_rooms_path, main_url=config.house.main,
                  main_key_path=config.house_key_path)
    skills["house"] = HouseSkill(house)
    if not house.is_main:
        # Un cuarto: la lista del súper y el calendario son los de la principal.
        for domain in SHARED_DOMAINS:
            skills[domain] = RemoteSkill(house)
    player = None
    if video is not None:
        search, player = video
        skills["video"] = VideoSkill(search, player, music, kids)
    updater = None
    if config.update.check and not simulated:
        updater = Updater(UrllibHttp(), config.state_dir / "actualizacion", automatic=config.update.automatic)
        skills["update"] = UpdateSkill(updater)
    recipe = RecipeSession(None if simulated else config.recipe_path)
    recipe_skill = RecipeSkill(recipe, timers, shopping, video=skills.get("video"))
    skills["recipe"] = recipe_skill
    checks: list[Check] = []
    if not simulated:
        checks = [internet_check()]
        if config.music.provider == "spotify" or config.spotify.client_id:
            # Con YouTube de respaldo, Spotify sin conectar no es un problema: solo si se eligió.
            checks.append(spotify_check(config.spotify.client_id, config.spotify_token_path))
        if spotify_ready(config):
            checks.append(player_check(PlayerctlBackend(config.spotifast.mpris_player).now_playing,
                                       config.spotifast.mpris_player))
    set_language(config.voice.language)
    matcher = load_matcher(language=config.voice.language)
    video_active = (lambda: player.current is not None) if player is not None else None
    other = load_matcher(language=other_language(config.voice.language))
    assistant = Assistant(matcher, skills, timers, video_active=video_active, other=other,
                          bilingual=config.voice.bilingual)
    ai, ai_problem = build_ai(config, assistant)
    if ai is not None:
        ai.for_kids = kids.applies
    assistant.fallback = ai
    skills["system"].open_questions = ai is not None
    if ai is not None:  # recetas paso a paso: la IA las arma y ve la que está en curso
        recipe_skill.make = ai.recipe
        ai.start_recipe = recipe_skill.open
        ai.extra_context = recipe.summary
    return App(
        assistant, timers, matcher, now_playing, weather, player, checks, config, shopping, recipe, updater, ai, ai_problem,
        music, house, tasks, kids,
    )


def build_ai(config: Config, assistant: Assistant) -> tuple[AiFallback | None, str | None]:
    """El respaldo con IA si está activado en [ai]; si no puede arrancar, el porqué."""
    if not config.ai.enabled:
        return None, None
    try:
        chat = build_chat(config.ai, read_key(config.ai, config.ai_key_path))
    except AiSetupError as exc:
        return None, str(exc)
    usage = AiUsage(config.ai_usage_path, config.ai.monthly_budget_usd, config.ai.daily_questions)
    fallback = AiFallback(
        chat, usage, run_command=assistant.try_command, prices=prices_for(config.ai, chat.model), context=config.ai.context
    )
    return fallback, None


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
