from pathlib import Path

import pytest
import yaml

from voxa.nlu import load_matcher, normalize
from voxa.nlu.matcher import compile_pattern
from voxa.nlu.numbers import parse_duration, parse_number

CORPUS = yaml.safe_load((Path(__file__).parent / "data" / "utterances.yaml").read_text(encoding="utf-8"))
MATCHER = load_matcher()


@pytest.mark.parametrize("case", CORPUS, ids=[c["text"] or "<vacío>" for c in CORPUS])
def test_corpus(case):
    intent = MATCHER.match(case["text"])
    if case["intent"] is None:
        assert intent is None
        return
    assert intent is not None, f"no se reconoció «{case['text']}»"
    assert intent.name == case["intent"]
    for slot, expected in (case.get("slots") or {}).items():
        assert intent.slots.get(slot) == expected, slot


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hey Voxa, ¿qué hora es?", "que hora es"),
        ("OYE VOXA pon música, por favor", "pon musica"),
        ("este... a ver, súbele", "subele"),
        ("temporizador de 1,5 horas", "temporizador de 1.5 horas"),
        ("La niña", "la nina"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("diez minutos", 600),
        ("un minuto", 60),
        ("media hora", 1800),
        ("hora y media", 5400),
        ("una hora y media", 5400),
        ("un cuarto de hora", 900),
        ("tres cuartos de hora", 2700),
        ("dos horas y quince minutos", 8100),
        ("un minuto y medio", 90),
        ("2 minutos y treinta", 150),
        ("1.5 horas", 5400),
        ("treinta y cinco segundos", 35),
        ("diez", 600),
        ("cinco minutitos", 300),
    ],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "arroz", "minutos de arroz", "cero minutos"])
def test_parse_duration_rejects(text):
    assert parse_duration(text) is None


@pytest.mark.parametrize(
    ("text", "value"),
    [("treinta", 30), ("treinta y cinco", 35), ("80", 80), ("cien", 100), ("ciento veinte", 120),
     ("setenta por ciento", 70), ("dos mil", 2000), ("veintidos", 22)],
)
def test_parse_number(text, value):
    assert parse_number(text) == value


def test_optional_elements_attach_their_own_space():
    regex = compile_pattern("x [a] [b]")
    assert all(regex.match(t) for t in ("x", "x a", "x b", "x a b"))
    assert not regex.match("xa")
    regex = compile_pattern("[a] [b] c")
    assert all(regex.match(t) for t in ("c", "a c", "b c", "a b c"))


def test_fuzzy_correction_does_not_touch_free_text():
    # «soda estereo» no debe «corregirse» hacia palabras de la gramática.
    intent = MATCHER.match("pon soda estereo")
    assert intent.name == "music.play"
    assert intent.slots["query"] == "soda estereo"
