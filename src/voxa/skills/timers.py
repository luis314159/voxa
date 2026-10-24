from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from voxa.core.phrases import capitalize, clock_words, falta, format_duration, format_remaining, join_words, of_label
from voxa.core.types import OK, Intent, Response
from voxa.state.timers import Timer, TimerManager, label_key

_MAX_SECONDS = 24 * 3600
_SOON = timedelta(seconds=30)  # «a las 7» dicho a las 6:59:50 es para mañana, no para dentro de 10 s


def ring_phrase(timer: Timer) -> str:
    if timer.is_reminder:
        if timer.label:
            return f"Te recuerdo: {timer.label}."
        at = datetime.fromtimestamp(timer.ends_at)
        return f"¡Son {clock_words(at.hour, at.minute, on_the_hour='')}!"
    if timer.label:
        return f"¡Terminó el temporizador {of_label(timer.label)}!"
    return f"¡Terminaron los {format_duration(timer.duration)}!"


def _hours(hour: int, period: str | None) -> list[int] | None:
    """Horas del día (0–23) que puede querer decir «las 8» según «de la mañana/tarde/noche»."""
    if period is None:
        return [hour] if hour == 0 or hour >= 13 else [hour % 12, hour % 12 + 12]
    if hour > 12:
        return [hour] if period in ("tarde", "noche") else None
    return {
        "manana": [hour],
        "madrugada": [hour % 12],
        "dia": [hour if hour >= 11 else hour + 12],
        "tarde": [hour % 12 + 12],
        "noche": [hour % 12 + 12 if hour >= 6 else hour % 12],
    }[period]


def next_occurrence(
    clock: tuple[int, int, str | None], now: datetime, *, tomorrow: bool = False
) -> datetime | None:
    """La próxima vez que serán «las 8 y media» (o mañana, si se pidió)."""
    hour, minute, period = clock
    hours = _hours(hour, period)
    if hours is None:
        return None
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = sorted(
        day + timedelta(days=d, hours=h, minutes=minute) for d in (0, 1, 2) for h in hours
    )
    if tomorrow:
        start = day + timedelta(days=1)
        return next((c for c in candidates if c >= start), None)
    return next((c for c in candidates if c > now + _SOON), None)


class TimerSkill:
    def __init__(self, timers: TimerManager, now: Callable[[], datetime] = datetime.now) -> None:
        self.timers = timers
        self._now = now

    async def handle(self, intent: Intent) -> Response:
        match intent.name:
            case "timer.set":
                return self._set(intent.slots["duration"], intent.slots.get("name"))
            case "timer.remind":
                return self._remind(intent.slots["time"], intent.slots.get("name"), intent.slots.get("day") == "manana")
            case "timer.query":
                return self._query(intent.slots.get("name"))
            case "timer.cancel":
                return self._cancel(intent.slots.get("name"))
            case "timer.cancel_all":
                count = self.timers.cancel_all()
                return Response("Cancelé todos los temporizadores." if count else "No hay temporizadores.")
            case "timer.stop_alarm":
                return self.stop_alarm()
        return Response("Todavía no sé hacer eso con los temporizadores.", sound="error")

    def stop_alarm(self) -> Response:
        if not self.timers.stop_ringing():
            return Response("No hay ninguna alarma sonando.")
        return OK

    def _set(self, seconds: int, label: str | None) -> Response:
        if seconds > _MAX_SECONDS:
            return Response("Puedo poner temporizadores de hasta 24 horas.", sound="error")
        label = label.strip() if label else None
        self.timers.add(seconds, label)
        said = format_duration(seconds)
        return Response(capitalize(f"{said} para {label}." if label else f"{said}. Empezando."))

    def _remind(self, clock: tuple[int, int, str | None], label: str | None, tomorrow: bool) -> Response:
        now = self._now()
        at = next_occurrence(clock, now, tomorrow=tomorrow)
        if at is None:
            return Response("No entendí la hora. Prueba con «a las 8 de la noche».", sound="error")
        label = label.strip() if label else None
        self.timers.add_at(at.timestamp(), label)
        hour = clock_words(at.hour, at.minute, on_the_hour="")  # «las 8 de la noche»
        when = f"mañana a {hour}" if at.date() > now.date() else f"a {hour}"
        if label:
            return Response(capitalize(f"{when} te recuerdo {label}."))
        return Response(f"Alarma para {when.removeprefix('a ')}.")

    def _resolve(self, name: str | None) -> tuple[list[Timer], Response | None]:
        active = self.timers.active
        if not active:
            return [], Response("No hay temporizadores.")
        if name and label_key(name) not in ("temporizador", "timer", "alarma", "recordatorio"):
            found = self.timers.find(name)
            if not found:
                return [], Response(f"No encontré un temporizador {of_label(name)}.")
            return found, None
        return active, None

    def _query(self, name: str | None) -> Response:
        timers, problem = self._resolve(name)
        if problem:
            return problem
        if len(timers) == 1 and not timers[0].is_reminder:
            timer = timers[0]
            suffix = f" para {timer.label}" if timer.label and len(self.timers.active) > 1 else ""
            return Response(f"{falta(format_remaining(self.timers.remaining(timer)))}{suffix}.")
        parts = [self._describe(t) for t in timers]
        if len(parts) == 1:
            return Response(capitalize(parts[0]) + ".")
        return Response(f"Tienes {len(timers)}: {join_words(parts)}.")

    def _describe(self, timer: Timer) -> str:
        if timer.is_reminder:  # «sacar la basura, a las 8 de la noche»
            at = datetime.fromtimestamp(timer.ends_at)
            day = "mañana " if at.date() > self._now().date() else ""
            return f"{timer.label or 'alarma'}, {day}a {clock_words(at.hour, at.minute, on_the_hour='')}"
        return f"{timer.label or format_duration(timer.duration)}, {format_remaining(self.timers.remaining(timer))}"

    def _cancel(self, name: str | None) -> Response:
        timers, problem = self._resolve(name)
        if problem:
            return problem
        if len(timers) > 1:
            names = join_words([t.label or format_duration(t.duration) for t in timers])
            return Response(f"¿Cuál? Tienes {names}.")
        timer = timers[0]
        self.timers.cancel(timer)
        what = of_label(timer.label) if timer.label else f"de {format_duration(timer.duration)}"
        return Response(f"Cancelé el temporizador {what}.")
