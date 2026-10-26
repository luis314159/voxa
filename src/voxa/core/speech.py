"""Partir lo que VOXA dice en trozos para empezar a hablar antes (síntesis y audio se encadenan).

Mientras suena un trozo, Piper ya sintetiza el siguiente: en una respuesta larga, lo que se espera
es lo que tarda el primer trozo, no toda la respuesta. Por eso el primero es corto (se corta en una
coma si la frase es larga) y los demás son oraciones completas, que suenan más naturales.
"""

from __future__ import annotations

import re

CHUNK_FROM_WORDS = 18
"""Respuestas más cortas se dicen de una vez (partirlas solo agregaría pausas)."""
_FIRST_MAX_WORDS = 14
_MIN_WORDS = 4
_SENTENCE_END = re.compile(r"[.!?…]+[»\"')]*(?=\s)")
_COMMA = re.compile(r"[,;:](?=\s)")
_ABBREVIATIONS = frozenset({"sr", "sra", "srta", "dr", "dra", "lic", "ing", "ud", "uds", "aprox", "núm", "pág"})


def _words(text: str) -> int:
    return len(text.split())


def _sentence_end(text: str, start: int = 0) -> int | None:
    """Dónde termina la primera oración completa (después del signo), o ``None``.

    No corta en abreviaturas cortas: «7 p. m. Hoy…», «Sr. López».
    """
    for m in _SENTENCE_END.finditer(text, start):
        before = text[: m.start()].split()
        word = before[-1].lower() if before else ""
        if m.group().startswith(".") and word.isalpha() and (len(word) == 1 or word in _ABBREVIATIONS):
            continue
        return m.end()
    return None


class SpeechChunker:
    """Recibe texto a pedazos (de una IA que transmite) y entrega trozos listos para decir."""

    def __init__(self) -> None:
        self._buffer = ""
        self._first = True

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        ready = []
        while (chunk := self._take()) is not None:
            ready.append(chunk)
        return ready

    def flush(self) -> list[str]:
        rest, self._buffer = self._buffer.strip(), ""
        return [rest] if rest else []

    def _take(self) -> str | None:
        text = self._buffer
        start, end = 0, None
        while (found := _sentence_end(text, start)) is not None:
            if _words(text[:found]) >= _MIN_WORDS:
                end = found
                break
            start = found  # oración muy corta («Claro.»): se junta con la siguiente
        span = text[:end] if end is not None else text
        if self._first and _words(span) > _FIRST_MAX_WORDS:
            # Primer trozo largo: se corta en una coma para empezar a hablar pronto.
            for m in _COMMA.finditer(span):
                if _words(text[: m.end()]) >= _MIN_WORDS + 1:
                    return self._cut(m.end())
        return self._cut(end) if end is not None else None

    def _cut(self, end: int) -> str:
        chunk, self._buffer = self._buffer[:end].strip(), self._buffer[end:]
        self._first = False
        return chunk


def speech_chunks(text: str) -> list[str]:
    """Una respuesta completa, en trozos; las cortas quedan enteras."""
    if _words(text) < CHUNK_FROM_WORDS:
        return [text]
    chunker = SpeechChunker()
    return chunker.feed(text + " ") + chunker.flush()
