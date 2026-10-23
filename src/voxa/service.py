"""VOXA en marcha: temporizadores, pantalla y, si hay modelos cargados, voz.

Lo comparten ``voxa texto``, ``voxa voz`` y ``voxa servicio``; cambia solo de dónde llegan las órdenes
(teclado, botón de la pantalla y, en la Fase 3, «Hey Voxa»).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, AsyncIterator

from voxa.app import App
from voxa.core.types import Response
from voxa.display import Display, DisplayServer
from voxa.skills.timers import ring_phrase
from voxa.state.timers import Timer

if TYPE_CHECKING:
    from voxa.audio.devices import Microphone
    from voxa.voice import TurnResult, VoiceSession

log = logging.getLogger(__name__)


class Service:
    def __init__(self, app: App, display: Display) -> None:
        self.app = app
        self.display = display
        self.session: VoiceSession | None = None
        self.mic: Microphone | None = None
        self._turn = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    def attach_voice(self, session: VoiceSession, mic: Microphone) -> None:
        session.observer = self.display
        self.session, self.mic = session, mic

    async def talk(self) -> TurnResult | None:
        """Un turno de voz. Si ya hay uno en curso (dos toques seguidos), no hace nada."""
        if self.session is None or self.mic is None or self._turn.locked():
            return None
        async with self._turn:
            return await self.session.turn(self.mic)

    async def handle_text(self, text: str) -> Response:
        """Orden escrita o botón de la pantalla: misma ruta que una hablada, con respuesta en voz si la hay."""
        response = await self.app.assistant.handle_text(text)
        self.display.exchange(text, response)
        if self.session is not None:
            await self.session.say(response)
        return response

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

    async def _acknowledge(self, sound: str) -> None:
        if self.session is not None:
            await self.session.say(Response(sound=sound))

    def on_ring(self, timer: Timer) -> None:
        self.display.publish()
        if self.session is not None:
            self._spawn(self.session.announce(ring_phrase(timer)))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @contextlib.asynccontextmanager
    async def running(self, port: int | None) -> AsyncIterator[Service]:
        """Arranca temporizadores, pantalla y su canal (si ``port`` no es None); los detiene al salir."""
        background = [asyncio.create_task(self.app.timers.run()), asyncio.create_task(self.display.run())]
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
            for task in [*background, *self._tasks]:
                task.cancel()
            for task in background:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
