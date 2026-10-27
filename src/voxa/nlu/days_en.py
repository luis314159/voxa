"""Days of the week in an English command: «monday to friday», «on tuesdays and thursdays», «on friday»."""

from __future__ import annotations

from voxa.nlu.days import EVERY_DAY, WEEKEND, WORKDAYS

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY = {name: n for n, name in enumerate(WEEKDAYS)} | {f"{name}s": n for n, name in enumerate(WEEKDAYS)}

DAY_WORDS = frozenset(_DAY) | {
    "day", "days", "daily", "every", "weekday", "weekdays", "weekend", "weekends", "on", "the", "this",
    "next", "and", "to", "through", "from", "each",
}


def parse_days(text: str) -> tuple[frozenset[int], bool] | None:
    """Days (0 = Monday) and whether it repeats weekly; ``None`` if no day is said."""
    words = text.split()
    if not words:
        return None
    if "daily" in words or {"every", "day"} <= set(words):
        return EVERY_DAY, True
    if "weekdays" in words or "weekday" in words:
        return WORKDAYS, True
    if "weekend" in words or "weekends" in words:
        return WEEKEND, True
    days = [(n, w) for n, w in enumerate(words) if w in _DAY]
    if not days:
        return None
    if len(days) == 2 and {"to", "through"} & set(words[days[0][0] + 1 : days[1][0]]):
        start, end = _DAY[days[0][1]], _DAY[days[1][1]]
        span = range(start, end + 1) if start <= end else [*range(start, 7), *range(0, end + 1)]
        return frozenset(span), True
    chosen = frozenset(_DAY[w] for _, w in days)
    repeat = "every" in words or "each" in words or any(w.endswith("s") for _, w in days)
    return chosen, repeat
