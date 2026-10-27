"""Recibe texto (de STT o del modo texto), encuentra la intención y la manda a su habilidad."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Awaitable, Callable, Mapping

from voxa.core.types import OK, Intent, Response, Skill
from voxa.i18n import guess_language, home_language, in_language, localize
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
STOPS_ALARM = frozenset(
    {"timer.stop_alarm", "media.pause", "system.ack", "system.cancel", "volume.mute", "timer.cancel"}
)

Fallback = Callable[[str], Awaitable[Response | None]]


def _localized(response: Response) -> Response:
    """Las frases fijas en el idioma de la casa (las que llevan datos ya vienen traducidas: ``tr``)."""
    speech = localize(response.speech)
    return response if speech == response.speech else replace(response, speech=speech)


class Assistant:
    def __init__(
        self,
        matcher: Matcher,
        skills: Mapping[str, Skill],
        timers: TimerManager | None = None,
        fallback: Fallback | None = None,
        video_active: Callable[[], bool] | None = None,
        other: Matcher | None = None,
        *,
        bilingual: bool = False,
    ) -> None:
        self._matcher = matcher
        self._other = other
        """La gramática del otro idioma: los botones de la pantalla y a veces la IA mandan órdenes en
        español aunque la casa hable inglés; en una casa bilingüe, se prueba con cada frase."""
        self.bilingual = bilingual and other is not None
        self._skills = dict(skills)
        self._timers = timers
        self.fallback = fallback
        self._video_active = video_active or (lambda: False)
        self.last_response: Response | None = None

    def skill(self, domain: str) -> Skill | None:
        return self._skills.get(domain)

    @property
    def active_media(self) -> str:
        """Qué reproductor reciben «pausa», «siguiente»…: el video mientras hay uno puesto."""
        return "video" if self._video_active() else "music"

    async def handle_text(self, text: str, language: str | None = None, *, button: bool = False) -> Response:
        """``language``: el que oyó el STT (casa bilingüe), que se prueba primero.

        ``button``: una orden fija de la pantalla o del celular («pausa»): se entiende en cualquier idioma y
        se contesta en el de la casa.
        """
        for matcher in self._matchers(language, everything=button):
            intent = matcher.match(text)
            if intent is None:
                continue
            log.info("«%s» → %s %s", text, intent.name, intent.slots)
            said_in = matcher.language.code if self.bilingual and not button else home_language()
            with in_language(said_in):
                response = _localized(await self.handle_intent(intent))
            return self._remember(self._marked(response, said_in))
        said_in = (language or guess_language(text)) if self.bilingual else home_language()
        with in_language(said_in):
            response = await self.fallback(text) if self.fallback else None
            response = _localized(response or NOT_UNDERSTOOD)
        return self._remember(self._marked(response, said_in))

    def _marked(self, response: Response, language: str) -> Response:
        """En una casa bilingüe, la respuesta lleva su idioma (para la voz con que se dice)."""
        return replace(response, language=language) if self.bilingual else response

    def _matchers(self, language: str | None, *, everything: bool = False) -> list[Matcher]:
        if self._other is None or not (self.bilingual or everything):
            return [self._matcher]
        if language == self._other.language.code:
            return [self._other, self._matcher]
        return [self._matcher, self._other]

    async def try_command(self, text: str) -> Response | None:
        """Ejecuta ``text`` si es una orden que las reglas entienden (la IA traduce a estas); si no, ``None``."""
        intent = next((i for m in self._matchers(None, everything=True) if (i := m.match(text))), None)
        if intent is None:
            return None
        log.info("«%s» → %s %s (vía IA)", text, intent.name, intent.slots)
        return await self.handle_intent(intent)

    async def handle_intent(self, intent: Intent) -> Response:
        if self._timers and self._timers.ringing and intent.name in STOPS_ALARM:
            return await self._dispatch("timer", Intent("timer.stop_alarm", text=intent.text, raw=intent.raw))
        if intent.name == "system.repeat":
            if self.last_response is None:
                return Response("No he dicho nada todavía.")
            return replace(self.last_response, spoken=False)  # repetir es volver a decirlo
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
