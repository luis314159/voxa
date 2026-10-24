"""Micrófono y salida con sounddevice (PortAudio): en Linux pasa por PipeWire, en Windows por WASAPI/MME."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import numpy as np

from voxa.audio.clip import MIC_RATE, OUTPUT_RATE, Clip
from voxa.audio.endpoint import FRAME_SAMPLES, State, UtteranceCollector

log = logging.getLogger(__name__)


class Microphone:
    """Mantiene el micrófono abierto y entrega bloques de 80 ms (int16, 16 kHz)."""

    def __init__(self, device: str | int | None = None) -> None:
        self._device = device
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=200)
        self._stream = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def __aenter__(self) -> Microphone:
        self.open()
        return self

    async def __aexit__(self, *exc) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    def open(self) -> None:
        """Abre el micrófono (``sounddevice.PortAudioError`` si no hay o está ocupado)."""
        import sounddevice as sd

        if self._stream is not None:
            return
        self._loop = asyncio.get_running_loop()
        stream = sd.InputStream(
            samplerate=MIC_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=self._device,
            callback=self._callback,
        )
        stream.start()
        self._stream = stream

    def close(self) -> None:
        """Suelta el micrófono de verdad (modo privado): el sistema deja de mostrarlo en uso."""
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        self.clear()

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("Micrófono: %s", status)
        frame = indata[:, 0].copy()
        self._loop.call_soon_threadsafe(self._put, frame)

    def _put(self, frame: np.ndarray) -> None:
        if self._queue.full():
            self._queue.get_nowait()  # se descarta lo más viejo: nadie está escuchando
        self._queue.put_nowait(frame)

    def clear(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()

    async def read(self) -> np.ndarray:
        return await self._queue.get()

    async def record_utterance(self, collector: UtteranceCollector, skip_ms: int = 0) -> np.ndarray | None:
        """Graba una frase. ``skip_ms`` descarta el inicio (eco del sonido «escuchando» por la bocina)."""
        self.clear()
        for _ in range(skip_ms // 80):
            await self.read()
        while True:
            state = collector.feed(await self.read())
            if state is State.DONE:
                return collector.audio
            if state is State.NO_SPEECH:
                return None


class AudioOutput(Protocol):
    async def play(self, clip: Clip) -> None: ...


class SpeakerOutput:
    def __init__(self, device: str | int | None = None, lead_in_ms: int = 0) -> None:
        self._device = device
        self._lead_in_ms = lead_in_ms
        self._lock = asyncio.Lock()

    async def play(self, clip: Clip) -> None:
        import sounddevice as sd

        # El silencio inicial le da tiempo a una bocina Bluetooth dormida para despertar.
        clip = clip.resampled(OUTPUT_RATE).with_silence(before_ms=self._lead_in_ms)
        async with self._lock:
            await asyncio.to_thread(self._play_blocking, sd, clip)

    def _play_blocking(self, sd, clip: Clip) -> None:
        sd.play(clip.samples, clip.rate, device=self._device, blocking=True)


class SilentOutput:
    """Para pruebas y modo texto: registra lo que se habría reproducido."""

    def __init__(self) -> None:
        self.played: list[Clip] = []

    async def play(self, clip: Clip) -> None:
        self.played.append(clip)
