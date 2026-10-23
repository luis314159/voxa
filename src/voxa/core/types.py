"""Tipos que comparten la NLU, el asistente y las habilidades."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Intent:
    name: str
    slots: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    """Texto normalizado que se reconoció."""
    raw: str = ""
    """Texto tal como llegó del STT."""

    @property
    def domain(self) -> str:
        return self.name.split(".", 1)[0]


@dataclass(frozen=True)
class Response:
    speech: str | None = None
    """Lo que VOXA dice. ``None`` cuando basta un sonido."""
    sound: str | None = None
    """Earcon a reproducir: ``"ok"`` o ``"error"``."""
    action: str | None = None
    """Efecto para el runtime de audio/UI, p. ej. ``"mic.mute"``."""


OK = Response(sound="ok")


class Skill(Protocol):
    async def handle(self, intent: Intent) -> Response: ...
