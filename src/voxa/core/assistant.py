"""Recibe texto (de STT o del modo texto), encuentra la intención y la manda a su habilidad."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Mapping

from voxa.core.types import OK, Intent, Response, Skill
from voxa.nlu.matcher import Matcher
from voxa.state.timers import TimerManager

log = logging.getLogger(__name__)

NOT_UNDERSTOOD = Response("No te entendí. Puedes preguntarme «¿qué puedes hacer?».", sound="error")
NOT_YET = Response("Todavía no sé hacer eso.", sound="error")
_NOT_YET_BY_DOMAIN = {
    "video": Response("Todavía no sé poner videos: falta instalar mpv y yt-dlp.", sound="error"),
}
FAILED = Response("Algo salió mal. Inténtalo de nuevo.", sound="error")

# Mientras suena una alarma, cualquiera de estas la apaga («para», «ya», «gracias»…).
_STOPS_ALARM = frozenset(
    {"timer.stop_alarm", "media.pause", "system.ack", "system.cancel", "volume.mute", "timer.cancel"}
)

Fallback = Callable[[str], Awaitable[Response | None]]


class Assistant:
    def __init__(
        self,
        matcher: Matcher,
        skills: Mapping[str, Skill],
        timers: TimerManager | None = None,
        fallback: Fallback | None = None,
        video_active: Callable[[], bool] | None = None,
    ) -> None:
        self._matcher = matcher
        self._skills = dict(skills)
        self._timers = timers
        self._fallback = fallback
        self._video_active = video_active or (lambda: False)
        self.last_response: Response | None = None

    @property
    def active_media(self) -> str:
        """Qué reproductor reciben «pausa», «siguiente»…: el video mientras hay uno puesto."""
        return "video" if self._video_active() else "music"

    async def handle_text(self, text: str) -> Response:
        intent = self._matcher.match(text)
        if intent is None:
            response = await self._fallback(text) if self._fallback else None
            return self._remember(response or NOT_UNDERSTOOD)
        log.info("«%s» → %s %s", text, intent.name, intent.slots)
        return self._remember(await self.handle_intent(intent))

    async def handle_intent(self, intent: Intent) -> Response:
        if self._timers and self._timers.ringing and intent.name in _STOPS_ALARM:
            return await self._dispatch("timer", Intent("timer.stop_alarm", text=intent.text, raw=intent.raw))
        if intent.name == "system.repeat":
            return self.last_response or Response("No he dicho nada todavía.")
        if intent.name == "system.cancel":
            return OK

        if intent.name == "music.play" and self._video_active():
            await self._dispatch("video", Intent("video.close", text=intent.text, raw=intent.raw))
        domain = self.active_media if intent.domain == "media" else intent.domain
        return await self._dispatch(domain, intent)

    async def _dispatch(self, domain: str, intent: Intent) -> Response:
        skill = self._skills.get(domain)
        if skill is None:
            return _NOT_YET_BY_DOMAIN.get(domain, NOT_YET)
        try:
            return await skill.handle(intent)
        except Exception:
            log.exception("La habilidad %s falló con %s", domain, intent)
            return FAILED

    def _remember(self, response: Response) -> Response:
        if response.speech:
            self.last_response = response
        return response
