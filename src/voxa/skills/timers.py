from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from voxa.core.people import speaker
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
from voxa.i18n import english, tr
from voxa.state.timers import Timer, TimerManager, display_label, label_key, next_weekly

_MAX_SECONDS = 24 * 3600
_SOON = timedelta(seconds=30)  # «a las 7» dicho a las 6:59:50 es para mañana, no para dentro de 10 s


def ring_phrase(timer: Timer) -> str:
    if timer.is_reminder and timer.person:
        if timer.label:
            return tr("{person}, te recuerdo: {label}.", person=timer.person, label=timer.label)
        return tr("{person}, es la hora.", person=timer.person)
    if timer.is_reminder:
        if timer.label:
            return tr("Te recuerdo: {label}.", label=timer.label)
        at = datetime.fromtimestamp(timer.ends_at)
        return tr("¡Son {hour}!", hour=clock_words(at.hour, at.minute, on_the_hour=""))
    if timer.label:
        return tr("¡Terminó el temporizador {of}!", of=of_label(timer.label), label=timer.label)
    return tr("¡Terminaron los {duration}!", duration=format_duration(timer.duration))


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


def _remind_whom(whom: tuple[str | None, bool]) -> str:
    person, for_other = whom
    return tr("le recuerdo a {person}", person=person) if for_other and person else tr("te recuerdo")


