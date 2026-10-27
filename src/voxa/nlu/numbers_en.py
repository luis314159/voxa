"""Numbers, durations and clock times said in English («thirty five», «an hour and a half», «7 30 pm»).

Works on normalized text (lowercase, no punctuation). Accepts words (Vosk) and digits (Whisper).
The clock periods use the same names as the Spanish parser («manana», «tarde», «noche», «dia»):
the timer skill understands those.
"""

from __future__ import annotations

_UNITS = {
    "zero": 0, "oh": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

UNIT_SECONDS = {
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600, "h": 3600,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "second": 1, "seconds": 1, "sec": 1, "secs": 1, "s": 1,
}
_SMALLER_UNIT = {3600: 60, 60: 1}

NUMBER_WORDS = frozenset(_UNITS) | frozenset(_TENS) | {"hundred", "and", "percent"}
DURATION_WORDS = NUMBER_WORDS | frozenset(UNIT_SECONDS) | {"half", "quarter", "of", "and"}


def _as_number(token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        return None


def parse_number_at(tokens: list[str], i: int) -> tuple[float, int] | None:
    if i < len(tokens) and (digit := _as_number(tokens[i])) is not None:
        return digit, i + 1
    total, start = 0, i
    if i < len(tokens) and tokens[i] in _TENS:
        total += _TENS[tokens[i]]
        i += 1
        if i < len(tokens) and 1 <= _UNITS.get(tokens[i], 0) <= 9 and tokens[i] not in ("a", "an"):
            total += _UNITS[tokens[i]]
            i += 1
    elif i < len(tokens) and tokens[i] in _UNITS:
        total += _UNITS[tokens[i]]
        i += 1
    if i < len(tokens) and tokens[i] == "hundred":
        total = max(total, 1) * 100
        i += 1
        if i < len(tokens) and tokens[i] == "and":
            i += 1
        if rest := parse_number_at(tokens, i):
            total += rest[0]
            i = rest[1]
    return (total, i) if i > start else None


def parse_number(text: str) -> int | None:
    """«thirty five» → 35, «80» → 80, «seventy percent» → 70."""
    tokens = [t for t in text.split() if t != "percent"]
    parsed = parse_number_at(tokens, 0) if tokens else None
    if parsed is None or parsed[1] != len(tokens):
        return None
    return round(parsed[0])


def parse_duration(text: str, default_unit: int = 60) -> int | None:
    """«ten minutes» → 600, «an hour and a half» → 5400, «half an hour» → 1800, «a quarter of an hour» → 900."""
    tokens = text.split()
    total = 0.0
    last_unit: int | None = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "and":
            i += 1
            continue
        if token == "half":
            # «half an hour», «an hour and a half»
            j = i + 1
            if j < len(tokens) and tokens[j] in ("a", "an"):
                j += 1
            if j < len(tokens) and tokens[j] in UNIT_SECONDS:
                last_unit = UNIT_SECONDS[tokens[j]]
                total += 0.5 * last_unit
                i = j + 1
                continue
            if last_unit is None:
                return None
            total += 0.5 * last_unit
            i += 1
            continue
        if token in ("a", "an") and i + 1 < len(tokens) and tokens[i + 1] in ("half", "quarter"):
            i += 1
            continue
        if token == "quarter":
            if tokens[i + 1 : i + 3] in (["of", "an"], ["of", "a"]) and tokens[i + 3 : i + 4] == ["hour"]:
                total += 900
                last_unit = 3600
                i += 4
                continue
            return None
        if token in UNIT_SECONDS:
            last_unit = UNIT_SECONDS[token]
            total += last_unit
            i += 1
            continue
        parsed = parse_number_at(tokens, i)
        if parsed is None:
            return None
        value, i = parsed
        if i < len(tokens) and tokens[i] in UNIT_SECONDS:
            last_unit = UNIT_SECONDS[tokens[i]]
            total += value * last_unit
            i += 1
        elif i == len(tokens):
            total += value * (_SMALLER_UNIT.get(last_unit, 1) if last_unit else default_unit)
        else:
            return None
    seconds = round(total)
    return seconds if seconds > 0 else None


CLOCK_WORDS = NUMBER_WORDS | {
    "half", "quarter", "past", "to", "oclock", "o", "clock", "am", "pm", "a", "p", "m", "in", "the",
    "morning", "afternoon", "evening", "at", "night", "noon", "midnight", "tonight",
}
_PERIODS = {
    ("in", "the", "morning"): "manana", ("in", "the", "afternoon"): "tarde", ("in", "the", "evening"): "noche",
    ("at", "night"): "noche", ("tonight",): "noche", ("am",): "manana", ("a", "m"): "manana",
    ("pm",): "tarde", ("p", "m"): "tarde",
}


def parse_clock(text: str) -> tuple[int, int, str | None] | None:
    """«seven thirty pm» → (7, 30, "tarde"); «half past 7» → (7, 30, None); «quarter to 8» → (8, -15, None)."""
    tokens = text.split()
    if tokens in (["noon"], ["midday"]):
        return 12, 0, "dia"
    if tokens == ["midnight"]:
        return 0, 0, "noche"
    minute_first = None
    if tokens[:2] in (["half", "past"],):
        minute_first, tokens = 30, tokens[2:]
    elif tokens[:3] in (["a", "quarter", "past"], ["a", "quarter", "to"]) or tokens[:2] in (["quarter", "past"], ["quarter", "to"]):
        skip = 3 if tokens[0] == "a" else 2
        minute_first, tokens = (15 if tokens[skip - 1] == "past" else -15), tokens[skip:]
    elif len(tokens) > 2 and tokens[1] in ("past", "to") or len(tokens) > 3 and tokens[2] in ("past", "to"):
        parsed = parse_number_at(tokens, 0)
        if parsed is None or not 0 < parsed[0] < 60:
            return None
        rest = tokens[parsed[1]:]
        if rest[:1] == ["minutes"]:
            rest = rest[1:]
        if rest[:1] not in (["past"], ["to"]):
            return None
        minute_first = int(parsed[0]) * (1 if rest[0] == "past" else -1)
        tokens = rest[1:]
    parsed = parse_number_at(tokens, 0)
    if parsed is None or parsed[0] != int(parsed[0]) or not 0 <= parsed[0] <= 24:
        return None
    hour, i = int(parsed[0]) % 24, parsed[1]
    minute = minute_first or 0
    if minute_first is None:
        if tokens[i : i + 1] == ["oclock"] or tokens[i : i + 2] == ["o", "clock"]:
            i += 1 if tokens[i] == "oclock" else 2
        elif tokens[i : i + 1] == ["oh"] and (number := parse_number_at(tokens, i + 1)) and 0 < number[0] < 10:
            minute, i = int(number[0]), number[1]  # «seven oh five»
        elif (number := parse_number_at(tokens, i)) and 0 <= number[0] < 60 and tokens[i] not in ("a", "an"):
            minute, i = int(number[0]), number[1]
    period = None
    for words, name in _PERIODS.items():
        if tuple(tokens[i : i + len(words)]) == words:
            period, i = name, i + len(words)
            break
    if i != len(tokens):
        return None
    return hour, minute, period
