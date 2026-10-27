"""Un turno de voz completo: escuchar → reconocer → entender → responder.

Lo dispara «pulsar para hablar» (Fase 1) y, más adelante, el detector de «Hey Voxa».
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterable, Callable, Protocol

from voxa.audio.clip import Clip
from voxa.audio.devices import AudioOutput, Microphone
from voxa.audio.ducking import Ducker
from voxa.audio.endpoint import EndpointConfig, UtteranceCollector
from voxa.audio.stt import SpeechToText
from voxa.audio.tts import TextToSpeech
from voxa.core.assistant import Assistant
from voxa.core.people import speaking
from voxa.core.speech import speech_chunks
from voxa.core.types import Response
from voxa.i18n import in_language

log = logging.getLogger(__name__)

# Frases que conviene tener listas en caché desde el arranque.
COMMON_PHRASES = [
    "No te entendí. Puedes preguntarme «¿qué puedes hacer?».",
    "No pude conectar con Spotify. Revisa que Spotifast esté abierto.",
    "No hay temporizadores.",
    "No está sonando nada.",
    "Aquí estoy.",
]


@dataclass
class TurnTimings:
    """Tiempos de un turno, para medir el presupuesto de latencia del plan (§5.1)."""

    listen: float = 0.0
    stt: float = 0.0
    nlu_and_action: float = 0.0
    tts: float = 0.0
    marks: dict[str, float] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"escucha {self.listen:.2f}s · STT {self.stt:.2f}s · acción {self.nlu_and_action:.2f}s · TTS {self.tts:.2f}s"


class TurnObserver(Protocol):
    """Quien quiera seguir el turno (la pantalla): fase actual y qué se oyó/respondió."""

    def phase(self, name: str) -> None: ...  # idle | listening | thinking | speaking
    def exchange(self, heard: str, response: Response | None) -> None: ...


class _NoObserver:
    def phase(self, name: str) -> None:
        pass

    def exchange(self, heard: str, response: Response | None) -> None:
        pass


@dataclass
class TurnResult:
    heard: str | None
    response: Response | None
    timings: TurnTimings
    person: str | None = None


class VoiceSession:
    def __init__(
        self,
        assistant: Assistant,
        stt: SpeechToText,
        tts: TextToSpeech | None,
        output: AudioOutput,
        sounds: dict[str, Clip],
        ducker: Ducker,
        echo_guard_ms: int = 240,
        endpoint: EndpointConfig | None = None,
        observer: TurnObserver | None = None,
    ) -> None:
        self.assistant = assistant
        self._stt = stt
        self._tts = tts
        self._output = output
        self._sounds = sounds
        self._ducker = ducker
        self._echo_guard_ms = echo_guard_ms
        self._endpoint = endpoint or EndpointConfig()
        self._speaking = asyncio.Lock()
        self.observer: TurnObserver = observer or _NoObserver()
        self.identify: Callable[[object], str | None] | None = None
        """Quién habla (por su voz); ``None`` si nadie ha grabado su voz."""
        self.gain: Callable[[], float] = lambda: 1.0
        """Horas de silencio: qué tan fuerte salen la voz y los sonidos (las alarmas, siempre normal)."""

    async def _play(self, clip: Clip) -> None:
        gain = self.gain()
        await self._output.play(clip if gain >= 1.0 else Clip(clip.samples * gain, clip.rate))

    def warm_up(self, phrases: list[str] = COMMON_PHRASES) -> None:
        if self._tts is not None and hasattr(self._tts, "warm_up"):
            self._tts.warm_up(phrases)

    async def turn(self, mic: Microphone, *, after_wake: bool = False) -> TurnResult:
        """Un turno. ``after_wake``: lo disparó «Hey Voxa» y la orden puede venir pegada.

        En ese caso el sonido «escuchando» suena mientras ya se graba (sin descartar su eco):
        perder el «pon» de «Hey Voxa, pon música» sería peor que un pitido en el audio.
        """
        timings = TurnTimings()
        await self._ducker.duck()
        try:
            self.observer.phase("listening")
            start = time.perf_counter()
            collector = UtteranceCollector(self._endpoint)
            if after_wake:
                chime = asyncio.ensure_future(self._play(self._sounds["listening"]))
                audio = await mic.record_utterance(collector, clear=False)
                await chime
            else:
                await self._play(self._sounds["listening"])
                start = time.perf_counter()
                audio = await mic.record_utterance(collector, skip_ms=self._echo_guard_ms)
            timings.listen = time.perf_counter() - start
            if audio is None:
                await self._play(self._sounds["cancel"])
                return TurnResult(None, None, timings)
            return await self.respond_to_audio(audio, timings)
        finally:
            self.observer.phase("idle")
            await self._ducker.restore()

    async def transcribe(self, audio) -> str:
        return await asyncio.to_thread(self._stt.transcribe, audio)

    async def respond_to_audio(self, audio, timings: TurnTimings | None = None) -> TurnResult:
        timings = timings or TurnTimings()
        self.observer.phase("thinking")
        start = time.perf_counter()
        who = asyncio.ensure_future(asyncio.to_thread(self._who, audio))  # a la par del reconocimiento
        text = await asyncio.to_thread(self._stt.transcribe, audio)
        timings.stt = time.perf_counter() - start
        person = await who
        if not text:
            self.observer.exchange("", None)
            await self._play(self._sounds["error"])
            return TurnResult("", None, timings, person)

        start = time.perf_counter()
        with speaking(person):
            response = await self.assistant.handle_text(text, getattr(self._stt, "last_language", None))
        timings.nlu_and_action = time.perf_counter() - start
        self.observer.exchange(text, response)
        timings.tts = await self.say(response)
        log.info("«%s»%s → %s (%s)", text, f" ({person})" if person else "", response.speech or response.sound, timings)
        return TurnResult(text, response, timings, person)

    def _who(self, audio) -> str | None:
        if self.identify is None:
            return None
        try:
            return self.identify(audio)
        except Exception as exc:  # noqa: BLE001 - saber quién habla nunca debe tumbar el turno
            log.warning("No pude reconocer la voz: %s", exc)
            return None

    async def say(self, response: Response) -> float:
        """Reproduce la respuesta; devuelve lo que tardó en empezar a sonar (síntesis del primer trozo)."""
        if response.spoken:
            return 0.0
        if response.speech and self._tts:
            with in_language(response.language):  # casa bilingüe: la voz del idioma de la respuesta
                return await self.say_stream(_iterate(speech_chunks(response.speech)))
        async with self._speaking:
            if response.sound or response.speech:
                await self._play(self._sounds.get(response.sound or "ok", self._sounds["ok"]))
            return 0.0

    async def say_stream(self, chunks: AsyncIterable[str]) -> float:
        """Dice los trozos según llegan: mientras suena uno, se sintetiza el siguiente.

        Devuelve lo que tardó el primero en estar listo (lo que se espera en silencio).
        """
        if self._tts is None:
            async for _ in chunks:
                pass
            return 0.0
        clips: asyncio.Queue = asyncio.Queue()
        first_ready = 0.0

        async def synthesize() -> None:
            nonlocal first_ready
            start = time.perf_counter()
            try:
                async for chunk in chunks:
                    if chunk.strip():
                        clip = await asyncio.to_thread(self._tts.synthesize, chunk)
                        if not first_ready:
                            first_ready = time.perf_counter() - start
                        await clips.put(clip)
            finally:
                await clips.put(None)

        async with self._speaking:
            producer = asyncio.ensure_future(synthesize())
            try:
                while (clip := await clips.get()) is not None:
                    self.observer.phase("speaking")
                    await self._play(clip)
            finally:
                self.observer.phase("idle")
                if not producer.done():
                    producer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await producer
        return first_ready

    async def announce(self, text: str) -> None:
        """Alarma: baja la música, suena el aviso y lo dice en voz alta."""
        await self._ducker.duck()
        try:
            async with self._speaking:
                await self._output.play(self._sounds["alarm"])  # la alarma suena normal, aun de noche
            await self.say(Response(text))
        finally:
            await self._ducker.restore()


async def _iterate(items: list[str]):
    for item in items:
        yield item
