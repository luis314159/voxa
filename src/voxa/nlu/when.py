"""El día y la hora de una cita dicha de corrido: «dentista el martes a las 5» → «dentista», martes 17:00.

Para «agrega … al calendario». Entiende hoy, mañana, pasado mañana, un día de la semana («el martes»,
«el próximo viernes») o una fecha («el 3 de noviembre», «el 15»), y la hora («a las 5 de la tarde»,
«a las 10 y media»). Sin hora, la cita es de todo el día. En inglés: «dentist on tuesday at 5 pm»,
«tomorrow at noon», «on november 3rd».

Una hora sin «de la mañana/tarde» se toma como la de una cita: de 1 a 7, de la tarde; de 8 a 11, de
la mañana. VOXA la repite al confirmar, así que si no era, se corrige.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from voxa.nlu import numbers, numbers_en
from voxa.nlu.normalize import strip_accents

_WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_ORDINAL = re.compile(r"^(\d{1,2})(?:st|nd|rd|th|o|ro|vo)?$")
# Palabras que sobran alrededor del título: «agrega [la] junta [para] el martes».
_EDGE_WORDS = {"el", "la", "los", "las", "un", "una", "para", "de", "que", "en", "on", "the", "a", "an", "for", "at", "y", "and"}


@dataclass(frozen=True)
class When:
    title: str
    day: date
    hour: int | None = None
    minute: int = 0

    @property
    def all_day(self) -> bool:
        return self.hour is None

    @property
    def start(self) -> datetime:
        return datetime(self.day.year, self.day.month, self.day.day, self.hour or 0, self.minute)


def parse_when(text: str, now: datetime, *, english: bool = False) -> When | None:
    """El título y cuándo; ``None`` si no dice ningún día ni hora."""
    words = text.split()
    plain = [strip_accents(w.lower()).strip(",.") for w in words]
    used: set[int] = set()
    day = _day(plain, used, now.date())
    clock = _clock(plain, used, english)
    if day is None and clock is None:
        return None
    if day is None:  # solo hora: hoy, o mañana si ya pasó
        day = now.date()
        if clock is not None and (_hour_of(clock), clock[1]) <= (now.hour, now.minute):
            day += timedelta(days=1)
    title_words = [w for i, w in enumerate(words) if i not in used]
    while title_words and strip_accents(title_words[-1].lower()).strip(",.") in _EDGE_WORDS:
        title_words.pop()
    while title_words and strip_accents(title_words[0].lower()).strip(",.") in _EDGE_WORDS:
        title_words.pop(0)
    title = " ".join(title_words).strip(" ,.")
    if not title:
        return None
    if clock is None:
        return When(title, day)
    return When(title, day, _hour_of(clock), clock[1])


def _hour_of(clock: tuple[int, int, str | None]) -> int:
    hour, _, period = clock
    if period in ("tarde", "noche") and hour < 12:
        return hour + 12
    if period in ("manana", "madrugada") and hour == 12:
        return 0
    if period is None and 1 <= hour <= 7:
        return hour + 12  # una cita «a las 5» es de la tarde
    return hour % 24


def _day(plain: list[str], used: set[int], today: date) -> date | None:
    for phrase, days in (("pasado manana", 2), ("day after tomorrow", 2), ("manana", 1), ("tomorrow", 1),
                         ("hoy", 0), ("today", 0), ("tonight", 0)):
        n = len(phrase.split())
        for i in range(len(plain) - n + 1):
            if " ".join(plain[i:i + n]) != phrase:
                continue
            if phrase == "manana" and i >= 2 and plain[i - 1] == "la" and plain[i - 2] in ("de", "en", "por"):
                continue  # «a las 9 de la mañana» es la hora, no el día
            used.update(range(i, i + n))
            _take_before(plain, used, i, {"el", "on", "for", "para"})
            return today + timedelta(days=days)
    for i, word in enumerate(plain):
        if word in _WEEKDAYS:
            used.add(i)
            _take_before(plain, used, i, {"el", "este", "esta", "proximo", "siguiente", "on", "this", "next", "para"})
            ahead = (_WEEKDAYS[word] - today.weekday()) % 7 or 7  # «el martes» dicho en martes: el que viene
            return today + timedelta(days=ahead)
    for i, word in enumerate(plain):  # «el 3 de noviembre», «november 3rd», «el 15»
        if word in _MONTHS:
            month = _MONTHS[word]
            number = _number_near(plain, i)
            if number is None:
                continue
            index, value = number
            used.update({i, index})
            for j in (i - 1, i + 1, index - 1):
                if 0 <= j < len(plain) and plain[j] in ("de", "of", "el", "on", "the"):
                    used.add(j)
            return _next_date(today, month, value)
    for i, word in enumerate(plain):
        if word in ("el", "the") and i + 1 < len(plain) and (m := _ORDINAL.match(plain[i + 1])) and 1 <= int(m.group(1)) <= 31:
            if i + 2 < len(plain) and plain[i + 2] in ("minutos", "minutes", "horas", "hours"):
                continue
            used.update({i, i + 1})
            _take_before(plain, used, i, {"on", "para"})
            day = int(m.group(1))
            month = today.month if day >= today.day else today.month % 12 + 1
            return _next_date(today, month, day)
    return None


def _number_near(plain: list[str], i: int) -> tuple[int, int] | None:
    for j in (i - 2, i + 1, i - 1):  # «3 de noviembre», «november 3rd»
        if 0 <= j < len(plain) and (m := _ORDINAL.match(plain[j])) and 1 <= int(m.group(1)) <= 31:
            return j, int(m.group(1))
    return None


def _next_date(today: date, month: int, day: int) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= today:
            return candidate
    return None


def _take_before(plain: list[str], used: set[int], i: int, words: set[str]) -> None:
    j = i - 1
    while j >= 0 and plain[j] in words and j not in used:
        used.add(j)
        j -= 1


def _clock(plain: list[str], used: set[int], english: bool) -> tuple[int, int, str | None] | None:
    parse = numbers_en.parse_clock if english else numbers.parse_clock
    starts = ("at",) if english else ("a", "al")
    for i, word in enumerate(plain):
        if word not in starts or i in used:
            continue
        first = i + 1
        if not english and first < len(plain) and plain[first] in ("la", "las"):
            first += 1
        # La frase de hora más larga que se entienda: «5 y media de la tarde».
        for end in range(len(plain), first, -1):
            if used & set(range(first, end)):
                continue
            clock = parse(" ".join(plain[first:end]))
            if clock is not None:
                used.update(range(i, end))
                return clock
    for i, word in enumerate(plain):  # «mediodía», «noon», sin «a las»
        if word in ("mediodia", "noon") and i not in used:
            used.add(i)
            _take_before(plain, used, i, {"al", "a", "at"})
            return 12, 0, "dia"
    return None
