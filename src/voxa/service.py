"""VOXA en marcha: temporizadores, pantalla y, si hay modelos cargados, voz.

Lo comparten ``voxa texto``, ``voxa voz`` y ``voxa servicio``; cambia solo de dónde llegan las órdenes
(teclado, botón de la pantalla y, en la Fase 3, «Hey Voxa»).
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import time
from typing import TYPE_CHECKING, AsyncIterable, AsyncIterator

from voxa import diagnostics
from voxa.app import App
from voxa.core.assistant import STOPS_ALARM
from voxa.core.types import Response
from voxa.display import Display, DisplayServer
from voxa.health import Health, Problem
from voxa.services.http import UrllibHttp
from voxa.skills.enroll import ENROLL_ACTION
from voxa.skills.timers import ring_phrase
from voxa.state.timers import Timer
from voxa.telegram import Chats, ShoppingBot, TelegramApi, read_token
from voxa.web import WebServer, load_or_create_key

if TYPE_CHECKING:
    from voxa.audio.devices import Microphone
    from voxa.audio.wakeword import WakeWordDetector
    from voxa.voice import TurnResult, VoiceSession

log = logging.getLogger(__name__)

MUTE_ACTION = "mic.mute"
PHOTO_ACTIONS = {"display.photo": True, "display.info": False}
PHONE_SECONDS = 120.0
_MIC_RETRY_SECONDS = 30.0
# Lo que se ve encima del video mientras VOXA escucha o piensa (el video tapa la pantalla).
_VIDEO_OSD = {"listening": "🎙 Te escucho…", "thinking": "Un momento…"}
WAKE_PHRASE = "Hey Voxa"


def _alarm_endpoint():
    """Durante la alarma solo interesan frases cortas («para», «ya, gracias»)."""
    from voxa.audio.endpoint import EndpointConfig

    return EndpointConfig(end_silence_ms=480, max_ms=2400, no_speech_timeout_ms=30000)


class Service:
    def __init__(self, app: App, display: Display, health: Health | None = None) -> None:
        self.app = app
        self.display = display
        self.health = health or display.health or Health(app.health_checks)
        display.health = self.health
        self.health.on_change = display.publish
        system = app.assistant.skill("system")
        if system is not None and hasattr(system, "problems"):
            system.problems = lambda: self.health.problems  # «¿estás bien?» dice qué falla
        enroll = app.assistant.skill("voice")
        if enroll is not None and hasattr(enroll, "ready"):
            enroll.ready = lambda: self.session is not None and self.mic is not None and self.wake is not None
        display.shopping = app.shopping.items  # la pantalla ve la lista tal cual (se republica tras cada orden)
        display.recipe = app.recipe.snapshot
        recipe = app.assistant.skill("recipe")
        if recipe is not None and hasattr(recipe, "on_wait"):
            recipe.on_wait = self._say_meanwhile
        if app.ai_problem:
            self.health.report(Problem("ia", "La IA no está lista", app.ai_problem))
        if app.ai is not None:
            app.ai.on_setup_error = lambda detail: self.health.report(Problem("ia", "La IA no funciona", detail))
            app.ai.on_ok = lambda: self.health.clear("ia")
        self.session: VoiceSession | None = None
        self.mic: Microphone | None = None
        self.muted = False
        self.wake: WakeWordDetector | None = None
        self.wake_count = 0
        self._turn = asyncio.Lock()
        self.web: WebServer | None = None
        self.enrolling: str | None = None
        """Quién está grabando su voz ahora («aprende mi voz»)."""
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
        if self.app.ai is not None:
            self.app.ai.speak = self._speak_as_it_arrives
        if not self.muted:
            self._open_microphone()
        self._sync_wake()

    def attach_wake(self, detector: WakeWordDetector) -> None:
        self.wake = detector
        self._sync_wake()

    def _sync_wake(self) -> None:
        listening = self.wake is not None and self.session is not None and not self.muted
        phrase = WAKE_PHRASE if listening else None
        if phrase != self.display.wake_word:
            self.display.wake_word = phrase
            self.display.publish()

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

    async def talk(self, *, after_wake: bool = False) -> TurnResult | None:
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
            result = await self.session.turn(self.mic, after_wake=after_wake)
        await self._apply(result.response)
        return result

    async def handle_text(self, text: str, *, speak: bool = True) -> Response:
        """Orden escrita o botón de la pantalla: misma ruta que una hablada, con respuesta en voz si la hay.

        ``speak=False``: desde el celular, sin hablar en la cocina (solo un sonido si no hay texto).
        """
        response = await self.app.assistant.handle_text(text)
        self.exchange(text, response)
        if self.session is not None and speak:
            await self.session.say(response)
        await self._apply(response)
        return response

    async def _speak_as_it_arrives(self, chunks: AsyncIterable[str], heard: str) -> None:
        """La respuesta de la IA por trozos: se dice y se va mostrando en la pantalla según llega."""
        said: list[str] = []

        async def shown() -> AsyncIterator[str]:
            async for chunk in chunks:
                said.append(chunk)
                self.display.exchange(heard, Response(" ".join(said)))
                yield chunk

        if self.session is not None:
            await self.session.say_stream(shown())

    def _kitchen_idle(self) -> bool:
        """Nadie usa la cocina: sin temporizadores, sin turno de voz y sin video."""
        timers = self.app.timers
        return not timers.active and not timers.ringing and not self._turn.locked() and not self._video_showing()

    async def _say_meanwhile(self, text: str) -> None:
        """Algo que decir mientras se espera a la IA («Déjame ver la receta…»); luego sigue «pensando»."""
        if self.session is not None:
            await self.session.say(Response(text))
        self.phase("thinking")

    async def _apply(self, response: Response | None) -> None:
        if response is not None and response.action == MUTE_ACTION:
            await self.set_muted(True, acknowledge=False)  # la respuesta ya lo dijo
        if response is not None and response.action in PHOTO_ACTIONS:
            await self.set_photo(PHOTO_ACTIONS[response.action])
        if response is not None and response.action in ("display.phone", "display.phone_close"):
            self.show_phone_code(response.action == "display.phone")
        if response is not None and response.action == ENROLL_ACTION:
            self._spawn(self.enroll(response.target or ""))

    async def enroll(self, person: str) -> Response | None:
        """«Aprende mi voz»: VOXA guía la grabación con el micrófono de la cocina y entrena el verificador."""
        import numpy as np

        from voxa.audio.clip import MIC_RATE
        from voxa.enroll import VoiceEnrollment, train_family_verifier

        if self.session is None or self.mic is None or self._turn.locked():
            return None
        config, mic, session = self.app.config, self.mic, self.session
        heard = f"Aprende la voz de {person}" if person else "Aprende mi voz"

        async def record(seconds: float) -> np.ndarray:
            mic.clear()
            frames, needed = [], int(seconds * MIC_RATE)
            while sum(len(f) for f in frames) < needed:
                frames.append(await mic.read())
            return np.concatenate(frames)[:needed]

        async def train():
            result = await asyncio.to_thread(train_family_verifier, config)
            self._reload_verifier()
            return result

        def show(text: str) -> None:
            self.display.exchange(heard, Response(text))

        async with self._turn:
            if self.muted:
                await self.set_muted(False, acknowledge=False)
            if not mic.is_open and not self._open_microphone():
                await session.say(Response("No encuentro el micrófono.", sound="error"))
                return None
            self.enrolling = person or "familia"
            try:
                response = await VoiceEnrollment(config.wake_recordings_dir, record, session.say, train, show).run(person)
            finally:
                self.enrolling = None
            self.exchange(heard, response)
            await session.say(response)
            mic.clear()
        if self.wake is not None:
            self.wake.reset()
        return response

    def _reload_verifier(self) -> None:
        """El verificador recién entrenado se usa de inmediato, sin reiniciar."""
        path = self.app.config.verifier_path
        if self.wake is not None and path.exists():
            from voxa.audio.verifier import Verifier

            self.wake.verifier = Verifier.load(path)

    def show_phone_code(self, on: bool) -> None:
        """El código QR para abrir VOXA en el celular (unos minutos o hasta que se toque)."""
        url = None
        if on and self.web is not None:
            url = self.web.url(diagnostics.local_ip() or "127.0.0.1")
        self.display.phone_url = url
        self.display.phone_until = time.monotonic() + PHONE_SECONDS if url else None
        self.display.publish()

    async def set_photo(self, on: bool) -> None:
        """«Modo foto»: solo la imagen de fondo; la información vuelve sola al hablar o con una alarma."""
        if on != self.display.photo:
            self.display.photo = on
            self.display.publish()

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
        self._sync_wake()
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

    async def _listen_for_wake(self) -> None:
        """Escucha «Hey Voxa» todo el tiempo (menos con el micrófono apagado o durante un turno).

        Mientras suena una alarma, además, entiende «para», «ya», «gracias»… sin «Hey Voxa».
        """
        from voxa.audio.endpoint import State, UtteranceCollector

        recent: collections.deque = collections.deque(maxlen=2)
        alarm: UtteranceCollector | None = None
        while True:
            wake, mic = self.wake, self.mic
            if wake is None or mic is None or self.session is None or self.muted or not mic.is_open or self._turn.locked():
                recent.clear()
                alarm = None
                await asyncio.sleep(0.1)
                continue
            frame = await mic.read()
            if self._turn.locked():
                wake.reset()  # tocaron la pantalla: ese turno se queda con el micrófono
                continue
            recent.append(frame)
            if await asyncio.to_thread(wake.feed, frame):
                self.wake_count += 1
                log.info("«%s» (%.2f)", WAKE_PHRASE, wake.last_score)
                # El último bloque (ya después de «Voxa») pudo traer el inicio de la orden: se devuelve.
                # Los anteriores no: traerían la cola de «Voxa» y confundirían al reconocedor.
                mic.push_back(list(recent)[-1:])
                recent.clear()
                alarm = None
                await self.talk(after_wake=True)
                mic.clear()  # lo que quedó (la voz de VOXA respondiendo) no debe volver a activarla
                wake.reset()
                continue
            if self.app.timers.ringing:
                alarm = alarm or UtteranceCollector(_alarm_endpoint())
                state = alarm.feed(frame)
                if state is State.DONE:
                    await self._maybe_stop_alarm(alarm.audio)
                if state in (State.DONE, State.NO_SPEECH):
                    alarm = None
            else:
                alarm = None

    async def _maybe_stop_alarm(self, audio) -> None:
        text = await self.session.transcribe(audio)
        intent = self.app.matcher.match(text) if text else None
        log.info("Durante la alarma: «%s» → %s", text, intent.name if intent else None)
        if intent is not None and intent.name in STOPS_ALARM:
            await self.stop_alarm()
        elif intent is not None and intent.name == "timer.adjust":
            # «5 minutos más»: se pospone sin decir «Hey Voxa».
            response = await self.app.assistant.handle_intent(intent)
            self.exchange(text, response)
            self.display.publish()
            if self.session is not None:
                await self.session.say(response)

    async def _keep_microphone(self) -> None:
        """Si el micrófono no abrió (USB desconectado, PipeWire reiniciando), lo reintenta solo."""
        while True:
            await asyncio.sleep(_MIC_RETRY_SECONDS)
            if self.mic is not None and not self.muted and not self.mic.is_open and not self._turn.locked():
                self._open_microphone()

    def _telegram_bot(self) -> ShoppingBot | None:
        config = self.app.config
        token = read_token(config.telegram_token_path)
        if token is None:
            log.warning("Telegram está encendido pero falta el token: corre «voxa telegram-vincular».")
            return None
        chats = Chats(config.telegram_chats_path, config.telegram_code_path)
        api = TelegramApi(token, UrllibHttp(daemon=True))
        return ShoppingBot(api, self.app.shopping, chats, self.app.matcher, on_change=self.display.publish)

    @contextlib.asynccontextmanager
    async def running(self, port: int | None) -> AsyncIterator[Service]:
        """Arranca temporizadores, pantalla y su canal (si ``port`` no es None); los detiene al salir."""
        background = [
            asyncio.create_task(self.app.timers.run()),
            asyncio.create_task(self.display.run()),
            asyncio.create_task(self.health.run()),
            asyncio.create_task(self._keep_microphone()),
            asyncio.create_task(self._listen_for_wake()),
        ]
        if self.app.updater is not None:
            self.app.updater.on_change = self.display.publish
            background.append(asyncio.create_task(self.app.updater.run(self._kitchen_idle)))
        server = None
        if port is not None:
            server = DisplayServer(self.display, self, port=port)
            try:
                await server.start()
            except OSError as exc:
                log.warning("No pude abrir el canal de la pantalla en el puerto %d: %s", port, exc)
                server = None
        config = self.app.config
        if config.web.enabled:
            web = WebServer(self, load_or_create_key(config.web_key_path), config.backgrounds_dir, port=config.web.port)
            try:
                await web.start()
                self.web = web
            except OSError as exc:
                log.warning("No pude abrir VOXA para el celular en el puerto %d: %s", config.web.port, exc)
        if config.telegram.enabled and (bot := self._telegram_bot()) is not None:
            background.append(asyncio.create_task(bot.run()))
        screen = self.app.assistant.skill("display")
        if screen is not None and hasattr(screen, "phone_ready"):
            screen.phone_ready = lambda: self.web is not None
        try:
            yield self
        finally:
            if server:
                await server.close()
            if self.web is not None:
                await self.web.close()
            if self.app.video is not None:
                await self.app.video.close()
            if self.mic is not None:
                self.mic.close()
            for task in [*background, *self._tasks]:
                task.cancel()
            for task in background:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
