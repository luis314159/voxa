"""Números y duraciones dichos en español («treinta y cinco», «hora y media»).

Trabaja sobre texto ya normalizado (minúsculas, sin acentos). Acepta tanto
palabras (Vosk) como dígitos (Whisper).
"""

from __future__ import annotations

_UNITS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiun": 21, "veintiuno": 21, "veintiuna": 21,
    "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_TENS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}
_HUNDREDS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200,
    "trescientos": 300, "trescientas": 300, "cuatrocientos": 400,
    "cuatrocientas": 400, "quinientos": 500, "quinientas": 500,
    "seiscientos": 600, "seiscientas": 600, "setecientos": 700,
    "setecientas": 700, "ochocientos": 800, "ochocientas": 800,
    "novecientos": 900, "novecientas": 900,
}

UNIT_SECONDS = {
    "hora": 3600, "horas": 3600, "h": 3600, "hr": 3600, "hrs": 3600,
    "minuto": 60, "minutos": 60, "minutito": 60, "minutitos": 60, "min": 60, "mins": 60,
    "segundo": 1, "segundos": 1, "segunditos": 1, "seg": 1, "segs": 1, "s": 1,
}
_SMALLER_UNIT = {3600: 60, 60: 1}

#: Palabras que pueden formar parte de un número o una duración (para la gramática).
NUMBER_WORDS = frozenset(_UNITS) | frozenset(_TENS) | frozenset(_HUNDREDS) | {"mil", "y"}
DURATION_WORDS = NUMBER_WORDS | frozenset(UNIT_SECONDS) | {"media", "medio", "cuarto", "cuartos", "de"}


def _as_number(token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        return None


def parse_number_at(tokens: list[str], i: int) -> tuple[float, int] | None:
    """Lee un número que empieza en ``tokens[i]``; devuelve (valor, siguiente índice)."""
    if i < len(tokens) and (digit := _as_number(tokens[i])) is not None:
        return digit, i + 1

    total = 0
    start = i
    if i < len(tokens) and tokens[i] in _HUNDREDS:
        total += _HUNDREDS[tokens[i]]
        i += 1
    if i < len(tokens) and tokens[i] in _TENS:
        total += _TENS[tokens[i]]
        i += 1
        if i + 1 < len(tokens) and tokens[i] == "y" and 1 <= _UNITS.get(tokens[i + 1], 0) <= 9:
            total += _UNITS[tokens[i + 1]]
            i += 2
    elif i < len(tokens) and tokens[i] in _UNITS:
        total += _UNITS[tokens[i]]
        i += 1
    if i < len(tokens) and tokens[i] == "mil":
        total = max(total, 1) * 1000
        i += 1
        if rest := parse_number_at(tokens, i):
            total += rest[0]
            i = rest[1]

    return (total, i) if i > start else None


def parse_number(text: str) -> int | None:
    """«treinta y cinco» → 35, «80» → 80, «setenta por ciento» → 70."""
    tokens = text.split()
    if tokens[-2:] == ["por", "ciento"]:
        tokens = tokens[:-2]
    parsed = parse_number_at(tokens, 0)
    if parsed is None or parsed[1] != len(tokens):
        return None
    return round(parsed[0])


def parse_duration(text: str, default_unit: int = 60) -> int | None:
    """Convierte una duración dicha a segundos.

    «diez minutos» → 600, «hora y media» → 5400, «un cuarto de hora» → 900,
    «dos minutos y treinta» → 150. Un número sin unidad usa ``default_unit``.
    Devuelve ``None`` si el texto no es solo una duración.
    """
    tokens = text.split()
    total = 0.0
    last_unit: int | None = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in ("y", "con"):
            i += 1
            continue
        if token in ("media", "medio"):
            if i + 1 < len(tokens) and tokens[i + 1] in UNIT_SECONDS:
                last_unit = UNIT_SECONDS[tokens[i + 1]]
                total += 0.5 * last_unit
                i += 2
                continue
            if last_unit is None:
                return None
            total += 0.5 * last_unit
            i += 1
            continue
        if token in UNIT_SECONDS:
            last_unit = UNIT_SECONDS[token]
            total += last_unit
            i += 1
            continue

        parsed = parse_number_at(tokens, i)
        if parsed is None:
            return None
        value, i = parsed
        if i < len(tokens) and tokens[i] in ("cuarto", "cuartos"):
            if tokens[i + 1 : i + 3] != ["de", "hora"]:
                return None
            last_unit = 3600
            total += value * 900
            i += 3
        elif i < len(tokens) and tokens[i] in UNIT_SECONDS:
            last_unit = UNIT_SECONDS[tokens[i]]
            total += value * last_unit
            i += 1
        elif i == len(tokens):
            unit = _SMALLER_UNIT.get(last_unit, 1) if last_unit else default_unit
            total += value * unit
        else:
            return None

    seconds = round(total)
    return seconds if seconds > 0 else None
