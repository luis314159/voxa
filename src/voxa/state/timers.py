"""Temporizadores persistentes: sobreviven a un reinicio de VOXA."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from voxa.nlu.normalize import strip_accents

log = logging.getLogger(__name__)

_ARTICLES = ("el ", "la ", "los ", "las ", "al ", "del ", "de ", "a ", "para ", "mi ", "mis ", "the ", "my ")
# Un temporizador que venció mientras VOXA estaba apagado suena al arrancar,
# salvo que haya pasado demasiado tiempo para que importe.
_MAX_OVERDUE_ON_LOAD = 3600
# Lo mínimo que puede quedarle a un temporizador al quitarle tiempo («quítale 10 minutos»).
_MIN_LEFT = 5.0


def next_weekly(at: tuple[int, int], days: list[int] | frozenset[int], after: datetime) -> datetime:
    """La próxima vez, después de ``after``, que es uno de esos días (0 = lunes) a esa hora."""
    hour, minute = at
    start = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for offset in range(8):
        candidate = start + timedelta(days=offset)
        if candidate.weekday() in days and candidate > after:
            return candidate
    raise ValueError(f"sin días: {days}")


def label_key(label: str) -> str:
    """Clave para comparar nombres: «al arroz», «del arroz» y «arroz» son el mismo; «té» y «te» también."""
    return strip_accents(display_label(label))


def display_label(label: str) -> str:
    """El nombre sin artículos, para mostrarlo: «el té» → «té»."""
    key = label.strip().lower()
    changed = True
    while changed:
        changed = False
        for article in _ARTICLES:
            if key.startswith(article):
                key = key[len(article) :]
                changed = True
    return key


@dataclass
class Timer:
    id: int
    duration: int
    ends_at: float
    label: str | None = None
    ringing_since: float | None = None
    last_rang_at: float | None = None
    kind: str = "timer"
    """``timer`` («en 10 minutos») o ``reminder`` («a las 8»: recordatorio o alarma de despertador)."""
    paused_remaining: float | None = None
    """En pausa: los segundos que le quedaban (``ends_at`` ya no cuenta)."""
    repeat: list[int] | None = None
    """Recordatorio semanal: los días en que suena (0 = lunes)."""
    at: list[int] | None = None
    """La hora y minuto de un recordatorio semanal, para programar la siguiente vez."""
    person: str | None = None
    """Para quién es («recuérdame…» dicho por Ana, o «recuérdale a Ana…»): se le dice por su nombre."""

    @property
    def is_reminder(self) -> bool:
        return self.kind == "reminder"

    @property
    def paused(self) -> bool:
        return self.paused_remaining is not None


class TimerManager:
    def __init__(
        self,
        store: Path | None = None,
        *,
        clock: Callable[[], float] = time.time,
        on_ring: Callable[[Timer], None] | None = None,
        repeat_seconds: float = 30,
        ring_timeout_seconds: float = 600,
    ) -> None:
        self._store = store
        self._clock = clock
        self.on_ring = on_ring
        self._repeat = repeat_seconds
        self._ring_timeout = ring_timeout_seconds
        self._timers: list[Timer] = []
        self._next_id = 1
        self._load()

    # --- consultas -------------------------------------------------------
    @property
    def active(self) -> list[Timer]:
        return sorted((t for t in self._timers if t.ringing_since is None), key=lambda t: t.ends_at)

    @property
    def ringing(self) -> list[Timer]:
        return [t for t in self._timers if t.ringing_since is not None]

    def remaining(self, timer: Timer) -> float:
        if timer.paused_remaining is not None:
            return timer.paused_remaining
        return max(0.0, timer.ends_at - self._clock())

    def find(self, label: str) -> list[Timer]:
        key = label_key(label)
        exact = [t for t in self.active if t.label and label_key(t.label) == key]
        return exact or [t for t in self.active if t.label and key in label_key(t.label)]

    # --- cambios ---------------------------------------------------------
    def add(self, seconds: int, label: str | None = None, *, kind: str = "timer") -> Timer:
        timer = Timer(self._next_id, seconds, self._clock() + seconds, label, kind=kind)
        self._next_id += 1
        self._timers.append(timer)
        self._save()
        return timer

    def add_at(
        self,
        ends_at: float,
        label: str | None = None,
        *,
        kind: str = "reminder",
        repeat: list[int] | None = None,
        at: list[int] | None = None,
        person: str | None = None,
    ) -> Timer:
        """A una hora fija (epoch): la hora exacta que se dijo, no «ahora + segundos».

        Con ``repeat`` (días) y ``at`` (hora, minuto), al sonar se programa solo la siguiente vez.
        """
        timer = Timer(
            self._next_id, max(1, round(ends_at - self._clock())), ends_at, label, kind=kind, repeat=repeat, at=at,
            person=person,
        )
        self._next_id += 1
        self._timers.append(timer)
        self._save()
        return timer

    def pause(self, timer: Timer) -> None:
        if timer.paused_remaining is None:
            timer.paused_remaining = max(0.0, timer.ends_at - self._clock())
            self._save()

    def resume(self, timer: Timer) -> None:
        if timer.paused_remaining is not None:
            timer.ends_at = self._clock() + timer.paused_remaining
            timer.paused_remaining = None
            self._save()

    def adjust(self, timer: Timer, seconds: float) -> None:
        """«Agrégale 5 minutos» (+) o «quítale 2» (−); nunca queda en menos de unos segundos."""
        left = max(_MIN_LEFT, self.remaining(timer) + seconds)
        if timer.paused_remaining is not None:
            timer.paused_remaining = left
        else:
            timer.ends_at = self._clock() + left
        timer.duration = max(1, round(max(timer.duration + seconds, left)))  # para la barra de la pantalla
        self._save()

    def snooze(self, timer: Timer, seconds: float) -> None:
        """Una alarma que suena vuelve a contar («5 minutos más»)."""
        timer.ringing_since = timer.last_rang_at = None
        timer.paused_remaining = None
        timer.ends_at = self._clock() + seconds
        timer.duration = max(1, round(seconds))
        self._save()

    def cancel(self, timer: Timer) -> None:
        self._timers.remove(timer)
        self._save()

    def cancel_all(self) -> int:
        count = len(self.active)
        self._timers = self.ringing
        self._save()
        return count

    def stop_ringing(self) -> list[Timer]:
        stopped = self.ringing
        self._timers = self.active
        self._save()
        return stopped

    def check(self) -> None:
        """Hace sonar los que vencieron y repite la alarma de los que siguen sonando."""
        now = self._clock()
        changed = False
        for timer in list(self._timers):
            if timer.paused:
                continue
            if timer.ringing_since is None and timer.ends_at <= now:
                timer.ringing_since = now
                changed = True
                self._schedule_next(timer, now)
                self._ring(timer, now)
            elif timer.ringing_since is not None:
                if now - timer.ringing_since >= self._ring_timeout:
                    log.info("Alarma %s apagada tras sonar %ss sin respuesta", timer.id, self._ring_timeout)
                    self._timers.remove(timer)
                    changed = True
                elif timer.last_rang_at is not None and now - timer.last_rang_at >= self._repeat:
                    self._ring(timer, now)
        if changed:
            self._save()

    async def run(self, interval: float = 0.25) -> None:
        while True:
            self.check()
            await asyncio.sleep(interval)

    def _schedule_next(self, timer: Timer, now: float) -> None:
        """Un recordatorio semanal deja programada la siguiente vez en cuanto suena."""
        if not timer.repeat or not timer.at:
            return
        at = next_weekly((timer.at[0], timer.at[1]), timer.repeat, datetime.fromtimestamp(now) + timedelta(minutes=1))
        self.add_at(at.timestamp(), timer.label, kind=timer.kind, repeat=timer.repeat, at=timer.at, person=timer.person)

    def _ring(self, timer: Timer, now: float) -> None:
        timer.last_rang_at = now
        if self.on_ring:
            self.on_ring(timer)

    # --- persistencia ----------------------------------------------------
    def _load(self) -> None:
        if not self._store or not self._store.exists():
            return
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("No pude leer los temporizadores guardados: %s", exc)
            return
        now = self._clock()
        for item in data:
            timer = Timer(**item)
            waiting = timer.ringing_since is None and timer.paused_remaining is None
            if waiting and timer.repeat and timer.at and timer.ends_at <= now:
                # Un recordatorio semanal que pasó con VOXA apagada sigue con la siguiente vez.
                at = next_weekly((timer.at[0], timer.at[1]), timer.repeat, datetime.fromtimestamp(now))
                timer.ends_at = at.timestamp()
            elif waiting and now - timer.ends_at > _MAX_OVERDUE_ON_LOAD:
                log.info("Se omite %s «%s»: venció hace mucho con VOXA apagada", timer.kind, timer.label)
                continue
            # Una alarma que sonaba antes del reinicio vuelve a sonar desde ahora.
            if timer.ringing_since is not None:
                timer.ringing_since, timer.last_rang_at = None, None
                timer.ends_at = now
            self._timers.append(timer)
        self._next_id = max((t.id for t in self._timers), default=0) + 1

    def _save(self) -> None:
        if not self._store:
            return
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(t) for t in self._timers], ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._store)
        except OSError as exc:
            log.warning("No pude guardar los temporizadores: %s", exc)
