"""Horas de silencio: de noche, VOXA habla bajito y no despierta a la casa.

- La voz y los sonidos salen más bajos (las alarmas no: para eso se pusieron).
- Una alarma que nadie apaga no se avisa en los otros cuartos.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from voxa.config import QuietConfig
from voxa.departure import parse_time


class QuietHours:
    def __init__(self, config: QuietConfig, clock: Callable[[], datetime] = datetime.now) -> None:
        self.config = config
        self._clock = clock

    def active(self) -> bool:
        quiet = self.config
        start, end = parse_time(quiet.start), parse_time(quiet.end)
        if not quiet.enabled or start is None or end is None:
            return False
        now = self._clock()
        minute = now.hour * 60 + now.minute
        first, last = start[0] * 60 + start[1], end[0] * 60 + end[1]
        return first <= minute < last if first <= last else (minute >= first or minute < last)

    def gain(self) -> float:
        """Cuánto suenan la voz y los sonidos (1 = normal)."""
        return max(0.05, min(1.0, self.config.level)) if self.active() else 1.0
