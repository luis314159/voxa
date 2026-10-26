from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from voxa.core.phrases import (
    capitalize,
    clock_words,
    days_phrase,
    falta,
    format_duration,
    format_remaining,
    join_words,
    of_label,
    weekday_name,
)
from voxa.core.types import OK, Intent, Response
from voxa.state.timers import Timer, TimerManager, label_key, next_weekly

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
                days = intent.slots.get("days")
                if days is not None:
                    return self._remind_on(intent.slots["time"], intent.slots.get("name"), *days)
                clock = intent.slots["time"]
                if intent.text.startswith(("despiertame", "levantame")) and clock[2] is None and 1 <= clock[0] <= 11:
                    clock = (clock[0], clock[1], "manana")  # «despiértame a las 6» es de la mañana
                return self._remind(clock, intent.slots.get("name"), intent.slots.get("day") == "manana")
            case "timer.adjust":
                return self._adjust(intent.slots["duration"] * int(intent.slots.get("sign", 1)), intent.slots.get("name"))
            case "timer.pause" | "timer.resume":
                return self._pause(intent.name == "timer.pause", intent.slots.get("name"))
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

    def _remind_on(
        self, clock: tuple[int, int, str | None], label: str | None, days: frozenset[int], repeat: bool
    ) -> Response:
        """«De lunes a viernes a las 6», «los martes a las 8 de la noche», «el viernes a las 5»."""
        now = self._now()
        hour, minute, period = clock
        if period is None and label is None and 1 <= hour <= 11:
            period = "manana"  # «despiértame a las 6»: de la mañana
        first = next_occurrence((hour, minute, period), now)
        if first is None:
            return Response("No entendí la hora. Prueba con «a las 8 de la noche».", sound="error")
        at = (first.hour, first.minute)  # la hora ya resuelta (mañana/tarde, «menos cuarto»)
        after = now if repeat else now.replace(hour=23, minute=59)  # «el viernes» dicho en viernes: el próximo
        when_at = next_weekly(at, days, after)
        label = label.strip() if label else None
        self.timers.add_at(when_at.timestamp(), label, repeat=sorted(days) if repeat else None, at=list(at))
        hour_words = clock_words(at[0], at[1], on_the_hour="")
        if repeat:
            when = f"{days_phrase(days)} a {hour_words}"
        else:
            when = f"el {weekday_name(when_at.weekday())} a {hour_words}"
        if label:
            return Response(capitalize(f"{when} te recuerdo {label}."))
        return Response(f"Alarma {when}.")

    def _adjust(self, seconds: int, name: str | None) -> Response:
        ringing = self.timers.ringing
        if ringing and seconds > 0 and (not name or self._generic(name)):
            for timer in ringing:  # «5 minutos más»: la alarma vuelve a contar
                self.timers.snooze(timer, seconds)
            return Response(f"Te aviso en {format_duration(seconds)}.")
        timers, problem = self._resolve(name, reminders=False)
        if problem:
            return problem
        if len(timers) > 1:
            names = join_words([t.label or format_duration(t.duration) for t in timers])
            return Response(f"¿A cuál? Tienes {names}.")
        timer = timers[0]
        self.timers.adjust(timer, seconds)
        did = "Le agregué" if seconds > 0 else "Le quité"
        whom = f" {_to_label(timer.label)}" if timer.label else ""
        left = falta(format_remaining(self.timers.remaining(timer)))
        return Response(f"{did} {format_duration(abs(seconds))}{whom}: {left[0].lower()}{left[1:]}.")

    def _pause(self, pause: bool, name: str | None) -> Response:
        timers, problem = self._resolve(name, reminders=False)
        if problem:
            return problem
        timers = [t for t in timers if t.paused != pause] or timers
        if len(timers) > 1:
            names = join_words([t.label or format_duration(t.duration) for t in timers])
            return Response(f"¿Cuál? Tienes {names}.")
        timer = timers[0]
        of = of_label(timer.label) if timer.label else f"de {format_duration(timer.duration)}"
        if pause:
            if timer.paused:
                return Response(f"El temporizador {of} ya estaba en pausa.")
            self.timers.pause(timer)
            return Response(f"Pausé el temporizador {of}; quedan {format_remaining(self.timers.remaining(timer))}.")
        if not timer.paused:
            return Response(f"El temporizador {of} no estaba en pausa.")
        self.timers.resume(timer)
        left = falta(format_remaining(self.timers.remaining(timer)))
        return Response(f"Sigue el temporizador {of}: {left[0].lower()}{left[1:]}.")

    @staticmethod
    def _generic(name: str) -> bool:
        return label_key(name) in ("temporizador", "timer", "alarma", "recordatorio", "despertador", "cronometro")

    def _resolve(self, name: str | None, *, reminders: bool = True) -> tuple[list[Timer], Response | None]:
        active = [t for t in self.timers.active if reminders or not t.is_reminder]
        if not active:
            return [], Response("No hay temporizadores.")
        if name and not self._generic(name):
            found = [t for t in self.timers.find(name) if t in active]
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
            hour = clock_words(at.hour, at.minute, on_the_hour="")
            if timer.repeat:
                return f"{timer.label or 'alarma'}, {days_phrase(timer.repeat)} a {hour}"
            days_away = (at.date() - self._now().date()).days
            day = "mañana " if days_away == 1 else f"el {weekday_name(at.weekday())} " if days_away > 1 else ""
            return f"{timer.label or 'alarma'}, {day}a {hour}"
        paused = " (en pausa)" if timer.paused else ""
        return f"{timer.label or format_duration(timer.duration)}, {format_remaining(self.timers.remaining(timer))}{paused}"

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


def _to_label(label: str) -> str:
    """«el arroz» → «al arroz», «la sopa» → «a la sopa»."""
    if label.startswith("el "):
        return "al " + label[3:]
    return "a " + label
