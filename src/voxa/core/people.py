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
