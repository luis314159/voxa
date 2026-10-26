"""Días de la semana en una orden: «de lunes a viernes», «los martes y jueves», «el viernes»."""

from __future__ import annotations

WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_DAY = {name: n for n, name in enumerate(WEEKDAYS)} | {"sabados": 5, "domingos": 6}
EVERY_DAY = frozenset(range(7))
WORKDAYS = frozenset(range(5))
WEEKEND = frozenset({5, 6})

DAY_WORDS = frozenset(_DAY) | {
    "dias", "dia", "diario", "diariamente", "semana", "fin", "fines", "entre", "todos", "todas", "cada",
    "los", "el", "este", "esta", "proximo", "que", "viene", "y", "a", "de", "al",
}
_EVERY = {"los", "cada", "todos", "todas"}


def parse_days(text: str) -> tuple[frozenset[int], bool] | None:
    """Días (0 = lunes) y si se repite cada semana; ``None`` si no dice ningún día.

    «de lunes a viernes» / «entre semana» → L–V, cada semana; «los fines de semana» → S–D;
    «todos los días» / «diario» → los 7; «los martes y jueves» → M y J, cada semana;
    «el viernes» / «este viernes» → solo el próximo viernes.
    """
    words = text.split()
    if not words:
        return None
    joined = f" {text} "
    if "diario" in words or "diariamente" in words or {"todos", "dias"} <= set(words) or " cada dia " in joined:
        return EVERY_DAY, True
    if " entre semana " in joined:
        return WORKDAYS, True
    if " fin de semana " in joined or " fines de semana " in joined:
        return WEEKEND, True
    days = [(n, w) for n, w in enumerate(words) if w in _DAY]
    if not days:
        return None
    if len(days) == 2 and "a" in words[days[0][0] + 1 : days[1][0]]:
        # «de lunes a viernes», «de viernes a domingo» (puede dar la vuelta a la semana)
        start, end = _DAY[days[0][1]], _DAY[days[1][1]]
        span = range(start, end + 1) if start <= end else [*range(start, 7), *range(0, end + 1)]
        return frozenset(span), True
    chosen = frozenset(_DAY[w] for _, w in days)
    repeat = bool(_EVERY & set(words)) or any(w in ("sabados", "domingos") for _, w in days)
    return chosen, repeat
