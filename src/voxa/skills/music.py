from __future__ import annotations

import logging

from voxa.core.phrases import capitalize, join_words
from voxa.core.types import OK, Intent, Response
from voxa.i18n import english, tr
from voxa.services.music_backend import AuthRequired, BackendUnavailable, MusicBackend, NeedsPermission, NothingFound
from voxa.skills.mood import mood_search

log = logging.getLogger(__name__)

_NO_SPOTIFY = Response("No pude conectar con Spotify. Revisa que Spotifast esté abierto.", sound="error")
_REAUTHORIZE = " Además, falta autorizar Spotify en VOXA."
MAX_SAID = 8


class MusicSkill:
    def __init__(self, backend: MusicBackend) -> None:
        self._backend = backend

    async def handle(self, intent: Intent) -> Response:
        try:
            return await self._handle(intent)
        except NothingFound as exc:
            if intent.name == "music.transfer":
                return Response(tr("No encontré ese dispositivo: «{what}».", what=exc), sound="error")
            return Response(tr("No encontré eso: «{what}».", what=exc), sound="error")
        except NeedsPermission:
            return Response("Para tus Me gusta, vuelve a conectar Spotify desde el celular: Ajustes, Spotify, "
                            "«Conectar con Spotify».", sound="error")
        except AuthRequired:
            return Response(_NO_SPOTIFY.speech + _REAUTHORIZE, sound="error")
        except BackendUnavailable as exc:
            log.warning("Música no disponible para %s: %s", intent.name, exc)
            return _NO_SPOTIFY

    async def _handle(self, intent: Intent) -> Response:
        backend = self._backend
        match intent.name:
            case "music.play":
                query = intent.slots["query"].removeprefix("de ").strip()
                kind = intent.slots.get("kind")
                # «Pon algo tranquilo para cocinar», «pon salsa», «música de los 80»: una playlist.
                if kind == "liked":
                    result = await backend.play_liked()
                    return Response(capitalize(result.describe()) + ".")
                if kind == "mood" and english():  # «play some music for cooking»
                    query, kind = f"{query} music", "playlist"
                elif kind == "mood":
                    query, kind = mood_search(f"para {query}", forced=True) or query, "playlist"
                elif kind in (None, "artist") and not english() and (search := mood_search(query)) is not None:
                    query, kind = search, "playlist"
                result = await backend.play(query, kind)
                return Response(capitalize(result.describe()) + ".")
            case "media.pause":
                await backend.pause()
            case "media.resume":
                await backend.resume()
            case "media.next":
                await backend.next()
            case "media.previous":
                await backend.previous()
            case "media.seek_forward":
                await backend.seek(intent.slots["duration"])
            case "media.seek_back":
                await backend.seek(-intent.slots["duration"])
            case "music.shuffle":
                await backend.shuffle(True)
                return Response("Modo aleatorio.")
            case "music.like":
                await backend.like()
                return Response("Guardada en tus Me gusta.")
            case "media.now_playing":
                current = await backend.now_playing()
                if current is None:
                    return Response("No está sonando nada.")
                if current.artist:
                    return Response(tr("{title}, de {artist}.", title=current.title, artist=current.artist))
                return Response(f"{current.title}.")
            case "music.playlists":
                names = [p.name for p in await backend.playlists()]
                if not names:
                    return Response("No encontré playlists en tu cuenta de Spotify.")
                said = join_words(names[:MAX_SAID] + ([tr("{count} más", count=len(names) - MAX_SAID)] if len(names) > MAX_SAID else []))
                count = tr("una playlist") if len(names) == 1 else tr("{count} playlists", count=len(names))
                return Response(tr("Tienes {count}: {items}. Dime «pon mi playlist» y su nombre; en el celular están todas.",
                                   count=count, items=said))
            case "music.transfer":
                name = await backend.transfer(intent.slots["device"])
                return Response(tr("Pasando la música a {device}.", device=name))
            case _:
                return Response("Todavía no sé hacer eso con la música.", sound="error")
        return OK
