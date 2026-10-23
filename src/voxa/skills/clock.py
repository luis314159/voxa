from __future__ import annotations

from datetime import datetime
from typing import Callable

from voxa.core.phrases import date_phrase, time_phrase
from voxa.core.types import Intent, Response


class ClockSkill:
    def __init__(self, now: Callable[[], datetime] = datetime.now) -> None:
        self._now = now

    async def handle(self, intent: Intent) -> Response:
        if intent.name == "clock.date":
            return Response(date_phrase(self._now()))
        return Response(time_phrase(self._now()))