class TimerSkill:
    def __init__(self, timers: TimerManager, now: Callable[[], datetime] = datetime.now) -> None:
        self.timers = timers
        self._now = now

    async def handle(self, intent: Intent) -> Response:
        match intent.name:
            case "timer.set":
                return self._set(intent.slots["duration"], intent.slots.get("name"))
            case "timer.remind":
                # «Recuérdale a Ana…»: para Ana. «Recuérdame…» dicho por alguien que VOXA reconoce: para esa persona.
                target = (intent.slots.get("person") or "").strip()
                whom = (target.title() if target else speaker(), bool(target))
                days = intent.slots.get("days")
                if days is not None:
                    return self._remind_on(intent.slots["time"], intent.slots.get("name"), *days, whom=whom)
                clock = intent.slots["time"]
                if intent.text.startswith(("despiertame", "levantame")) and clock[2] is None and 1 <= clock[0] <= 11:
                    clock = (clock[0], clock[1], "manana")  # «despiértame a las 6» es de la mañana
                return self._remind(clock, intent.slots.get("name"), intent.slots.get("day") == "manana", whom)
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
            case "timer.unclear":
                return Response(
                    "No entendí para cuándo. Dime, por ejemplo: «alarma a las siete» o «temporizador de diez minutos».",
                    sound="error",
                )
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
        if label:
            return Response(capitalize(tr("{duration} para {label}.", duration=said, label=label)))
        return Response(capitalize(tr("{duration}. Empezando.", duration=said)))

    def _remind(
        self, clock: tuple[int, int, str | None], label: str | None, tomorrow: bool,
        whom: tuple[str | None, bool] = (None, False),
    ) -> Response:
        now = self._now()
        at = next_occurrence(clock, now, tomorrow=tomorrow)
        if at is None:
            return Response("No entendí la hora. Prueba con «a las 8 de la noche».", sound="error")
        label = label.strip() if label else None
        self.timers.add_at(at.timestamp(), label, person=whom[0])
        hour = clock_words(at.hour, at.minute, on_the_hour="")  # «las 8 de la noche»
        tomorrow = at.date() > now.date()
        when = tr("mañana a {hour}", hour=hour) if tomorrow else tr("a {hour}", hour=hour)
        if label:
            return Response(capitalize(f"{when} {_remind_whom(whom)} {label}."))
        return Response(tr("Alarma para {when}.", when=tr("mañana a {hour}", hour=hour) if tomorrow else hour))

    def _remind_on(
        self, clock: tuple[int, int, str | None], label: str | None, days: frozenset[int], repeat: bool,
        whom: tuple[str | None, bool] = (None, False),
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
        self.timers.add_at(when_at.timestamp(), label, repeat=sorted(days) if repeat else None, at=list(at),
                           person=whom[0])
        hour_words = clock_words(at[0], at[1], on_the_hour="")
        if repeat:
            when = tr("{days} a {hour}", days=days_phrase(days), hour=hour_words)
        else:
            when = tr("el {day} a {hour}", day=weekday_name(when_at.weekday()), hour=hour_words)
        if label:
            return Response(capitalize(f"{when} {_remind_whom(whom)} {label}."))
        return Response(tr("Alarma {when}.", when=when))

    def _adjust(self, seconds: int, name: str | None) -> Response:
        ringing = self.timers.ringing
        if ringing and seconds > 0 and (not name or self._generic(name)):
            for timer in ringing:  # «5 minutos más»: la alarma vuelve a contar
                self.timers.snooze(timer, seconds)
            return Response(tr("Te aviso en {duration}.", duration=format_duration(seconds)))
        timers, problem = self._resolve(name, reminders=False)
        if problem:
            return problem
        if len(timers) > 1:
            names = join_words([t.label or format_duration(t.duration) for t in timers])
            return Response(tr("¿A cuál? Tienes {names}.", names=names))
        timer = timers[0]
        self.timers.adjust(timer, seconds)
        whom = tr(" {to}", to=_to_label(timer.label), label=timer.label) if timer.label else ""
        left = falta(format_remaining(self.timers.remaining(timer)))
        values = {"duration": format_duration(abs(seconds)), "whom": whom, "left": f"{left[0].lower()}{left[1:]}"}
        if seconds > 0:
            return Response(tr("Le agregué {duration}{whom}: {left}.", **values))
        return Response(tr("Le quité {duration}{whom}: {left}.", **values))

    def _pause(self, pause: bool, name: str | None) -> Response:
        timers, problem = self._resolve(name, reminders=False)
        if problem:
            return problem
        timers = [t for t in timers if t.paused != pause] or timers
        if len(timers) > 1:
            names = join_words([t.label or format_duration(t.duration) for t in timers])
            return Response(tr("¿Cuál? Tienes {names}.", names=names))
        timer = timers[0]
        of, name = _of_and_name(timer)
        if pause:
            if timer.paused:
                return Response(tr("El temporizador {of} ya estaba en pausa.", of=of, name=name))
            self.timers.pause(timer)
            left = format_remaining(self.timers.remaining(timer))
            return Response(tr("Pausé el temporizador {of}; quedan {left}.", of=of, name=name, left=left))
        if not timer.paused:
            return Response(tr("El temporizador {of} no estaba en pausa.", of=of, name=name))
        self.timers.resume(timer)
        left = falta(format_remaining(self.timers.remaining(timer)))
        return Response(tr("Sigue el temporizador {of}: {left}.", of=of, name=name, left=f"{left[0].lower()}{left[1:]}"))

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
                return [], Response(tr("No encontré un temporizador {of}.", of=of_label(name), name=name))
            return found, None
        return active, None

    def _query(self, name: str | None) -> Response:
        timers, problem = self._resolve(name)
        if problem:
            return problem
        if len(timers) == 1 and not timers[0].is_reminder:
            timer = timers[0]
            label = timer.label if not english() or not timer.label else display_label(timer.label)
            suffix = tr(" para {label}", label=label) if label and len(self.timers.active) > 1 else ""
            return Response(f"{falta(format_remaining(self.timers.remaining(timer)))}{suffix}.")
        parts = [self._describe(t) for t in timers]
        if len(parts) == 1:
            return Response(capitalize(parts[0]) + ".")
        return Response(tr("Tienes {count}: {items}.", count=len(timers), items=join_words(parts)))

    def _describe(self, timer: Timer) -> str:
        if timer.is_reminder:  # «sacar la basura, a las 8 de la noche»
            at = datetime.fromtimestamp(timer.ends_at)
            hour = clock_words(at.hour, at.minute, on_the_hour="")
            what = timer.label or tr("alarma")
            if timer.repeat:
                return tr("{what}, {days} a {hour}", what=what, days=days_phrase(timer.repeat), hour=hour)
            days_away = (at.date() - self._now().date()).days
            day = tr("mañana ") if days_away == 1 else tr("el {day} ", day=weekday_name(at.weekday())) if days_away > 1 else ""
            return tr("{what}, {day}a {hour}", what=what, day=day, hour=hour)
        paused = tr(" (en pausa)") if timer.paused else ""
        return f"{timer.label or format_duration(timer.duration)}, {format_remaining(self.timers.remaining(timer))}{paused}"

    def _cancel(self, name: str | None) -> Response:
        timers, problem = self._resolve(name)
        if problem:
            return problem
        if len(timers) > 1:
            names = join_words([t.label or format_duration(t.duration) for t in timers])
            return Response(tr("¿Cuál? Tienes {names}.", names=names))
        timer = timers[0]
        self.timers.cancel(timer)
        of, name = _of_and_name(timer)
        return Response(tr("Cancelé el temporizador {of}.", of=of, name=name))


def _of_and_name(timer: Timer) -> tuple[str, str]:
    """«del arroz» / «de 5 minutos» (español) y «rice» / «5 minute» (para «the rice timer» en inglés)."""
    if timer.label:
        return of_label(timer.label), display_label(timer.label)
    duration = format_duration(timer.duration)
    return tr("de {duration}", duration=duration), duration


def _to_label(label: str) -> str:
    """«el arroz» → «al arroz», «la sopa» → «a la sopa»."""
    if label.startswith("el "):
        return "al " + label[3:]
    return "a " + label
