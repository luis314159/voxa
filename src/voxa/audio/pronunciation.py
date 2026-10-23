"""Ajustes de pronunciación para Piper.

Dos capas:

- ``fix_phonemes`` corrige un hábito de eSpeak (el fonetizador de Piper): tras «br», «dr», «cl»…
  convierte la *i* átona en una sílaba propia con un sonido palatal raro (``ɡaβɾiʲˈel``, «Ga-bri-ʲél»).
  En México se dice «Ga-briel», con diptongo: ``ɡaβɾjˈel``.
- ``Lexicon`` reescribe palabras antes de sintetizar, sobre todo nombres en inglés
  («The Beatles» → «de bítels»). Se edita en ``pronunciacion.yaml``; el valor puede ser
  una escritura «a la española» o fonemas IPA entre ``[[ ]]``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEFAULT_LEXICON = Path(__file__).with_name("pronunciacion.yaml")
_STRESS = ("ˈ", "ˌ")


def fix_phonemes(phonemes: list[str]) -> list[str]:
    """``i ʲ ˈ`` (i átona + vocal tónica, en hiato) → ``j ˈ`` (diptongo). «río» y «Lucía» no cambian."""
    fixed: list[str] = []
    i = 0
    while i < len(phonemes):
        if phonemes[i : i + 2] == ["i", "ʲ"] and i + 2 < len(phonemes) and phonemes[i + 2] in _STRESS:
            stressed_i = bool(fixed) and fixed[-1] in _STRESS
            if not stressed_i:
                fixed.append("j")
                i += 2
                continue
        fixed.append(phonemes[i])
        i += 1
    return fixed


class Lexicon:
    def __init__(self, entries: dict[str, str]) -> None:
        self.entries = {k.strip(): str(v).strip() for k, v in entries.items() if k and str(k).strip() and v}
        self._lookup = {k.casefold(): v for k, v in self.entries.items()}
        words = sorted(self._lookup, key=len, reverse=True)  # «Guns N' Roses» antes que «Roses»
        self._regex = (
            re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in words) + r")(?!\w)", re.IGNORECASE)
            if words
            else None
        )

    @classmethod
    def load(cls, *paths: Path) -> Lexicon:
        """Carga y combina diccionarios; los posteriores tienen prioridad (los del usuario al final)."""
        entries: dict[str, str] = {}
        for path in paths:
            if not path.exists():
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                log.warning("No pude leer el diccionario de pronunciación %s: %s", path, exc)
                continue
            if not isinstance(data, dict):
                log.warning("%s debe ser una lista «palabra: pronunciación»", path)
                continue
            entries.update({str(k): str(v) for k, v in data.items() if v is not None})
        return cls(entries)

    def apply(self, text: str) -> str:
        if not self._regex:
            return text
        return self._regex.sub(lambda m: self._lookup[m.group(0).casefold()], text)
