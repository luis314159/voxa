"""VOXA en marcha: temporizadores, pantalla y, si hay modelos cargados, voz.

Lo comparten ``voxa texto``, ``voxa voz`` y ``voxa servicio``; cambia solo de dónde llegan las órdenes
(teclado, botón de la pantalla y, en la Fase 3, «Hey Voxa»).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, AsyncIterator

from voxa import diagnostics
from voxa.app import App
from voxa.core.types import Response
from voxa.display import Display, DisplayServer
from voxa.health import Health, Problem
from voxa.skills.timers import ring_phrase
from voxa.state.timers import Timer

if TYPE_CHECKING:
    from voxa.audio.devices import Microphone
    from voxa.voice import TurnResult, VoiceSession

log = logging.getLogger(__name__)

MUTE_ACTION = "mic.mute"
_MIC_RETRY_SECONDS = 30.0
# Lo que se ve encima del video mientras VOXA escucha o piensa (el video tapa la pantalla).
_VIDEO_OSD = {"listening": "🎙 Te escucho…", "thinking": "Un momento…"}


class Service:
    def __init__(self, app: App, display: Display, health: Health | None = None) -> None:
        self.app = app
        self.display = display
        self.health = health or display.health or Health(app.health_checks)
        display.health = self.health
        self.health.on_change = display.publish
        self.session: VoiceSession | None = None
        self.mic: Microphone | None = None
        self.muted = False
        self._turn = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        if app.video is not None:
            app.video.on_end = self._video_ended

    @classmethod
    def create(cls, app: App) -> Service:
        health = Health(app.health_checks)
        weather = app.weather.today if app.weather else None
        return cls(app, Display(app.timers, app.now_playing, weather=weather, health=health), health)

    # --- voz ------------------------------------------------------------------
    def attach_voice(self, session: VoiceSession, mic: Microphone) -> None:
        session.observer = self
        self.session, self.mic = session, mic
        if not self.muted:
            self._open_microphone()

    def _open_microphone(self) -> bool:
        if self.mic is None:
            return False
        try:
            self.mic.open()
        except Exception as exc:  # noqa: BLE001 - PortAudio: sin micrófono, ocupado, sin permisos…
            self.health.report(Problem("microfono", "No encuentro el micrófono", str(exc)))
            return False
        self.health.clear("microfono")
        return True

    async def talk(self) -> TurnResult | None:
        """Un turno de voz. Si ya hay uno en curso (dos toques seguidos), no hace nada.

        Con el micrófono apagado, tocar el anillo lo vuelve a encender y escucha de una vez.
        """
        if self.session is None or self.mic is None or self._turn.locked():
            return None
        async with self._turn:
            if self.muted:
                await self.set_muted(False, acknowledge=False)
            if not self.mic.is_open and not self._open_microphone():
                await self.session.say(Response("No encuentro el micrófono.", sound="error"))
                return None
            result = await self.session.turn(self.mic)
        await self._apply(result.response)
        return result

    async def handle_text(self, text: str) -> Response:
        """Orden escrita o botón de la pantalla: misma ruta que una hablada, con respuesta en voz si la hay."""
        response = await self.app.assistant.handle_text(text)
        self.exchange(text, response)
        if self.session is not None:
            await self.session.say(response)
        await self._apply(response)
        return response

    async def _apply(self, response: Response | None) -> None:
        if response is not None and response.action == MUTE_ACTION:
            await self.set_muted(True, acknowledge=False)  # la respuesta ya lo dijo

    async def set_muted(self, on: bool, *, acknowledge: bool = True) -> None:
        """Modo privado: suelta el micrófono de verdad (no solo deja de hacerle caso)."""
        if on == self.muted:
            return
        self.muted = on
        if self.mic is not None:
            if on:
                self.mic.close()
            else:
                self._open_microphone()
        self.display.muted = on
        self.display.publish()
        if acknowledge:
            await self._acknowledge("cancel" if on else "ok")

    # --- TurnObserver: la pantalla y, si hay un video encima, su OSD -------------
    def phase(self, name: str) -> None:
        self.display.phase(name)
        if self._video_showing() and name in _VIDEO_OSD:
            self._spawn(self.app.video.show_text(_VIDEO_OSD[name], 4.0))

    def exchange(self, heard: str, response: Response | None) -> None:
        self.display.exchange(heard, response)
        if self._video_showing() and response is not None and response.speech:
            self._spawn(self.app.video.show_text(response.speech, 3.0))
        self._sync_video()

    def _video_showing(self) -> bool:
        return self.app.video is not None and self.app.video.current is not None

    def _sync_video(self) -> None:
        current = self.app.video.current if self.app.video else None
        title = current.title if current else None
        if title != self.display.video_title:
            self.display.video_title = title
            self.display.publish()

    def _video_ended(self) -> None:
        self._sync_video()

    # --- botones de la pantalla ----------------------------------------------
    async def cancel_timer(self, timer_id: int) -> None:
        timer = next((t for t in self.app.timers.active if t.id == timer_id), None)
        if timer is None:
            return
        self.app.timers.cancel(timer)
        self.display.publish()
        await self._acknowledge("cancel")

    async def stop_alarm(self) -> None:
        if self.app.timers.stop_ringing():
            self.display.publish()
            await self._acknowledge("ok")

    def diagnostics(self) -> dict:
        return diagnostics.collect(self)

    async def _acknowledge(self, sound: str) -> None:
        if self.session is not None:
            await self.session.say(Response(sound=sound))

    def on_ring(self, timer: Timer) -> None:
        self.display.publish()
        if self.session is not None:
            self._spawn(self.session.announce(ring_phrase(timer)))
        if self._video_showing():
            self._spawn(self.app.video.show_text(f"⏰ {ring_phrase(timer)}", 8.0))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _keep_microphone(self) -> None:
        """Si el micrófono no abrió (USB desconectado, PipeWire reiniciando), lo reintenta solo."""
        while True:
            await asyncio.sleep(_MIC_RETRY_SECONDS)
            if self.mic is not None and not self.muted and not self.mic.is_open and not self._turn.locked():
                self._open_microphone()

    @contextlib.asynccontextmanager
    async def running(self, port: int | None) -> AsyncIterator[Service]:
        """Arranca temporizadores, pantalla y su canal (si ``port`` no es None); los detiene al salir."""
        background = [
            asyncio.create_task(self.app.timers.run()),
            asyncio.create_task(self.display.run()),
            asyncio.create_task(self.health.run()),
            asyncio.create_task(self._keep_microphone()),
        ]
        server = None
        if port is not None:
            server = DisplayServer(self.display, self, port=port)
            try:
                await server.start()
            except OSError as exc:
                log.warning("No pude abrir el canal de la pantalla en el puerto %d: %s", port, exc)
                server = None
        try:
            yield self
        finally:
            if server:
                await server.close()
            if self.app.video is not None:
                await self.app.video.close()
            if self.mic is not None:
                self.mic.close()
            for task in [*background, *self._tasks]:
                task.cancel()
            for task in background:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
