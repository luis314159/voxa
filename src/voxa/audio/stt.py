"""Reconocimiento de voz: Vosk (rápido, comandos), faster-whisper (preciso, texto libre) e híbrido."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from voxa.audio.clip import MIC_RATE

log = logging.getLogger(__name__)


class SpeechToText(Protocol):
    name: str

    def transcribe(self, samples: np.ndarray) -> str:
        """``samples``: int16 mono a 16 kHz."""
        ...


UNKNOWN = "[unk]"
_ACCENTED = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú"}


def accent_variants(word: str) -> set[str]:
    """«musica» → {musica, músíca…}: la gramática va sin acentos y el modelo de Vosk con ellos.

    En español hay como máximo una tilde por palabra; también se prueba ñ por n.
    Vosk descarta en silencio las variantes que no existen en su léxico.
    """
    variants = {word}
    for i, ch in enumerate(word):
        if ch in _ACCENTED:
            variants.add(word[:i] + _ACCENTED[ch] + word[i + 1 :])
        elif ch == "n":
            variants.add(word[:i] + "ñ" + word[i + 1 :])
    return variants


class VoskStt:
    """Con ``vocabulary``, Vosk solo reconoce esas palabras (y ``[unk]`` para lo demás):
    mucho más preciso para comandos, y deja el texto libre a Whisper."""

    def __init__(self, model_dir: Path, vocabulary: list[str] | None = None, *, model=None) -> None:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-2)  # oculta los avisos por cada variante que no existe en el léxico
        self.name = "vosk-gramatica" if vocabulary else "vosk"
        self.model = model or Model(str(model_dir))  # se puede compartir entre reconocedores
        model = self.model
        if vocabulary:
            words = sorted({v for w in vocabulary for v in accent_variants(w)})
            # ensure_ascii=False: Vosk no decodifica los escapes \uXXXX y descartaría las palabras con tilde.
            grammar = json.dumps([*words, UNKNOWN], ensure_ascii=False)
            self._recognizer = KaldiRecognizer(model, MIC_RATE, grammar)
        else:
            self._recognizer = KaldiRecognizer(model, MIC_RATE)

    def transcribe(self, samples: np.ndarray) -> str:
        self._recognizer.Reset()
        self._recognizer.AcceptWaveform(samples.astype(np.int16).tobytes())
        return json.loads(self._recognizer.FinalResult()).get("text", "").strip()


class WhisperStt:
    name = "whisper"

    def __init__(self, model: str = "base", threads: int = 0, language: str = "es") -> None:
        from faster_whisper import WhisperModel

        self.language = language
        self._model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads)

    def transcribe(self, samples: np.ndarray) -> str:
        audio = samples.astype(np.float32) / 32768.0
        # Sin initial_prompt: con frases cortas Whisper tiende a «repetir» el prompt.
        segments, _ = self._model.transcribe(
            audio, language=self.language, beam_size=2, condition_on_previous_text=False, vad_filter=False
        )
        return " ".join(s.text.strip() for s in segments).strip()


class HybridStt:
    """Vosk primero; si la frase lleva texto libre (nombres de canciones…), Whisper sobre el mismo audio.

    Con ``closed`` (Vosk limitado al vocabulario de la gramática) se prueba antes: las órdenes cortas
    («pausa», «ayuda», «modo foto») las reconoce mejor que nadie y en ~0.1 s; solo se acepta si no
    hubo palabras fuera del vocabulario y la orden se entiende completa, sin texto libre.

    Si Whisper entrega algo que no se entiende y Vosk sí, gana Vosk: con frases
    cortas Whisper a veces inventa.
    """

    name = "hibrido"

    def __init__(
        self,
        fast: SpeechToText,
        accurate: SpeechToText,
        needs_accurate: Callable[[str], bool],
        understands: Callable[[str], bool] | None = None,
        closed: SpeechToText | None = None,
    ) -> None:
        self._fast = fast
        self._accurate = accurate
        self._needs_accurate = needs_accurate
        self._understands = understands or (lambda text: bool(text))
        self._closed = closed

    def transcribe(self, samples: np.ndarray) -> str:
        started = time.perf_counter()
        if self._closed is not None:
            command = self._closed.transcribe(samples)
            if command and UNKNOWN not in command and self._understands(command) and not self._needs_accurate(command):
                log.info("STT %s (%.2fs): %s", self._closed.name, time.perf_counter() - started, command)
                return command
        text = self._fast.transcribe(samples)
        if text and UNKNOWN not in text and not self._needs_accurate(text):
            log.info("STT %s (%.2fs): %s", self._fast.name, time.perf_counter() - started, text)
            return text
        accurate = self._accurate.transcribe(samples)
        fast_text = text.replace(UNKNOWN, "").strip()
        chosen = fast_text if not self._understands(accurate) and self._understands(fast_text) else accurate
        log.info("STT %s→%s (%.2fs): %r / %r → %r", self._fast.name, self._accurate.name,
                 time.perf_counter() - started, text, accurate, chosen)
        return chosen or fast_text
