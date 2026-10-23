"""Voz de VOXA con Piper. Cada frase sintetizada se guarda en caché: la segunda vez es instantánea."""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

from voxa.audio.clip import Clip

log = logging.getLogger(__name__)


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> Clip: ...


class PiperTts:
    def __init__(self, model: Path, cache_dir: Path | None = None, length_scale: float = 1.0) -> None:
        from piper import PiperVoice, SynthesisConfig  # import perezoso: solo si se usa voz

        self._voice = PiperVoice.load(model)
        self._config = SynthesisConfig(length_scale=length_scale)
        self._cache_dir = cache_dir
        self._cache_prefix = f"{model.stem}-{length_scale}"
        self._lock = threading.Lock()  # el modelo ONNX no se comparte entre hilos

    def synthesize(self, text: str) -> Clip:
        cached = self._cache_path(text)
        if cached and cached.exists():
            return Clip.load(cached)
        with self._lock:
            chunks = list(self._voice.synthesize(text, self._config))
        if not chunks:
            raise ValueError(f"Piper no generó audio para {text!r}")
        clip = Clip(np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32), chunks[0].sample_rate)
        if cached:
            try:
                clip.save(cached)
            except OSError as exc:
                log.warning("No pude guardar en caché la frase: %s", exc)
        return clip

    def warm_up(self, phrases: list[str]) -> None:
        """Pre-genera frases frecuentes para que suenen sin espera."""
        for phrase in phrases:
            self.synthesize(phrase)

    def _cache_path(self, text: str) -> Path | None:
        if not self._cache_dir:
            return None
        digest = hashlib.sha1(f"{self._cache_prefix}|{text}".encode()).hexdigest()[:16]
        return self._cache_dir / f"{digest}.wav"
