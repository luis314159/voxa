"""``voxa revisar``: revisa la instalación en la PC de la cocina y dice qué falta y cómo arreglarlo.

Solo lee: no instala, no cambia la configuración y no gasta (la IA no se llama; para eso está
``voxa ia-probar``). Pensado para correrse después de ``scripts/install.sh`` y cada vez que algo
no funcione.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from voxa.config import Config, read_config
from voxa.health import Check, internet_check
from voxa.services.process import CommandNotFound, CommandRunner, run_command

OK, WARN, FAIL, SKIP = "ok", "aviso", "falla", "omitido"
_MARKS = {OK: "\033[32m✓\033[0m", WARN: "\033[33m⚠\033[0m", FAIL: "\033[31m✖\033[0m", SKIP: "\033[2m·\033[0m"}
_PLAIN_MARKS = {OK: "✓", WARN: "⚠", FAIL: "✖", SKIP: "·"}


@dataclass(frozen=True)
class Finding:
    group: str
    name: str
    status: str
    detail: str = ""
    fix: str = ""


@dataclass
class Tools:
    """Lo que la revisión toca del sistema; las pruebas lo cambian por imitaciones."""

    which: Callable[[str], str | None] = shutil.which
    run: CommandRunner = run_command
    has_module: Callable[[str], bool] = lambda name: importlib.util.find_spec(name) is not None
    linux: bool = sys.platform == "linux"
    internet: Check = field(default_factory=internet_check)


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --- cada grupo devuelve sus hallazgos ------------------------------------------------
def check_config(path: Path) -> tuple[Config, list[Finding]]:
    group = "Configuración"
    if not path.exists():
        return Config(), [Finding(group, "config.toml", WARN, f"No existe {path}: se usan los valores por defecto.",
                                  f"cp config/default.toml {path}")]
    try:
        config, warnings = read_config(path)
    except Exception as exc:  # noqa: BLE001 - TOML mal escrito
        return Config(), [Finding(group, "config.toml", FAIL, f"No se puede leer: {exc}", f"Revisa {path}")]
    findings = [Finding(group, "config.toml", OK, str(path))]
    findings += [Finding(group, "Errata", WARN, w, "Compara con config/default.toml") for w in warnings]
    return config, findings


def check_voice(config: Config, tools: Tools) -> list[Finding]:
    group, voice, out = "Voz", config.voice, []
    missing = [m for m in ("numpy", "sounddevice", "vosk", "faster_whisper", "piper", "onnxruntime") if not tools.has_module(m)]
    if missing:
        out.append(Finding(group, "Paquetes de audio", FAIL, f"Faltan: {', '.join(missing)}",
                           "pipx install --force 'RUTA/DE/VOXA[audio,ia]'  (o bash scripts/install.sh)"))
    else:
        out.append(Finding(group, "Paquetes de audio", OK))
    if voice.stt in ("vosk", "hibrido"):
        model = _path(voice.vosk_model) if voice.vosk_model else None
        if model is None or not model.is_dir():
            out.append(Finding(group, "Modelo de Vosk", FAIL, str(model or "sin configurar"), "bash scripts/install.sh"))
        else:
            out.append(Finding(group, "Modelo de Vosk", OK, model.name))
    if voice.stt in ("whisper", "hibrido"):
        cache = Path(os.environ.get("HF_HUB_CACHE") or Path.home() / ".cache/huggingface/hub")
        name = f"models--Systran--faster-whisper-{voice.whisper_model}"
        if (cache / name).exists():
            out.append(Finding(group, "Whisper", OK, voice.whisper_model))
        else:
            out.append(Finding(group, "Whisper", WARN, f"«{voice.whisper_model}» se descargará la primera vez (necesita internet).",
                               "voxa escuchar ALGUNA_GRABACION.wav  (lo descarga una vez)"))
    piper = _path(voice.piper_voice) if voice.piper_voice else None
    if piper is None or not piper.exists():
        out.append(Finding(group, "Voz de Piper", FAIL, str(piper or "sin configurar"), "bash scripts/install.sh"))
    elif not Path(f"{piper}.json").exists():
        out.append(Finding(group, "Voz de Piper", FAIL, f"Falta {piper.name}.json junto al modelo", "bash scripts/install.sh"))
    else:
        out.append(Finding(group, "Voz de Piper", OK, piper.stem))
    return out


def check_devices(config: Config, tools: Tools) -> list[Finding]:
    group = "Audio"
    if not tools.has_module("sounddevice"):
        return [Finding(group, "Dispositivos", SKIP, "sin sounddevice")]
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception as exc:  # noqa: BLE001 - PortAudio sin dispositivos o sin servidor de audio
        return [Finding(group, "Dispositivos", FAIL, str(exc), "¿Corre PipeWire? systemctl --user status pipewire")]
    out = []
    for kind, wanted, key in (("Micrófono", config.voice.input_device, "max_input_channels"),
                              ("Salida", config.voice.output_device, "max_output_channels")):
        try:
            if wanted:
                info = sd.query_devices(int(wanted) if wanted.isdigit() else wanted, "input" if key.startswith("max_in") else "output")
            else:
                index = sd.default.device[0 if key.startswith("max_in") else 1]
                info = devices[index] if index is not None and index >= 0 else None
        except (ValueError, IndexError, sd.PortAudioError) as exc:
            out.append(Finding(group, kind, FAIL, f"«{wanted}»: {exc}", "python -m sounddevice  ← lista los nombres"))
            continue
        if not info or not info.get(key):
            out.append(Finding(group, kind, FAIL, "No hay ninguno predeterminado", "Revisa la configuración de sonido"))
        else:
            out.append(Finding(group, kind, OK, str(info["name"])))
    return out


async def check_bluetooth(tools: Tools) -> list[Finding]:
    group = "Audio"
    if not tools.linux:
        return [Finding(group, "Bocina Bluetooth", SKIP, "solo en Linux")]
    try:
        result = await tools.run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])
    except (CommandNotFound, asyncio.TimeoutError):
        return [Finding(group, "Bocina Bluetooth", WARN, "No pude preguntar a PipeWire (wpctl)")]
    if "bluez" not in result.stdout:
        return [Finding(group, "Bocina Bluetooth", WARN, "La salida predeterminada no es la bocina Bluetooth",
                        "Conéctala y elígela como salida (o: wpctl status / wpctl set-default ID)")]
    profile = "a2dp" in result.stdout.lower()
    return [Finding(group, "Bocina Bluetooth", OK if profile else WARN,
                    "en alta calidad (A2DP)" if profile else "conectada, pero no en A2DP",
                    "" if profile else "bash scripts/install.sh  (fija el perfil A2DP)")]


def check_wake(config: Config, tools: Tools) -> list[Finding]:
    group = "«Hey Voxa»"
    if not config.wake.enabled:
        return [Finding(group, "Activación por voz", SKIP, "apagada en [wake]")]
    try:
        from voxa.audio.wakeword import DEFAULT_MODEL, FEATURE_MODEL_SHA256
    except ImportError as exc:
        return [Finding(group, "Detector", FAIL, f"Falta un paquete: {exc.name}", "bash scripts/install.sh")]

    out = []
    folder = _path(config.wake.feature_dir)
    for name, expected in FEATURE_MODEL_SHA256.items():
        path = folder / name
        if not path.exists():
            out.append(Finding(group, name, FAIL, f"Falta en {folder}", "bash scripts/install.sh"))
        elif _sha256(path) != expected:
            out.append(Finding(group, name, FAIL, "La huella no coincide (archivo dañado o alterado)",
                               f"rm {path} && bash scripts/install.sh"))
        else:
            out.append(Finding(group, name, OK))
    model = _path(config.wake.model) if config.wake.model else DEFAULT_MODEL
    out.append(Finding(group, "Modelo «Hey Voxa»", OK if model.exists() else FAIL, model.name,
                       "" if model.exists() else "Revisa model en [wake]"))
    if config.verifier_path.exists():
        out.append(Finding(group, "Verificador familiar", OK, str(config.verifier_path)))
    else:
        out.append(Finding(group, "Verificador familiar", WARN, "Todavía no (opcional, recomendado)",
                           "voxa grabar-activacion --persona NOMBRE  y luego  voxa entrenar-verificador"))
    return out


async def check_music(config: Config, tools: Tools) -> list[Finding]:
    group, out = "Música", []
    if not config.spotify.client_id:
        out.append(Finding(group, "Spotify", FAIL, "Falta el Client ID de tu app de Spotify", "Celular → Ajustes → Spotify"))
    elif not config.spotify_token_path.exists():
        out.append(Finding(group, "Spotify", FAIL, "Falta autorizar a VOXA", "Celular → Ajustes → Spotify → Conectar (o voxa spotify-login)"))
    else:
        out.append(Finding(group, "Spotify", OK, "autorizado"))
    if not tools.linux:
        return out + [Finding(group, "Spotifast", SKIP, "solo en Linux")]
    if tools.which("playerctl") is None:
        return out + [Finding(group, "playerctl", FAIL, "No está instalado", "sudo apt install playerctl")]
    player = config.spotifast.mpris_player
    try:
        result = await tools.run(["playerctl", "--list-all"])
        players = result.stdout.split()
    except (CommandNotFound, asyncio.TimeoutError):
        players = []
    if any(p == player or p.startswith(f"{player}.") for p in players):
        out.append(Finding(group, "Spotifast", OK, f"responde como «{player}»"))
    else:
        seen = f" (hay: {', '.join(players)})" if players else ""
        out.append(Finding(group, "Spotifast", FAIL, f"No encuentro el reproductor «{player}»{seen}",
                           "Abre Spotifast; si se llama distinto, cambia mpris_player en [spotifast]"))
    return out


def check_video(config: Config, tools: Tools) -> list[Finding]:
    group = "Video"
    if not config.video.enabled:
        return [Finding(group, "Videos", SKIP, "apagados en [video]")]
    out = []
    for name, command, fix in (
        ("yt-dlp", config.video.ytdlp, "pipx install 'yt-dlp[default]'"),
        ("mpv", config.video.mpv[0] if config.video.mpv else "mpv", "sudo apt install mpv"),
        ("deno", "deno", "pipx install deno  (YouTube ya lo exige)"),
    ):
        found = tools.which(command)
        out.append(Finding(group, name, OK if found else FAIL, found or "No está instalado", "" if found else fix))
    return out


async def check_network(config: Config, tools: Tools) -> list[Finding]:
    group = "Red"
    problem = await tools.internet()
    out = [Finding(group, "Internet", FAIL if problem else OK, problem.detail if problem else "")]
    w = config.weather
    if w.latitude is None or w.longitude is None:
        out.append(Finding(group, "Clima", WARN, "Sin ubicación", "Pon latitude y longitude en [weather]"))
    elif not problem:
        from voxa.services.http import UrllibHttp
        from voxa.services.weather import OpenMeteo, WeatherUnavailable

        try:
            weather = await OpenMeteo(UrllibHttp(), w.latitude, w.longitude).today()
            out.append(Finding(group, "Clima", OK, f"{weather.description}, {round(weather.temperature)} °C"))
        except WeatherUnavailable as exc:
            out.append(Finding(group, "Clima", WARN, str(exc)))
    return out


def check_ai(config: Config, tools: Tools) -> list[Finding]:
    from voxa.services.ai import AiSetupError, build_chat, read_key

    group = "IA"
    if not config.ai.enabled:
        return [Finding(group, "Respaldo con IA", SKIP, "apagado (opcional): voxa ia-clave y enabled = true en [ai]")]
    try:
        chat = build_chat(config.ai, read_key(config.ai, config.ai_key_path))
    except AiSetupError as exc:
        return [Finding(group, "Respaldo con IA", FAIL, str(exc), "voxa ia-clave  /  revisa [ai]")]
    return [Finding(group, "Respaldo con IA", OK, f"{chat.name} (pruébala: voxa ia-probar)")]


def check_calendar(config: Config) -> list[Finding]:
    from voxa.settings import read_secret

    group = "Calendario"
    if not config.calendar.enabled:
        return [Finding(group, "Calendario de la familia", SKIP, "apagado (opcional): Ajustes → Calendario en el celular")]
    if read_secret(config.calendar_url_path) is None:
        return [Finding(group, "Calendario de la familia", FAIL, "falta la dirección iCal", "Ajustes → Calendario en el celular")]
    return [Finding(group, "Calendario de la familia", OK, "dirección guardada (pregunta «¿qué tengo hoy?»)")]


def check_telegram(config: Config) -> list[Finding]:
    from voxa.telegram import Chats, read_token

    group = "Telegram"
    if not config.telegram.enabled:
        return [Finding(group, "Lista desde Telegram", SKIP, "apagado (opcional): voxa telegram-vincular y enabled = true en [telegram]")]
    if read_token(config.telegram_token_path) is None:
        return [Finding(group, "Lista desde Telegram", FAIL, "falta el token del bot", "voxa telegram-vincular")]
    chats = Chats(config.telegram_chats_path, config.telegram_code_path).all()
    if not chats:
        return [Finding(group, "Lista desde Telegram", WARN, "ningún chat vinculado: el bot no le contesta a nadie",
                        "voxa telegram-vincular")]
    return [Finding(group, "Lista desde Telegram", OK, "chats: " + ", ".join(chats.values()))]


async def check_services(config: Config, tools: Tools) -> list[Finding]:
    group = "Servicios"
    if not tools.linux:
        return [Finding(group, "systemd", SKIP, "solo en Linux")]
    out = []
    for unit, why in (("voxa.service", "VOXA"), ("voxa-ui.service", "la pantalla")):
        try:
            result = await tools.run(["systemctl", "--user", "is-active", unit])
            state = result.stdout.strip() or "desconocido"
        except (CommandNotFound, asyncio.TimeoutError):
            state = "desconocido"
        if state == "active":
            out.append(Finding(group, unit, OK, "en marcha"))
        else:
            out.append(Finding(group, unit, FAIL, f"{why}: {state}",
                               f"systemctl --user restart {unit}  ·  journalctl --user -u {unit.split('.')[0]} -n 50"))
    if config.video.enabled:
        try:
            result = await tools.run(["systemctl", "--user", "is-enabled", "voxa-ytdlp.timer"])
            enabled = result.stdout.strip() == "enabled"
        except (CommandNotFound, asyncio.TimeoutError):
            enabled = False
        out.append(Finding(group, "voxa-ytdlp.timer", OK if enabled else WARN,
                           "actualiza yt-dlp cada semana" if enabled else "yt-dlp no se actualizará solo",
                           "" if enabled else "systemctl --user enable --now voxa-ytdlp.timer"))
    return out


async def run_checkup(path: Path, tools: Tools | None = None) -> list[Finding]:
    tools = tools or Tools()
    config, findings = check_config(path)
    findings += check_voice(config, tools)
    findings += check_devices(config, tools)
    steps: list[Callable[[], Awaitable[list[Finding]]] | Callable[[], list[Finding]]] = [
        lambda: check_bluetooth(tools),
        lambda: check_wake(config, tools),
        lambda: check_music(config, tools),
        lambda: check_video(config, tools),
        lambda: check_network(config, tools),
        lambda: check_ai(config, tools),
        lambda: check_telegram(config),
        lambda: check_calendar(config),
        lambda: check_services(config, tools),
    ]
    for step in steps:
        result = step()
        findings += await result if asyncio.iscoroutine(result) else result
    return findings


def render(findings: list[Finding], *, color: bool = True) -> str:
    marks = _MARKS if color else _PLAIN_MARKS
    lines, group = [], None
    for f in findings:
        if f.group != group:
            group = f.group
            lines.append(f"\n{group}")
        detail = f" — {f.detail}" if f.detail else ""
        lines.append(f"  {marks[f.status]} {f.name}{detail}")
        if f.fix and f.status in (WARN, FAIL):
            lines.append(f"      → {f.fix}")
    fails = sum(f.status == FAIL for f in findings)
    warns = sum(f.status == WARN for f in findings)
    if fails or warns:
        lines.append(f"\n{fails} por arreglar, {warns} avisos.")
    else:
        lines.append("\nTodo en orden.")
    return "\n".join(lines).lstrip("\n")
