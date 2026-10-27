"""Frases para lo que VOXA dice en voz alta (en el idioma de la casa: ``voxa.i18n``).

Los números van en dígitos (Piper los lee bien) salvo el 1, que necesita
concordar: «una hora», «un minuto» / «an hour», «a minute».
"""

from __future__ import annotations

import math
from datetime import datetime

from voxa.i18n import english

_WEEKDAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December")

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _amount(value: int, singular: str, plural: str, *, feminine: bool = False) -> str:
    if english():
        return f"{'an' if singular == 'hour' else 'a'} {singular}" if value == 1 else f"{value} {plural}"
    if value == 1:
        return f"{'una' if feminine else 'un'} {singular}"
    return f"{value} {plural}"


_PLURAL_DAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos")


def days_phrase(days: list[int] | frozenset[int]) -> str:
    """{0..4} → «de lunes a viernes», {5, 6} → «los fines de semana», {1, 3} → «los martes y jueves»."""
    chosen = sorted(set(days))
    if english():
        if len(chosen) == 7:
            return "every day"
        if chosen == [5, 6]:
            return "on weekends"
        if len(chosen) >= 3 and chosen == list(range(chosen[0], chosen[-1] + 1)):
            return f"{_WEEKDAYS_EN[chosen[0]]} through {_WEEKDAYS_EN[chosen[-1]]}"
        return "on " + join_words([_WEEKDAYS_EN[d] + "s" for d in chosen])
    if len(chosen) == 7:
        return "todos los días"
    if chosen == [5, 6]:
        return "los fines de semana"
    if len(chosen) >= 3 and chosen == list(range(chosen[0], chosen[-1] + 1)):
        return f"de {_WEEKDAYS[chosen[0]]} a {_WEEKDAYS[chosen[-1]]}"
    return "los " + join_words([_PLURAL_DAYS[d] for d in chosen])


def weekday_name(day: int) -> str:
    return _WEEKDAYS_EN[day] if english() else _WEEKDAYS[day]


def join_words(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + (" and " if english() else " y ") + parts[-1]


def format_duration(seconds: int) -> str:
    """600 → «10 minutos», 5400 → «una hora y 30 minutos»."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    names = (("hour", "hours"), ("minute", "minutes"), ("second", "seconds")) if english() else (
        ("hora", "horas"), ("minuto", "minutos"), ("segundo", "segundos"))
    if hours:
        parts.append(_amount(hours, *names[0], feminine=True))
    if minutes:
        parts.append(_amount(minutes, *names[1]))
    if secs or not parts:
        parts.append(_amount(secs, *names[2]))
    return join_words(parts)


def format_remaining(seconds: float) -> str:
    """Tiempo restante redondeado hacia arriba: minutos si quedan 2 o más, si no, segundos."""
    secs = max(0, math.ceil(seconds))
    if secs >= 120:
        secs = math.ceil(secs / 60) * 60
    return format_duration(secs)


def falta(remaining: str) -> str:
    """Concuerda el verbo: «Falta un minuto», «Faltan 4 minutos» («4 minutes left»)."""
    if english():
        return f"{remaining} left"
    singular = remaining.startswith(("un ", "una ")) and " y " not in remaining
    return f"{'Falta' if singular else 'Faltan'} {remaining}"


def of_label(label: str) -> str:
    """«el arroz» → «del arroz», «la sopa» → «de la sopa» («for rice»)."""
    if english():
        return f"for {label}"
    if label.startswith("el "):
        return "del " + label[3:]
    return "de " + label


def clock_words(hour: int, minute: int, *, on_the_hour: str = " en punto") -> str:
    """«las 3 y 25 de la tarde», «la una y media de la madrugada», «las 7 de la mañana»."""
    hour12 = hour % 12 or 12
    if english():  # «7:30 in the evening», «7 in the morning», «noon»
        if (hour, minute) == (12, 0):
            return "noon"
        oclock = " o'clock" if on_the_hour else ""
        time = f"{hour12}:{minute:02d}" if minute else f"{hour12}{oclock}"
        period = "at night" if hour >= 21 or hour < 5 else "in the morning" if hour < 12 else (
            "in the afternoon" if hour < 18 else "in the evening")
        return f"{time} {period}"
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
    if english():
        return f"It's {words}."
    return f"{'Es' if words.startswith('la ') else 'Son'} {words}."


def date_phrase(now: datetime) -> str:
    if english():
        return f"Today is {_WEEKDAYS_EN[now.weekday()]}, {_MONTHS_EN[now.month - 1]} {now.day}."
    return f"Hoy es {_WEEKDAYS[now.weekday()]} {now.day} de {_MONTHS[now.month - 1]}."


def capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]
