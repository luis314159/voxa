from __future__ import annotations

from voxa.core.phrases import capitalize, falta, format_duration, format_remaining, join_words, of_label
from voxa.core.types import OK, Intent, Response
from voxa.state.timers import Timer, TimerManager, label_key

_MAX_SECONDS = 24 * 3600


def ring_phrase(timer: Timer) -> str:
    if timer.label:
        return f"¡Terminó el temporizador {of_label(timer.label)}!"
    return f"¡Terminaron los {format_duration(timer.duration)}!"


class TimerSkill:
    def __init__(self, timers: TimerManager) -> None:
        self.timers = timers

    async def handle(self, intent: Intent) -> Response:
        match intent.name:
            case "timer.set":
                return self._set(intent.slots["duration"], intent.slots.get("name"))
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

    def _resolve(self, name: str | None) -> tuple[list[Timer], Response | None]:
        active = self.timers.active
        if not active:
            return [], Response("No hay temporizadores.")
        if name and label_key(name) not in ("temporizador", "timer", "alarma"):
            found = self.timers.find(name)
            if not found:
                return [], Response(f"No encontré un temporizador {of_label(name)}.")
            return found, None
        return active, None

    def _query(self, name: str | None) -> Response:
        timers, problem = self._resolve(name)
        if problem:
            return problem
        if len(timers) == 1:
            timer = timers[0]
            suffix = f" para {timer.label}" if timer.label and len(self.timers.active) > 1 else ""
            return Response(f"{falta(format_remaining(self.timers.remaining(timer)))}{suffix}.")
        parts = [
            f"{t.label or format_duration(t.duration)}, {format_remaining(self.timers.remaining(t))}" for t in timers
        ]
        return Response(f"Tienes {len(timers)}: {join_words(parts)}.")

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
