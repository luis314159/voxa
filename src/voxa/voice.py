"""Un turno de voz completo: escuchar → reconocer → entender → responder.

Lo dispara «pulsar para hablar» (Fase 1) y, más adelante, el detector de «Hey Voxa».
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from voxa.audio.clip import Clip
from voxa.audio.devices import AudioOutput, Microphone
from voxa.audio.ducking import Ducker
from voxa.audio.endpoint import EndpointConfig, UtteranceCollector
from voxa.audio.stt import SpeechToText
from voxa.audio.tts import TextToSpeech
from voxa.core.assistant import Assistant
from voxa.core.types import Response

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

    def warm_up(self, phrases: list[str] = COMMON_PHRASES) -> None:
        if self._tts is not None and hasattr(self._tts, "warm_up"):
            self._tts.warm_up(phrases)

    async def turn(self, mic: Microphone) -> TurnResult:
        timings = TurnTimings()
        await self._ducker.duck()
        try:
            self.observer.phase("listening")
            await self._output.play(self._sounds["listening"])
            start = time.perf_counter()
            audio = await mic.record_utterance(UtteranceCollector(self._endpoint), skip_ms=self._echo_guard_ms)
            timings.listen = time.perf_counter() - start
            if audio is None:
                await self._output.play(self._sounds["cancel"])
                return TurnResult(None, None, timings)
            return await self.respond_to_audio(audio, timings)
        finally:
            self.observer.phase("idle")
            await self._ducker.restore()

    async def respond_to_audio(self, audio, timings: TurnTimings | None = None) -> TurnResult:
        timings = timings or TurnTimings()
        self.observer.phase("thinking")
        start = time.perf_counter()
        text = await asyncio.to_thread(self._stt.transcribe, audio)
        timings.stt = time.perf_counter() - start
        if not text:
            self.observer.exchange("", None)
            await self._output.play(self._sounds["error"])
            return TurnResult("", None, timings)

        start = time.perf_counter()
        response = await self.assistant.handle_text(text)
        timings.nlu_and_action = time.perf_counter() - start
        self.observer.exchange(text, response)
        timings.tts = await self.say(response)
        log.info("«%s» → %s (%s)", text, response.speech or response.sound, timings)
        return TurnResult(text, response, timings)

    async def say(self, response: Response) -> float:
        """Reproduce la respuesta; devuelve lo que tardó la síntesis."""
        async with self._speaking:
            if response.speech and self._tts:
                start = time.perf_counter()
                clip = await asyncio.to_thread(self._tts.synthesize, response.speech)
                elapsed = time.perf_counter() - start
                self.observer.phase("speaking")
                try:
                    await self._output.play(clip)
                finally:
                    self.observer.phase("idle")
                return elapsed
            if response.sound or response.speech:
                await self._output.play(self._sounds.get(response.sound or "ok", self._sounds["ok"]))
            return 0.0

    async def announce(self, text: str) -> None:
        """Alarma: baja la música, suena el aviso y lo dice en voz alta."""
        await self._ducker.duck()
        try:
            async with self._speaking:
                await self._output.play(self._sounds["alarm"])
            await self.say(Response(text))
        finally:
            await self._ducker.restore()
