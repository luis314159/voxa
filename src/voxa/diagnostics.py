"""La pantalla de diagnóstico (mantener presionado el reloj): cómo está VOXA por dentro.

Pensada para revisar la cocina sin teclado: versión, voz, micrófono, música, red y los últimos
avisos del registro. No incluye tokens, Client ID ni nada de lo que se dijo.
"""

from __future__ import annotations

import collections
import logging
import platform
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import voxa

if TYPE_CHECKING:
    from voxa.service import Service

_STARTED = time.monotonic()


class RecentLog(logging.Handler):
    """Guarda los últimos avisos y errores para mostrarlos en la pantalla."""

    def __init__(self, capacity: int = 30) -> None:
        super().__init__(logging.WARNING)
        self._lines: collections.deque[str] = collections.deque(maxlen=capacity)
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record).splitlines()[0]
        except Exception:  # noqa: BLE001 - el registro nunca debe tumbar a VOXA
            return
        mark = "✖" if record.levelno >= logging.ERROR else "⚠"
        self._lines.append(f"{mark} {line[:160]}")

    def lines(self) -> list[str]:
        return list(self._lines)


RECENT = RecentLog()


def install() -> None:
    root = logging.getLogger()
    if RECENT not in root.handlers:
        root.addHandler(RECENT)


def _uptime(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def _memory() -> str | None:
    """Memoria residente del proceso (Linux)."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return f"{int(line.split()[1]) // 1024} MB"
    except OSError:
        pass
    return None


def _local_ip() -> str | None:
    """IP de la PC en la red de la casa (un socket UDP «conectado» no envía nada)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # dirección de documentación: nunca se usa de verdad
            return s.getsockname()[0]
        except OSError:
            return None


def _program(command: str) -> str:
    found = shutil.which(command)
    return found or "no instalado"


def collect(service: Service) -> dict:
    app, display = service.app, service.display
    config = app.config
    voice = config.voice
    problems = service.health.problems
    has_problem = {p.id for p in problems}

    if service.session is None:
        mic = "sin voz cargada"
    elif service.muted:
        mic = "apagado (modo privado)"
    elif service.mic is not None and service.mic.is_open:
        mic = "abierto"
    else:
        mic = "no disponible"
    if service.wake is None:
        wake = "desactivado" if not config.wake.enabled else "no disponible"
    else:
        times = "1 vez" if service.wake_count == 1 else f"{service.wake_count} veces"
        family = " · con verificador" if service.wake.verifier is not None else ""
        wake = f"umbral {service.wake.threshold:.2f} · {times}{family}"
    music = display.music
    if app.ai is not None:
        ai = f"{app.ai.chat.name} · {app.ai.usage.summary()}"
    else:
        ai = app.ai_problem or ("desactivada" if not config.ai.enabled else "no disponible")
    sections = [
        (
            "VOXA",
            [
                ("Versión", voxa.__version__),
                ("Encendida hace", _uptime(time.monotonic() - _STARTED)),
                ("Memoria", _memory() or "—"),
                ("Python", platform.python_version()),
                ("Sistema", platform.platform(terse=True) if sys.platform != "linux" else _os_name()),
            ],
        ),
        (
            "Voz",
            [
                ("Reconocimiento", f"{voice.stt} · Whisper {voice.whisper_model}"),
                ("Voz", Path(voice.piper_voice).stem or "—"),
                ("Micrófono", mic),
                ("«Hey Voxa»", wake),
                ("Entrada", voice.input_device or "predeterminada"),
                ("Salida", voice.output_device or "predeterminada"),
            ],
        ),
        (
            "Música y video",
            [
                ("Spotify", "falta conectar" if "spotify" in has_problem else "conectado"),
                ("Reproductor", config.spotifast.mpris_player + (" · no responde" if "musica" in has_problem else "")),
                ("Sonando", f"{music.title} — {music.artist}" if music and music.artist else (music.title if music else "nada")),
                ("yt-dlp", _program(config.video.ytdlp)),
                ("mpv", _program(config.video.mpv[0]) if config.video.mpv else "—"),
            ],
        ),
        (
            "Red",
            [
                ("Internet", "sin conexión" if "internet" in has_problem else "bien"),
                ("IP local", _local_ip() or "—"),
                ("Clima", _weather_place(config) or "sin ubicación"),
                ("IA", ai),
                ("Pantalla", f"puerto {config.display.port}"),
            ],
        ),
    ]
    return {
        "sections": [{"title": title, "items": [list(item) for item in items]} for title, items in sections],
        "problems": [{"id": p.id, "text": p.text, "detail": p.detail} for p in problems],
        "log": RECENT.lines()[-12:],
    }


def _os_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return platform.platform(terse=True)


def _weather_place(config) -> str | None:
    w = config.weather
    if w.latitude is None or w.longitude is None:
        return None
    return f"{w.latitude:.1f}, {w.longitude:.1f}"  # aproximada: la pantalla puede salir en fotos
