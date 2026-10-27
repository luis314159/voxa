from __future__ import annotations

import contextlib
import logging
import re

from voxa.core.types import OK, Intent, Response
from voxa.i18n import tr
from voxa.services.music_backend import BackendUnavailable, MusicBackend
from voxa.services.video import VideoNotFound, VideoPlayer, VideoSearch, VideoUnavailable

log = logging.getLogger(__name__)

_NO_VIDEO = Response("No pude poner el video. Revisa la conexión a internet.", sound="error")
_NOTHING_ON = Response("No hay ningún video puesto.")
# Lo que sigue a estos signos suele ser relleno: «Pozole rojo | Receta fácil 🔥 #shorts».
_TITLE_CUT = re.compile(r"\s[|\-–—·•]\s|:\s|[|(\[#【]")
_NOT_WORDS = re.compile(r"[^\w\s¿?¡!.,'’&-]")
_MAX_WORDS = 10
_ARTICLE = re.compile(r"^(el|la|los|las|un|una|unos|unas|the|an?)\s+", re.IGNORECASE)


def speakable_title(title: str) -> str:
    """El título como se diría en voz alta: sin emojis, etiquetas ni MAYÚSCULAS a gritos."""
    head = _TITLE_CUT.split(title, maxsplit=1)[0]
    words = _NOT_WORDS.sub(" ", head).split()
    if not words:
        words = _NOT_WORDS.sub(" ", title).split() or ["el video"]
    text = " ".join(words[:_MAX_WORDS])
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) > 0.6 * len(letters):
        text = text.lower()
    return text[:1].upper() + text[1:]


class VideoSkill:
    """«Pon un video de cómo hacer pozole», y mientras se ve: pausa, sigue, adelanta, cierra."""

    def __init__(self, search: VideoSearch, player: VideoPlayer, music: MusicBackend | None = None) -> None:
        self._search = search
        self._player = player
        self._music = music

    @property
    def active(self) -> bool:
        return self._player.current is not None

    async def handle(self, intent: Intent) -> Response:
        try:
            return await self._handle(intent)
        except VideoNotFound as exc:
            return Response(tr("No encontré un video de «{what}».", what=exc), sound="error")
        except VideoUnavailable as exc:
            log.warning("Video no disponible para %s: %s", intent.name, exc)
            return _NO_VIDEO

    async def _handle(self, intent: Intent) -> Response:
        player = self._player
        if intent.name == "video.play":
            query = intent.slots["query"].strip()
            if intent.slots.get("kind") == "recipe":
                query = tr("receta de {dish}", dish=_ARTICLE.sub("", query))  # «cómo se hace el pozole»
            video = await self._search.search(query)
            if self._music is not None:  # la música no compite con la receta
                with contextlib.suppress(BackendUnavailable):
                    await self._music.pause()
            await player.play(video)
            return Response(tr("Poniendo: {title}.", title=speakable_title(video.title)))
        if player.current is None:
            return OK if intent.name == "video.close" else _NOTHING_ON
        match intent.name:
            case "video.close":
                await player.close()
            case "media.pause":
                await player.pause()
            case "media.resume":
                await player.resume()
            case "media.seek_forward":
                await player.seek(intent.slots["duration"])
            case "media.seek_back":
                await player.seek(-intent.slots["duration"])
            case "media.now_playing":
                return Response(tr("Es «{title}».", title=speakable_title(player.current.title)))
            case "media.next" | "media.previous":
                return Response("Con los videos no hay siguiente ni anterior; pide otro video.")
            case _:
                return Response("Todavía no sé hacer eso con los videos.", sound="error")
        return OK
