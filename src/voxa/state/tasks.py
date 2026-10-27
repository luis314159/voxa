"""Pendientes de la familia y de cada persona («llamar al plomero», «tarea de mate»), persistentes."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from voxa.nlu.normalize import strip_accents
from voxa.state.timers import display_label

log = logging.getLogger(__name__)


@dataclass
class Task:
    id: int
    text: str
    person: str | None = None
    """De quién es (``None``: de la casa)."""
    created: float = 0.0


def _key(text: str) -> str:
    return strip_accents(display_label(text))


class TaskList:
    def __init__(self, store: Path | None = None) -> None:
        self._store = store
        self.tasks: list[Task] = []
        self._next = 1
        self._load()

    def of(self, person: str | None) -> list[Task]:
        """Los de esa persona; con ``None``, los de la casa."""
        return [t for t in self.tasks if (t.person or None) == (person or None)]

    def add(self, text: str, person: str | None = None) -> Task | None:
        text = display_label(text).strip()
        if not text:
            return None
        if any(_key(t.text) == _key(text) for t in self.of(person)):
            return None  # ya estaba
        task = Task(self._next, text, person, time.time())
        self._next += 1
        self.tasks.append(task)
        self._save()
        return task

    def done(self, text_or_id: str | int, person: str | None = None) -> Task | None:
        """Quita el pendiente (por id, o por texto: primero los de esa persona, luego los de la casa)."""
        if isinstance(text_or_id, int):
            found = next((t for t in self.tasks if t.id == text_or_id), None)
        else:
            key = _key(text_or_id)
            candidates = self.of(person) + (self.of(None) if person else [])
            found = next((t for t in candidates if _key(t.text) == key), None)
            found = found or next((t for t in candidates if key and key in _key(t.text)), None)
        if found is not None:
            self.tasks.remove(found)
            self._save()
        return found

    def _load(self) -> None:
        if not self._store or not self._store.exists():
            return
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            self.tasks = [Task(**item) for item in data]
            self._next = max((t.id for t in self.tasks), default=0) + 1
        except (OSError, ValueError, TypeError) as exc:
            log.warning("No pude leer los pendientes: %s", exc)

    def _save(self) -> None:
        if not self._store:
            return
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(t) for t in self.tasks], ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._store)
        except OSError as exc:
            log.warning("No pude guardar los pendientes: %s", exc)
