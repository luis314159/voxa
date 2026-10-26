"""Frases en español para lo que VOXA dice en voz alta.

Los números van en dígitos (Piper los lee bien) salvo el 1, que necesita
concordar: «una hora», «un minuto».
"""

from __future__ import annotations

import math
from datetime import datetime

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _amount(value: int, singular: str, plural: str, *, feminine: bool = False) -> str:
    if value == 1:
        return f"{'una' if feminine else 'un'} {singular}"
    return f"{value} {plural}"


_PLURAL_DAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos")


def days_phrase(days: list[int] | frozenset[int]) -> str:
    """{0..4} → «de lunes a viernes», {5, 6} → «los fines de semana», {1, 3} → «los martes y jueves»."""
    chosen = sorted(set(days))
    if len(chosen) == 7:
        return "todos los días"
    if chosen == [5, 6]:
        return "los fines de semana"
    if len(chosen) >= 3 and chosen == list(range(chosen[0], chosen[-1] + 1)):
        return f"de {_WEEKDAYS[chosen[0]]} a {_WEEKDAYS[chosen[-1]]}"
    return "los " + join_words([_PLURAL_DAYS[d] for d in chosen])


def weekday_name(day: int) -> str:
    return _WEEKDAYS[day]


def join_words(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " y " + parts[-1]


def format_duration(seconds: int) -> str:
    """600 → «10 minutos», 5400 → «una hora y 30 minutos»."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(_amount(hours, "hora", "horas", feminine=True))
    if minutes:
        parts.append(_amount(minutes, "minuto", "minutos"))
    if secs or not parts:
        parts.append(_amount(secs, "segundo", "segundos"))
    return join_words(parts)


def format_remaining(seconds: float) -> str:
    """Tiempo restante redondeado hacia arriba: minutos si quedan 2 o más, si no, segundos."""
    secs = max(0, math.ceil(seconds))
    if secs >= 120:
        secs = math.ceil(secs / 60) * 60
    return format_duration(secs)


def falta(remaining: str) -> str:
    """Concuerda el verbo: «Falta un minuto», «Faltan 4 minutos»."""
    singular = remaining.startswith(("un ", "una ")) and " y " not in remaining
    return f"{'Falta' if singular else 'Faltan'} {remaining}"


def of_label(label: str) -> str:
    """«el arroz» → «del arroz», «la sopa» → «de la sopa»."""
    if label.startswith("el "):
        return "del " + label[3:]
    return "de " + label


def clock_words(hour: int, minute: int, *, on_the_hour: str = " en punto") -> str:
    """«las 3 y 25 de la tarde», «la una y media de la madrugada», «las 7 de la mañana»."""
    hour12 = hour % 12 or 12
    head = "la una" if hour12 == 1 else f"las {hour12}"
    if minute == 0:
        tail = on_the_hour
    elif minute == 15:
        tail = " y cuarto"
    elif minute == 30:
        tail = " y media"
    else:
        tail = f" y {minute}"
    if 1 <= hour < 6:
        period = "de la madrugada"
    elif 6 <= hour < 12:
        period = "de la mañana"
    elif 12 <= hour < 20:
        period = "de la tarde"
    else:
        period = "de la noche"
    return f"{head}{tail} {period}"


def time_phrase(now: datetime) -> str:
    """«Son las 3 y 25 de la tarde», «Es la una en punto de la madrugada»."""
    words = clock_words(now.hour, now.minute)
    return f"{'Es' if words.startswith('la ') else 'Son'} {words}."


def date_phrase(now: datetime) -> str:
    return f"Hoy es {_WEEKDAYS[now.weekday()]} {now.day} de {_MONTHS[now.month - 1]}."


def capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]
