"""Lista del súper: persistente, sin repetidos (sin importar acentos ni mayúsculas)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from voxa.nlu.normalize import strip_accents
from voxa.state.timers import display_label

log = logging.getLogger(__name__)


def item_key(item: str) -> str:
    """«la leche», «Leche» y «leché» son lo mismo; el plural simple también («huevo»/«huevos»)."""
    key = strip_accents(display_label(item))
    return key[:-2] if key.endswith("es") and len(key) > 4 else key[:-1] if key.endswith("s") and len(key) > 3 else key


class ShoppingList:
    def __init__(self, store: Path | None = None) -> None:
        self._store = store
        self.items: list[str] = []
        self._load()

    def add(self, items: list[str]) -> tuple[list[str], list[str]]:
        """Devuelve (agregados, que ya estaban)."""
        added, present = [], []
        keys = {item_key(i) for i in self.items}
        for item in items:
            name = display_label(item)
            if not name:
                continue
            if item_key(name) in keys:
                present.append(name)
            else:
                self.items.append(name)
                keys.add(item_key(name))
                added.append(name)
        if added:
            self._save()
        return added, present

    def remove(self, item: str) -> str | None:
        key = item_key(item)
        for existing in self.items:
            if item_key(existing) == key:
                self.items.remove(existing)
                self._save()
                return existing
        return None

    def clear(self) -> int:
        count = len(self.items)
        self.items.clear()  # la misma lista: la pantalla la tiene referenciada
        self._save()
        return count

    def _load(self) -> None:
        if not self._store or not self._store.exists():
            return
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            self.items[:] = [str(i) for i in data if isinstance(i, str)]
        except (OSError, ValueError) as exc:
            log.warning("No pude leer la lista del súper: %s", exc)

    def _save(self) -> None:
        if not self._store:
            return
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._store)
        except OSError as exc:
            log.warning("No pude guardar la lista del súper: %s", exc)
