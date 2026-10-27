"""Quién está hablando en este turno (si VOXA reconoció su voz): para saludar y personalizar.

Lo pone el turno de voz antes de entender la orden; las habilidades lo leen con ``speaker()``.
Desde el celular o la pantalla no se sabe quién es (``None``).
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Iterator

_current: ContextVar[str | None] = ContextVar("voxa_persona", default=None)


def speaker() -> str | None:
    return _current.get()


@contextlib.contextmanager
def speaking(person: str | None) -> Iterator[None]:
    token = _current.set(person)
    try:
        yield
    finally:
        _current.reset(token)


def resolve(name: str, aliases: dict[str, str]) -> str:
    """«papá» → «Luis» si así le dicen (Ajustes → Voz de la familia); si no, el nombre como se dijo."""
    from voxa.nlu.normalize import strip_accents

    def plain(text: str) -> str:
        return " ".join(strip_accents(text.lower()).replace("-", " ").split())

    words = name.split()
    if len(words) > 1 and plain(words[0]) in ("el", "la", "mi", "my", "the"):  # «la tía Rosa», «mi abuela»
        words = words[1:]
    said = plain(" ".join(words))
    for person, nicknames in aliases.items():
        if said == plain(person) or said in (plain(n) for n in nicknames.split(",") if n.strip()):
            return person
    return " ".join(w[:1].upper() + w[1:] for w in words)
