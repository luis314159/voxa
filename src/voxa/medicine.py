"""Medicinas con confirmación: «Ana, ¿ya te tomaste la medicina?».

Un recordatorio que habla de medicina («recuérdame tomar la pastilla de la presión a las 8») suena
como cualquier otro, pero pregunta y espera respuesta:

- «ya me la tomé» (o apagar la alarma) la anota como tomada;
- «todavía no» la vuelve a preguntar en unos minutos;
- si nadie contesta, la pregunta se repite unas veces y luego se avisa a otra persona: por Telegram
  y en los otros cuartos (de noche, en horas de silencio, solo por Telegram).

Lo de cada día se guarda en ``medicinas.json`` (para «¿ya se tomó Ana la medicina?» y el celular).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from voxa.config import MedicineConfig
from voxa.i18n import tr
from voxa.nlu.normalize import strip_accents
from voxa.state.timers import Timer, TimerManager

log = logging.getLogger(__name__)

_WORDS = re.compile(
    r"\b(?:medicinas?|medicamentos?|pastillas?|pildoras?|tabletas?|capsulas?|jarabe|insulina|gotas|vitaminas?"
    r"|antibioticos?|inyeccion|inhalador|medicine|meds|medications?|pills?|tablets?|vitamins?|insulin|drops"
    r"|inhaler|antibiotics?)\b"
)
KEEP_DAYS = 14


_VERB = re.compile(
    r"^(?:que\s+)?(?:se\s+|me\s+|te\s+)?(?:tomar(?:se|me|te)?|tome|tomes|toma|ponerse|ponerme|ponga|darle|dale"
    r"|take|takes|give\s+\w+)\s+", re.IGNORECASE,
)


def what(label: str | None) -> str:
    """«se tome la pastilla de la presión» → «la pastilla de la presión» (lo que se toma)."""
    text = (label or "").strip()
    return _VERB.sub("", text) or text


def is_medicine(label: str | None) -> bool:
    return bool(label) and _WORDS.search(strip_accents(label.lower())) is not None


@dataclass
class Dose:
    label: str
    person: str | None
    due: float
    taken: float | None = None
    missed: bool = False


class MedicineLog:
    def __init__(self, store: Path | None = None, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock
        self.doses: list[Dose] = []
        self._load()

    def record(self, timer: Timer, *, taken: bool) -> Dose:
        """La dosis de esta vez: tomada ahora o sin confirmar."""
        dose = Dose(timer.label or "", timer.person, timer.ends_at, self._clock() if taken else None, not taken)
        self.doses.append(dose)
        self._save()
        return dose

    def mark_taken(self, index: int) -> bool:
        """Desde el celular: «ya se la tomó» (una que quedó sin confirmar)."""
        today = self.today()
        if not 0 <= index < len(today) or today[index].taken is not None:
            return False
        today[index].taken, today[index].missed = self._clock(), False
        self._save()
        return True

    def today(self) -> list[Dose]:
        start = datetime.fromtimestamp(self._clock()).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return [d for d in self.doses if d.due >= start]

    def last_for(self, person: str | None) -> Dose | None:
        mine = [d for d in self.today() if _same(d.person, person)]
        return mine[-1] if mine else None

    def snapshot(self) -> list[dict]:
        return [{"medicina": what(d.label), "persona": d.person, "hora": d.due, "tomada": d.taken, "sin_confirmar": d.missed}
                for d in self.today()]

    def _load(self) -> None:
        if not self._store or not self._store.exists():
            return
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            self.doses = [Dose(**d) for d in data if isinstance(d, dict)]
        except (OSError, ValueError, TypeError) as exc:
            log.warning("No pude leer las medicinas: %s", exc)

    def _save(self) -> None:
        cutoff = self._clock() - KEEP_DAYS * 86400
        self.doses = [d for d in self.doses if d.due >= cutoff]
        if not self._store:
            return
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            self._store.write_text(json.dumps([asdict(d) for d in self.doses], ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("No pude guardar las medicinas: %s", exc)


def _same(a: str | None, b: str | None) -> bool:
    return strip_accents((a or "").lower()) == strip_accents((b or "").lower())


Notify = Callable[[str], Awaitable[None]]


class MedicineTracker:
    """Lo que pasa con cada dosis: preguntar, anotar y, si nadie contesta, avisar a otra persona."""

    def __init__(self, config: MedicineConfig, timers: TimerManager, log_: MedicineLog) -> None:
        self.config = config
        self.timers = timers
        self.log = log_
        self.notify: Notify | None = None
        """Lo pone el servicio: avisa a otra persona (Telegram y los otros cuartos)."""
        self._tasks: set[asyncio.Task] = set()
        if config.enabled:
            timers.ring_rules = self._ring_rules
            timers.on_stopped.append(self.stopped)
            timers.on_unanswered.append(self.unanswered)

    def _ring_rules(self, timer: Timer) -> tuple[float, float] | None:
        """Cada cuánto se pregunta y cuánto se espera, para las medicinas (``None``: como cualquier alarma)."""
        if not is_medicine(timer.label):
            return None
        every = self.config.ask_every_minutes * 60
        return every, every * max(1, self.config.tries)

    def watches(self, timer: Timer) -> bool:
        return self.config.enabled and is_medicine(timer.label)

    def ringing(self) -> list[Timer]:
        return [t for t in self.timers.ringing if is_medicine(t.label)] if self.config.enabled else []

    def stopped(self, timers: list[Timer]) -> None:
        for timer in timers:
            if is_medicine(timer.label):
                self.log.record(timer, taken=True)
                log.info("Medicina tomada: %s (%s)", timer.label, timer.person or "la casa")

    def unanswered(self, timer: Timer) -> None:
        if not is_medicine(timer.label):
            return
        self.log.record(timer, taken=False)
        log.warning("Medicina sin confirmar: %s (%s)", timer.label, timer.person or "la casa")
        if self.notify is None:
            return
        try:
            task = asyncio.get_running_loop().create_task(self.notify(missed_phrase(timer)))
        except RuntimeError:  # sin bucle (pruebas síncronas): solo queda anotada
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def _hour(timer: Timer) -> str:
    at = datetime.fromtimestamp(timer.ends_at)
    return f"{at.hour}:{at.minute:02d}"


def ring_phrase(timer: Timer) -> str:
    """La primera vez dice qué tomar y cómo confirmar; las siguientes, solo pregunta."""
    first = timer.last_rang_at is None or timer.ringing_since is None or timer.last_rang_at <= timer.ringing_since
    label = what(timer.label)
    if first and timer.person:
        return tr("{person}, es hora de tu medicina: {label}. Cuando te la tomes, dime «ya me la tomé».",
                  person=timer.person, label=label)
    if first:
        return tr("Es hora de la medicina: {label}. Cuando se la tomen, díganme «ya me la tomé».", label=label)
    if timer.person:
        return tr("{person}, ¿ya te tomaste la medicina? {label}.", person=timer.person, label=label)
    return tr("¿Ya se tomaron la medicina? {label}.", label=label)


def missed_phrase(timer: Timer) -> str:
    if timer.person:
        return tr("{person} no ha confirmado su medicina de las {hour}: {label}.", person=timer.person,
                  hour=_hour(timer), label=what(timer.label))
    return tr("Nadie confirmó la medicina de las {hour}: {label}.", hour=_hour(timer), label=what(timer.label))
