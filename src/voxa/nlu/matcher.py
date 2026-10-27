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
from voxa.nlu import days, days_en, numbers, numbers_en
from voxa.nlu.normalize import normalize, phonetic_key, restore_original, strip_accents

_NUMBER_TOKEN = r"\d+(?:\.\d+)?"


def _word_run(words: frozenset[str]) -> str:
    alternatives = "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True))
    word = rf"(?:{_NUMBER_TOKEN}|{alternatives})"
    return rf"{word}(?:\s+{word})*"


@dataclass(frozen=True)
class Language:
    """Lo que cambia con el idioma: el vocabulario de números, horas y días, y cómo se leen."""

    code: str
    grammar: str
    duration_words: frozenset[str]
    number_words: frozenset[str]
    clock_words: frozenset[str]
    day_words: frozenset[str]
    parse_duration: Callable[[str, int], int | None]
    parse_number: Callable[[str], int | None]
    parse_clock: Callable[[str], tuple[int, int, str | None] | None]
    parse_days: Callable[[str], tuple[frozenset[int], bool] | None]
    phonetic: bool  # corregir palabras por cómo suenan (solo español)

    def typed_slots(self) -> dict[str, str]:
        # Los slots con tipo solo aceptan su vocabulario; así no se «comen» el resto de la frase.
        return {
            "duration": _word_run(self.duration_words),
            "number": _word_run(self.number_words),
            "time": _word_run(self.clock_words),
            "days": _word_run(self.day_words),
        }


LANGUAGES = {
    "es": Language("es", "grammar.yaml", numbers.DURATION_WORDS, numbers.NUMBER_WORDS | {"por", "ciento"},
                   numbers.CLOCK_WORDS, days.DAY_WORDS, numbers.parse_duration, numbers.parse_number,
                   numbers.parse_clock, days.parse_days, phonetic=True),
    "en": Language("en", "grammar_en.yaml", numbers_en.DURATION_WORDS, numbers_en.NUMBER_WORDS,
                   numbers_en.CLOCK_WORDS, days_en.DAY_WORDS, numbers_en.parse_duration, numbers_en.parse_number,
                   numbers_en.parse_clock, days_en.parse_days, phonetic=False),
}
_TYPED_SLOTS = LANGUAGES["es"].typed_slots()
# Slots de texto libre: si los contiene, la intención no se puede corregir con fuzzy.
_FREE_SLOTS = frozenset({"query", "name", "device", "person"})


def compile_pattern(pattern: str, typed: dict[str, str] | None = None) -> re.Pattern[str]:
    """Traduce la sintaxis de la gramática a una expresión regular anclada."""
    return re.compile(rf"^{_compile_sequence(strip_accents(pattern.strip()), typed or _TYPED_SLOTS)}$")


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


def _compile_sequence(src: str, typed: dict[str, str]) -> str:
    # Cada elemento opcional lleva consigo su espacio, así «x [a] [b]» acepta «x», «x a», «x a b»…
    out = []
    seen_required = False
    for item in _split_top(src, " "):
        optional = item.startswith("[") and item.endswith("]")
        body = _compile_item(item[1:-1] if optional else item, typed, group=optional)
        if optional:
            out.append(rf"(?:\s+{body})?" if seen_required else rf"(?:{body}\s+)?")
        else:
            out.append(rf"\s+{body}" if seen_required else body)
            seen_required = True
    return "".join(out)


def _compile_item(item: str, typed: dict[str, str], *, group: bool = False) -> str:
    if group or (item.startswith("(") and item.endswith(")")):
        inner = item if group else item[1:-1]
        return "(?:" + "|".join(_compile_sequence(alt, typed) for alt in _split_top(inner, "|")) + ")"
    if item.startswith("{") and item.endswith("}"):
        name = item[1:-1]
        return rf"(?P<{name}>{typed.get(name, '.+?')})"
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
    def __init__(self, specs: list[dict[str, Any]], fuzzy_cutoff: float = 0.8, language: str = "es") -> None:
        self.language = LANGUAGES[language]
        typed = self.language.typed_slots()
        self._intents: list[_IntentSpec] = []
        self._vocabulary: set[str] = set(self.language.duration_words)
        self._fuzzy_cutoff = fuzzy_cutoff
        self._phonetic: dict[str, str] | None = None
        for spec in specs:
            intent = _IntentSpec(spec["intent"], [], spec.get("default_unit", 60))
            for entry in spec["patterns"]:
                source, fixed = (entry, {}) if isinstance(entry, str) else (entry["pattern"], entry.get("set", {}))
                slots = set(re.findall(r"\{(\w+)\}", source))
                intent.patterns.append(_Pattern(compile_pattern(source, typed), dict(fixed), bool(slots & _FREE_SLOTS)))
                literal = re.sub(r"\{\w+\}", " ", strip_accents(source))
                self._vocabulary.update(re.findall(r"[a-z]+", literal))
            self._intents.append(intent)

    def match(self, raw: str) -> Intent | None:
        text = normalize(raw, self.language.code)
        if not text:
            return None
        if intent := self._match_text(text, raw, allow_free_text=True):
            return intent
        if not self.language.phonetic:
            return None
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
                slots = self._convert_slots(m.groupdict(), spec, self.language)
                if slots is None:
                    continue
                slots.update(pattern.fixed)
                for name in _FREE_SLOTS & slots.keys():
                    slots[name] = restore_original(slots[name], raw)
                return Intent(spec.name, slots, text, raw)
        return None

    @staticmethod
    def _convert_slots(groups: dict[str, str | None], spec: _IntentSpec, language: Language) -> dict[str, Any] | None:
        converters: dict[str, Callable[[str], Any]] = {
            "duration": lambda v: language.parse_duration(v, spec.default_unit),
            "number": language.parse_number,
            "time": language.parse_clock,
            "days": language.parse_days,
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


def load_matcher(path: Path | None = None, language: str = "es") -> Matcher:
    if path is None:
        grammar = LANGUAGES[language].grammar
        source = resources.files("voxa.nlu").joinpath(grammar).read_text(encoding="utf-8")
    else:
        source = path.read_text(encoding="utf-8")
    return Matcher(yaml.safe_load(source), language=language)
