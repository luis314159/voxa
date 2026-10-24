"""Estado de la pantalla de cocina (``voxa-ui``) y el canal local que la alimenta.

Protocolo: JSON, un mensaje por línea, sobre TCP en 127.0.0.1 (nunca hacia fuera del equipo).

- VOXA → pantalla: ``{"type": "state", ...}`` con la foto completa cada vez que algo cambia.
  Los temporizadores llevan su hora de fin y la música su posición con la hora en que se midió:
  la pantalla cuenta los segundos por su cuenta, sin un mensaje por segundo.
  También van el clima, los problemas («Sin internet») y si el micrófono está apagado.
- Pantalla → VOXA: ``{"type": "talk"}`` (tocar el anillo), ``{"type": "say", "text": "pausa"}``
  (botones de música: misma ruta que una orden hablada), ``{"type": "cancel_timer", "id": 3}``,
  ``{"type": "stop_alarm"}``, ``{"type": "mute", "on": true}`` y ``{"type": "diagnostics"}``,
  que VOXA contesta solo a esa pantalla con ``{"type": "diagnostics", ...}``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Awaitable, Callable, Protocol

from voxa.core.types import Response
from voxa.health import Health
from voxa.services.music_backend import BackendUnavailable, NowPlaying
from voxa.services.weather import Weather, WeatherUnavailable
from voxa.state.timers import TimerManager, display_label

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
DEFAULT_PORT = 8766
_MAX_SAY_CHARS = 200
_POSITION_DRIFT = 2.5  # segundos de diferencia que justifican reenviar la posición de la canción
_WEATHER_EVERY = 15 * 60
_WEATHER_RETRY = 2 * 60

NowPlayingSource = Callable[[], Awaitable[NowPlaying | None]]
WeatherSource = Callable[[], Awaitable[Weather]]


class Display:
    """Junta lo que la pantalla muestra y avisa a los suscriptores cuando cambia."""

    def __init__(
        self,
        timers: TimerManager,
        now_playing: NowPlayingSource | None = None,
        *,
        weather: WeatherSource | None = None,
        health: Health | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._timers = timers
        self._now_playing = now_playing
        self._weather = weather
        self.health = health
        self._clock = clock
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self.current_phase = "idle"
        self.heard: str | None = None
        self.answer: str | None = None
        self.exchange_at: float | None = None
        self.music: NowPlaying | None = None
        self._music_at: float | None = None
        self.weather: Weather | None = None
        self.muted = False
        self.video_title: str | None = None
        self.wake_word: str | None = None
        self._last: dict | None = None

    # --- TurnObserver (voxa.voice) ----------------------------------------
    def phase(self, name: str) -> None:
        if name != self.current_phase:
            self.current_phase = name
            self.publish()

    def exchange(self, heard: str, response: Response | None) -> None:
        self.heard = heard or None
        self.answer = response.speech if response else None
        self.exchange_at = self._clock()
        self.publish()

    # --- foto del estado ---------------------------------------------------
    def snapshot(self) -> dict:
        timers = [
            {
                "id": t.id,
                "label": display_label(t.label) if t.label else None,  # «el arroz» → «arroz»
                "total": t.duration,
                "ends_at": t.ends_at,
                "ringing": t.ringing_since is not None,
                "kind": t.kind,
            }
            for t in [*self._timers.ringing, *self._timers.active]
        ]
        return {
            "type": "state",
            "v": PROTOCOL_VERSION,
            "phase": self.current_phase,
            "heard": self.heard,
            "answer": self.answer,
            "exchange_at": self.exchange_at,
            "timers": timers,
            "music": self._music_snapshot(),
            "weather": self._weather_snapshot(),
            "muted": self.muted,
            "problems": [{"id": p.id, "text": p.text} for p in self.health.problems] if self.health else [],
            "video": {"title": self.video_title} if self.video_title else None,
            "wake_word": self.wake_word,
        }

    def _weather_snapshot(self) -> dict | None:
        w = self.weather
        if w is None:
            return None
        return {
            "temperature": round(w.temperature),
            "high": round(w.high),
            "low": round(w.low),
            "rain_probability": w.rain_probability,
            "code": w.code,
            "is_day": w.is_day,
            "description": w.description,
        }

    def _music_snapshot(self) -> dict | None:
        m = self.music
        if m is None:
            return None
        return {
            "title": m.title,
            "artist": m.artist,
            "album": m.album,
            "art_url": m.art_url,
            "playing": m.playing,
            "position": m.position,
            "position_at": self._music_at,
            "length": m.length,
        }

    def publish(self, *, force: bool = False) -> None:
        state = self.snapshot()
        if not force and not _differs(self._last, state):
            return
        self._last = state
        for queue in self._subscribers:
            _put_latest(queue, state)

    # --- suscriptores ------------------------------------------------------
    def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1)
        state = self.snapshot()
        queue.put_nowait(state)
        if self._last is None:
            self._last = state
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    @property
    def watched(self) -> bool:
        return bool(self._subscribers)

    # --- ciclo -------------------------------------------------------------
    async def refresh_music(self) -> None:
        if self._now_playing is None:
            return
        try:
            self.music = await self._now_playing()
        except BackendUnavailable:
            self.music = None
        self._music_at = self._clock()

    async def refresh_weather(self) -> bool:
        if self._weather is None:
            return True
        try:
            self.weather = await self._weather()
        except WeatherUnavailable as exc:
            log.info("Clima para la pantalla no disponible: %s", exc)
            return False  # se queda el último dato: el clima no cambia tan rápido
        return True

    async def run(self, music_every: float = 2.0) -> None:
        """Revisa temporizadores cada segundo y la música cada ``music_every`` s mientras alguien mira."""
        last_music = 0.0
        next_weather = 0.0
        while True:
            now = time.monotonic()
            if self.watched and now - last_music >= music_every:
                last_music = now
                await self.refresh_music()
            if self.watched and self._weather is not None and now >= next_weather:
                next_weather = now + (_WEATHER_EVERY if await self.refresh_weather() else _WEATHER_RETRY)
            self.publish()
            await asyncio.sleep(1.0)


def _differs(old: dict | None, new: dict) -> bool:
    """¿Vale la pena enviar ``new``? La posición de la canción avanza sola; solo cuenta si salta."""
    if old is None:
        return True
    old_music, new_music = old.get("music"), new.get("music")
    if (old_music is None) != (new_music is None):
        return True
    if old_music and new_music:
        volatile = ("position", "position_at")
        if {k: v for k, v in old_music.items() if k not in volatile} != {
            k: v for k, v in new_music.items() if k not in volatile
        }:
            return True
        expected = _expected_position(old_music, new_music["position_at"])
        if expected is not None and new_music["position"] is not None:
            if abs(expected - new_music["position"]) > _POSITION_DRIFT:
                return True
    return {k: v for k, v in old.items() if k != "music"} != {k: v for k, v in new.items() if k != "music"}


def _expected_position(music: dict, at: float | None) -> float | None:
    if music["position"] is None or music["position_at"] is None or at is None:
        return None
    return music["position"] + (at - music["position_at"] if music["playing"] else 0.0)


def _put_latest(queue: asyncio.Queue[dict], state: dict) -> None:
    """Una pantalla lenta solo necesita la foto más reciente: se descarta la anterior."""
    with contextlib.suppress(asyncio.QueueEmpty):
        queue.get_nowait()
    queue.put_nowait(state)


class DisplayCommands(Protocol):
    """Lo que la pantalla puede pedir (``voxa.service.Service``)."""

    async def talk(self) -> object: ...
    async def handle_text(self, text: str) -> object: ...
    async def cancel_timer(self, timer_id: int) -> None: ...
    async def stop_alarm(self) -> None: ...
    async def set_muted(self, on: bool) -> None: ...
    def diagnostics(self) -> dict: ...


class DisplayServer:
    def __init__(
        self,
        display: Display,
        commands: DisplayCommands,
        *,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
    ) -> None:
        self._display = display
        self._commands = commands
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task] = set()
        self._writers: set[asyncio.StreamWriter] = set()

    @property
    def port(self) -> int:
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._client, self._host, self._port)
        log.info("Pantalla: escuchando en %s:%d", self._host, self.port)

    async def close(self) -> None:
        if self._server:
            self._server.close()
            for writer in list(self._writers):  # wait_closed() espera a que se vayan las pantallas
                writer.close()
            await self._server.wait_closed()
        for task in list(self._tasks):
            task.cancel()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        queue = self._display.subscribe()
        sender = asyncio.create_task(self._send_states(queue, writer))
        self._writers.add(writer)
        try:
            while line := await reader.readline():
                self._dispatch(line, writer)
        except (ConnectionError, asyncio.LimitOverrunError, ValueError) as exc:
            log.info("Pantalla desconectada: %s", exc)
        finally:
            self._writers.discard(writer)
            self._display.unsubscribe(queue)
            sender.cancel()
            writer.close()
            with contextlib.suppress(ConnectionError, asyncio.CancelledError):
                await writer.wait_closed()

    async def _send_states(self, queue: asyncio.Queue[dict], writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(ConnectionError):
            while True:
                state = await queue.get()
                writer.write(json.dumps(state, ensure_ascii=False).encode() + b"\n")
                await writer.drain()

    @property
    def clients(self) -> int:
        return len(self._writers)

    def _dispatch(self, line: bytes, writer: asyncio.StreamWriter | None = None) -> None:
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("Mensaje inválido de la pantalla: %r", line[:80])
            return
        if not isinstance(message, dict):
            return
        action: Awaitable[object] | None = None
        kind, commands = message.get("type"), self._commands
        if kind == "talk":
            action = commands.talk()
        elif kind == "say" and isinstance(message.get("text"), str) and message["text"].strip():
            action = commands.handle_text(message["text"].strip()[:_MAX_SAY_CHARS])
        elif kind == "cancel_timer" and isinstance(message.get("id"), int):
            action = commands.cancel_timer(message["id"])
        elif kind == "stop_alarm":
            action = commands.stop_alarm()
        elif kind == "mute" and isinstance(message.get("on"), bool):
            action = commands.set_muted(message["on"])
        elif kind == "diagnostics" and writer is not None:
            report = {"type": "diagnostics", "v": PROTOCOL_VERSION, **commands.diagnostics()}
            writer.write(json.dumps(report, ensure_ascii=False).encode() + b"\n")
        else:
            log.debug("Mensaje de la pantalla ignorado: %s", message)
        if action is not None:
            task = asyncio.ensure_future(action)
            self._tasks.add(task)
            task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            log.error("Falló una orden de la pantalla", exc_info=task.exception())
