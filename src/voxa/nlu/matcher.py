"""Convierte texto en una intención usando la gramática de ``grammar.yaml``."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Callable

import yaml

from voxa.core.types import Intent
from voxa.nlu.days import DAY_WORDS, parse_days
from voxa.nlu.normalize import normalize, phonetic_key, restore_original, strip_accents
from voxa.nlu.numbers import CLOCK_WORDS, DURATION_WORDS, NUMBER_WORDS, parse_clock, parse_duration, parse_number

_NUMBER_TOKEN = r"\d+(?:\.\d+)?"


def _word_run(words: frozenset[str]) -> str:
    alternatives = "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True))
    word = rf"(?:{_NUMBER_TOKEN}|{alternatives})"
    return rf"{word}(?:\s+{word})*"


# Los slots con tipo solo aceptan su vocabulario; así no se «comen» el resto de la frase.
_TYPED_SLOTS = {
    "duration": _word_run(DURATION_WORDS),
    "number": _word_run(NUMBER_WORDS | {"por", "ciento"}),
    "time": _word_run(CLOCK_WORDS),
    "days": _word_run(DAY_WORDS),
}
# Slots de texto libre: si los contiene, la intención no se puede corregir con fuzzy.
_FREE_SLOTS = frozenset({"query", "name", "device"})


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Traduce la sintaxis de la gramática a una expresión regular anclada."""
    return re.compile(rf"^{_compile_sequence(strip_accents(pattern.strip()))}$")


def _split_top(src: str, sep: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(src):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(src[start:i])
            start = i + 1
    parts.append(src[start:])
    return [p for p in parts if p]


def _compile_sequence(src: str) -> str:
    # Cada elemento opcional lleva consigo su espacio, así «x [a] [b]» acepta «x», «x a», «x a b»…
    out = []
    seen_required = False
    for item in _split_top(src, " "):
        optional = item.startswith("[") and item.endswith("]")
        body = _compile_item(item[1:-1] if optional else item, group=optional)
        if optional:
            out.append(rf"(?:\s+{body})?" if seen_required else rf"(?:{body}\s+)?")
        else:
            out.append(rf"\s+{body}" if seen_required else body)
            seen_required = True
    return "".join(out)


def _compile_item(item: str, *, group: bool = False) -> str:
    if group or (item.startswith("(") and item.endswith(")")):
        inner = item if group else item[1:-1]
        return "(?:" + "|".join(_compile_sequence(alt) for alt in _split_top(inner, "|")) + ")"
    if item.startswith("{") and item.endswith("}"):
        name = item[1:-1]
        return rf"(?P<{name}>{_TYPED_SLOTS.get(name, '.+?')})"
    return re.escape(item)


@dataclass
class _Pattern:
    regex: re.Pattern[str]
    fixed: dict[str, Any]
    free_text: bool


@dataclass
class _IntentSpec:
    name: str
    patterns: list[_Pattern]
    default_unit: int = 60
    words: set[str] = field(default_factory=set)


class Matcher:
    def __init__(self, specs: list[dict[str, Any]], fuzzy_cutoff: float = 0.8) -> None:
        self._intents: list[_IntentSpec] = []
        self._vocabulary: set[str] = set(DURATION_WORDS)
        self._fuzzy_cutoff = fuzzy_cutoff
        self._phonetic: dict[str, str] | None = None
        for spec in specs:
            intent = _IntentSpec(spec["intent"], [], spec.get("default_unit", 60))
            for entry in spec["patterns"]:
                source, fixed = (entry, {}) if isinstance(entry, str) else (entry["pattern"], entry.get("set", {}))
                slots = set(re.findall(r"\{(\w+)\}", source))
                intent.patterns.append(_Pattern(compile_pattern(source), dict(fixed), bool(slots & _FREE_SLOTS)))
                literal = re.sub(r"\{\w+\}", " ", strip_accents(source))
                self._vocabulary.update(re.findall(r"[a-z]+", literal))
            self._intents.append(intent)

    def match(self, raw: str) -> Intent | None:
        text = normalize(raw)
        if not text:
            return None
        if intent := self._match_text(text, raw, allow_free_text=True):
            return intent
        # El STT a veces escribe mal una palabra («pausa» → «pauza»): se corrige
        # contra el vocabulario; el texto libre solo vale si la corrección no lo tocó.
        corrected = self._correct(text)
        if corrected != text:
            return self._match_text(corrected, raw, allow_free_text=False, heard=text)
        return None

    @property
    def vocabulary(self) -> list[str]:
        """Palabras de la gramática (sin acentos): vocabulario cerrado para Vosk."""
        return sorted(self._vocabulary)

    def understands(self, text: str) -> bool:
        return self.match(text) is not None

    def needs_accurate_stt(self, text: str) -> bool:
        """True si la frase no se entiende o trae texto libre (canción, nombre): conviene Whisper."""
        intent = self.match(text)
        return intent is None or any(slot in _FREE_SLOTS for slot in intent.slots)

    def _match_text(self, text: str, raw: str, *, allow_free_text: bool, heard: str = "") -> Intent | None:
        for spec in self._intents:
            for pattern in spec.patterns:
                m = pattern.regex.match(text)
                if m is None:
                    continue
                free = [m.group(s) for s in _FREE_SLOTS if m.groupdict().get(s)]
                if not allow_free_text and any(f" {value.strip()} " not in f" {heard} " for value in free):
                    continue  # el texto «corregido» de una canción o un nombre ya no es lo que se dijo
                slots = self._convert_slots(m.groupdict(), spec)
                if slots is None:
                    continue
                slots.update(pattern.fixed)
                for name in _FREE_SLOTS & slots.keys():
                    slots[name] = restore_original(slots[name], raw)
                return Intent(spec.name, slots, text, raw)
        return None

    @staticmethod
    def _convert_slots(groups: dict[str, str | None], spec: _IntentSpec) -> dict[str, Any] | None:
        converters: dict[str, Callable[[str], Any]] = {
            "duration": lambda v: parse_duration(v, spec.default_unit),
            "number": parse_number,
            "time": parse_clock,
            "days": parse_days,
        }
        slots: dict[str, Any] = {}
        for name, value in groups.items():
            if value is None:
                continue
            value = value.strip()
            if name in converters:
                converted = converters[name](value)
                if converted is None:
                    return None
                slots[name] = converted
            else:
                slots[name] = value
        return slots

    def _correct(self, text: str) -> str:
        # Se compara por sonido (b/v, s/z/c…), no por letras: así se equivoca el STT en español.
        if self._phonetic is None:
            self._phonetic = {}
            for word in sorted(self._vocabulary):
                self._phonetic.setdefault(phonetic_key(word), word)
        words = []
        for word in text.split():
            if word in self._vocabulary or word.replace(".", "").isdigit():
                words.append(word)
                continue
            key = phonetic_key(word)
            if key in self._phonetic:
                words.append(self._phonetic[key])
                continue
            close = difflib.get_close_matches(key, self._phonetic, n=1, cutoff=self._fuzzy_cutoff)
            words.append(self._phonetic[close[0]] if close else word)
        return " ".join(words)


def load_matcher(path: Path | None = None) -> Matcher:
    if path is None:
        source = resources.files("voxa.nlu").joinpath("grammar.yaml").read_text(encoding="utf-8")
    else:
        source = path.read_text(encoding="utf-8")
    return Matcher(yaml.safe_load(source))
