"""Voz de VOXA con Piper. Cada frase sintetizada se guarda en caché: la segunda vez es instantánea."""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

from voxa.audio.clip import Clip
from voxa.audio.pronunciation import Lexicon, fix_phonemes

log = logging.getLogger(__name__)

_PHONEME_FIXES_VERSION = 1  # súbelo al cambiar fix_phonemes: invalida el audio en caché


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> Clip: ...


class PiperTts:
    def __init__(
        self,
        model: Path,
        cache_dir: Path | None = None,
        length_scale: float = 1.0,
        lexicon: Lexicon | None = None,
    ) -> None:
        from piper import PiperVoice, SynthesisConfig  # import perezoso: solo si se usa voz

        self._voice = PiperVoice.load(model)
        espeak_phonemize = self._voice.phonemize
        self._voice.phonemize = lambda text: [fix_phonemes(s) for s in espeak_phonemize(text)]
        self._config = SynthesisConfig(length_scale=length_scale)
        self._lexicon = lexicon or Lexicon({})
        self._cache_dir = cache_dir
        self._cache_prefix = f"{model.stem}-{length_scale}-{_PHONEME_FIXES_VERSION}"
        self._lock = threading.Lock()  # el modelo ONNX no se comparte entre hilos

    def phonemes(self, text: str) -> str:
        """Fonemas que Piper usará, con los ajustes aplicados (para depurar pronunciaciones)."""
        with self._lock:
            return " | ".join("".join(s) for s in self._voice.phonemize(self._lexicon.apply(text)))

    def synthesize(self, text: str) -> Clip:
        text = self._lexicon.apply(text)
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


class BilingualTts:
    """Casa bilingüe: cada respuesta con la voz de su idioma (``voxa.i18n.language`` de esa tarea)."""

    def __init__(self, voices: dict[str, TextToSpeech], home: str) -> None:
        self._voices = voices
        self._home = home

    def synthesize(self, text: str) -> Clip:
        from voxa.i18n import language

        return self._voices.get(language(), self._voices[self._home]).synthesize(text)

    def phonemes(self, text: str) -> str:
        return self._voices[self._home].phonemes(text)  # type: ignore[attr-defined]

    def warm_up(self, phrases: list[str]) -> None:
        home = self._voices[self._home]
        if hasattr(home, "warm_up"):
            home.warm_up(phrases)
