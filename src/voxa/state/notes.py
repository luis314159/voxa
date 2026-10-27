"""Notas y recados: «déjale una nota a papá: que compre tortillas».

La nota se ve en la pantalla de la cocina y, cuando VOXA reconoce la voz de a quien va, se la dice
una vez («Por cierto, Luis: Ana te dejó un recado…»). Las notas para todos solo se ven. Se borran
con «ya leí mis recados», desde el celular, o solas después de unos días.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from voxa.nlu.normalize import strip_accents

log = logging.getLogger(__name__)

KEEP_DAYS = 3
MAX_NOTES = 20


def same_person(a: str | None, b: str | None) -> bool:
    def plain(name: str | None) -> str:
        return " ".join(strip_accents((name or "").lower()).replace("-", " ").split())

    return plain(a) == plain(b)


@dataclass
class Note:
    id: int
    text: str
    to: str | None
    """Para quién (``None``: para todos)."""
    author: str | None
    created: float
    told: bool = False
    """Ya se le dijo en voz alta a quien va."""


class NoteBoard:
    def __init__(self, store: Path | None = None, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock
        self.notes: list[Note] = []
        self._load()

    def add(self, text: str, to: str | None, author: str | None) -> Note:
        self._expire()
        note = Note(max((n.id for n in self.notes), default=0) + 1, text.strip(), to, author, self._clock())
        self.notes = [*self.notes, note][-MAX_NOTES:]
        self._save()
        return note

    def for_person(self, person: str | None) -> list[Note]:
        self._expire()
        return [n for n in self.notes if n.to is not None and same_person(n.to, person)]

    def untold(self, person: str) -> list[Note]:
        return [n for n in self.for_person(person) if not n.told]

    def mark_told(self, notes: list[Note]) -> None:
        for note in notes:
            note.told = True
        self._save()

    def clear(self, person: str | None) -> int:
        """«Ya leí mis recados»: las de esa persona (sin saber quién habla, las de todos)."""
        before = len(self.notes)
        self.notes = [n for n in self.notes if person is not None and not same_person(n.to, person)]
        self._save()
        return before - len(self.notes)

    def remove(self, note_id: int) -> bool:
        before = len(self.notes)
        self.notes = [n for n in self.notes if n.id != note_id]
        self._save()
        return len(self.notes) < before

    def snapshot(self) -> list[dict]:
        self._expire()
        return [{"id": n.id, "text": n.text, "to": n.to, "from": n.author} for n in self.notes]

    def _expire(self) -> None:
        cutoff = self._clock() - KEEP_DAYS * 86400
        if any(n.created < cutoff for n in self.notes):
            self.notes = [n for n in self.notes if n.created >= cutoff]
            self._save()

    def _load(self) -> None:
        if not self._store or not self._store.exists():
            return
        try:
            self.notes = [Note(**n) for n in json.loads(self._store.read_text(encoding="utf-8")) if isinstance(n, dict)]
        except (OSError, ValueError, TypeError) as exc:
            log.warning("No pude leer las notas: %s", exc)

    def _save(self) -> None:
        if not self._store:
            return
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            self._store.write_text(json.dumps([asdict(n) for n in self.notes], ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("No pude guardar las notas: %s", exc)
