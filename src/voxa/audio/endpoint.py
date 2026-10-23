"""Decide cuándo empezó y terminó de hablar la persona (endpointing).

Detector de energía con piso de ruido adaptativo: no necesita modelos ni
dependencias, y aguanta el ruido constante de una cocina (extractor, refri).
"""

from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass

import numpy as np

from voxa.audio.clip import MIC_RATE


def frame_db(frame: np.ndarray) -> float:
    rms = np.sqrt(np.mean(np.square(frame.astype(np.float64) / 32768.0)))
    return 20 * np.log10(max(rms, 1e-6))


class EnergyDetector:
    def __init__(self, margin_db: float = 10.0, floor_db: float = -55.0, adapt: float = 0.05) -> None:
        self._margin = margin_db
        self._min_speech = floor_db
        self._adapt = adapt
        self.noise_db: float | None = None

    def is_speech(self, frame: np.ndarray) -> bool:
        level = frame_db(frame)
        if self.noise_db is None:
            self.noise_db = level
        speech = level > max(self.noise_db + self._margin, self._min_speech)
        if not speech:
            # El piso de ruido solo aprende de lo que no es voz.
            self.noise_db += self._adapt * (level - self.noise_db)
        return speech


class State(enum.Enum):
    WAITING = "esperando"
    SPEAKING = "hablando"
    DONE = "listo"
    NO_SPEECH = "sin voz"


@dataclass
class EndpointConfig:
    frame_ms: int = 80
    preroll_ms: int = 320
    """Audio previo al inicio detectado que se conserva (para no cortar la primera sílaba)."""
    start_ms: int = 160
    """Voz continua necesaria para considerar que empezó a hablar."""
    end_silence_ms: int = 720
    """Silencio tras la voz que marca el fin de la frase."""
    max_ms: int = 8000
    no_speech_timeout_ms: int = 5000


class UtteranceCollector:
    """Recibe bloques del micrófono uno a uno y arma la frase completa."""

    def __init__(self, config: EndpointConfig | None = None, detector: EnergyDetector | None = None) -> None:
        self.config = config or EndpointConfig()
        self._detector = detector or EnergyDetector()
        frames = lambda ms: max(1, ms // self.config.frame_ms)  # noqa: E731
        self._preroll: deque[np.ndarray] = deque(maxlen=frames(self.config.preroll_ms))
        self._start_frames = frames(self.config.start_ms)
        self._end_frames = frames(self.config.end_silence_ms)
        self._max_frames = frames(self.config.max_ms)
        self._timeout_frames = frames(self.config.no_speech_timeout_ms)
        self._frames: list[np.ndarray] = []
        self._run = 0
        self._silence = 0
        self._waited = 0
        self.state = State.WAITING

    def feed(self, frame: np.ndarray) -> State:
        if self.state in (State.DONE, State.NO_SPEECH):
            return self.state
        speech = self._detector.is_speech(frame)

        if self.state is State.WAITING:
            self._waited += 1
            self._preroll.append(frame)
            self._run = self._run + 1 if speech else 0
            if self._run >= self._start_frames:
                self._frames = list(self._preroll)
                self.state = State.SPEAKING
            elif self._waited >= self._timeout_frames:
                self.state = State.NO_SPEECH
            return self.state

        self._frames.append(frame)
        self._silence = 0 if speech else self._silence + 1
        if self._silence >= self._end_frames or len(self._frames) >= self._max_frames:
            # Se recorta el silencio final, dejando un poco de cola.
            keep = len(self._frames) - max(0, self._silence - 2)
            self._frames = self._frames[:keep]
            self.state = State.DONE
        return self.state

    @property
    def audio(self) -> np.ndarray:
        return np.concatenate(self._frames) if self._frames else np.zeros(0, dtype=np.int16)


FRAME_SAMPLES = MIC_RATE * EndpointConfig.frame_ms // 1000
