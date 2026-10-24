"""«Buenos días»: la hora, el clima, lo que hay hoy y, si se configuró, la música de la mañana."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from voxa.core.phrases import clock_words, join_words, time_phrase
from voxa.core.types import Intent, Response
from voxa.services.music_backend import BackendUnavailable, MusicBackend, NothingFound
from voxa.services.weather import OpenMeteo, WeatherUnavailable
from voxa.state.timers import TimerManager

log = logging.getLogger(__name__)


class RoutineSkill:
    def __init__(
        self,
        timers: TimerManager,
        weather: OpenMeteo | None = None,
        music: MusicBackend | None = None,
        morning_music: str = "",
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._timers = timers
        self._weather = weather
        self._music = music
        self._morning_music = morning_music
        self._now = now

    async def handle(self, intent: Intent) -> Response:
        if intent.name == "routine.good_night":
            return Response(self._good_night())
        return Response(await self._good_morning())

    async def _good_morning(self) -> str:
        now = self._now()
        parts = [f"¡{'Buenos días' if now.hour < 12 else 'Buenas tardes' if now.hour < 20 else 'Buenas noches'}!",
                 time_phrase(now)]
        if self._weather is not None:
            try:
                w = await self._weather.today()
                rain = f" y {w.rain_probability} % de probabilidad de lluvia" if w.rain_probability >= 30 else ""
                parts.append(f"Hay {round(w.temperature)} grados; hoy, máxima de {round(w.high)}{rain}.")
            except WeatherUnavailable as exc:
                log.info("Sin clima para «buenos días»: %s", exc)
        today = self._reminders(lambda at: at.date() == now.date())
        if today:
            parts.append(f"Hoy tienes: {join_words(today)}.")
        if self._morning_music and self._music is not None:
            try:
                await self._music.play(self._morning_music)
            except (BackendUnavailable, NothingFound) as exc:
                log.warning("No pude poner la música de la mañana: %s", exc)
        return " ".join(parts)

    def _good_night(self) -> str:
        now = self._now()
        coming = self._reminders(lambda at: (at - now).total_seconds() < 18 * 3600)
        if coming:
            return f"Buenas noches. Te aviso: {join_words(coming)}."
        return "Buenas noches."

    def _reminders(self, keep: Callable[[datetime], bool]) -> list[str]:
        said = []
        for timer in self._timers.active:
            if not timer.is_reminder:
                continue
            at = datetime.fromtimestamp(timer.ends_at)
            if keep(at):
                said.append(f"{timer.label or 'la alarma'} a {clock_words(at.hour, at.minute, on_the_hour='')}")
        return said
