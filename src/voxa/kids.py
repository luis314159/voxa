"""Modo niños: lo que cambia cuando le habla un niño (o cualquiera, si se eligió «para todos»).

- Música sin canciones explícitas (con Spotify, que trae la marca; con YouTube no hay cómo saberlo).
- Volumen con tope.
- La IA contesta como para un niño.
- Videos solo en el horario que se eligió.

Quién es niño lo dice «aprende mi voz»: las reglas aplican cuando VOXA reconoce su voz. Si no
reconoce a nadie, aplican solo con «para todos». Se enciende por voz («activa el modo niños»,
para todos); se apaga solo desde el celular, para que no lo apaguen los niños.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from voxa.config import KidsConfig
from voxa.core.people import speaker
from voxa.departure import parse_time
from voxa.nlu.normalize import strip_accents

log = logging.getLogger(__name__)

AI_HINT = (
    "\n\nAhora te habla un niño o una niña: contesta con palabras sencillas, de forma amable y apropiada "
    "para su edad, sin contenido para adultos, violencia, sustos ni temas delicados; si pregunta algo así, "
    "sugiere con cariño que le pregunte a un adulto de la familia."
)


def _same(a: str, b: str) -> bool:
    """«María José», «maria-jose» y «Maria jose» son la misma persona."""
    def plain(name: str) -> str:
        return " ".join(strip_accents(name.lower()).replace("-", " ").split())

    return plain(a) == plain(b)


class KidsRules:
    def __init__(
        self,
        config: KidsConfig,
        *,
        clock: Callable[[], datetime] = datetime.now,
        save: Callable[[dict], None] | None = None,
    ) -> None:
        self.config = config
        self._clock = clock
        self._save = save
        self.guarding = False
        """La música que suena la pidió alguien con las reglas de niños: se saltan las explícitas."""

    def applies(self) -> bool:
        """¿Las reglas aplican a quien habla en este turno?"""
        kids = self.config
        if not kids.enabled:
            return False
        if kids.everyone:
            return True
        person = speaker()
        return person is not None and any(_same(person, child) for child in kids.children)

    def clean_music(self) -> bool:
        return self.applies() and self.config.clean_music

    def music_started(self) -> None:
        """Se puso música nueva: se vigila si la pidió alguien con las reglas de niños."""
        self.guarding = self.clean_music()

    def watching_music(self) -> bool:
        kids = self.config
        return kids.enabled and kids.clean_music and (kids.everyone or self.guarding)

    def volume(self, percent: int) -> int:
        """El volumen pedido, con el tope de los niños si aplica."""
        if self.applies() and self.config.max_volume:
            return min(percent, self.config.max_volume)
        return percent

    def video_hours(self) -> tuple[str, str] | None:
        """El horario de videos («16:00», «19:00») si ahora no se puede; ``None`` si sí se puede."""
        kids = self.config
        if not self.applies() or not kids.video_from or not kids.video_until:
            return None
        start, end = parse_time(kids.video_from), parse_time(kids.video_until)
        if start is None or end is None:
            return None
        now = self._clock()
        minute = now.hour * 60 + now.minute
        first, last = start[0] * 60 + start[1], end[0] * 60 + end[1]
        allowed = first <= minute < last if first <= last else (minute >= first or minute < last)
        return None if allowed else (kids.video_from, kids.video_until)

    def turn_on(self) -> None:
        """Por voz: para todos, hasta que se apague desde el celular."""
        self.config = replace(self.config, enabled=True, everyone=True)
        if self._save is not None:
            try:
                self._save({"enabled": True, "everyone": True})
            except OSError as exc:
                log.warning("No pude guardar el modo niños: %s", exc)


def saver(config_file: Path) -> Callable[[dict], None]:
    """Guarda en ajustes.json (sin reiniciar: las reglas ya cambiaron en memoria)."""
    from voxa.settings import save_settings, settings_path

    return lambda values: save_settings(settings_path(config_file), "kids", values)


async def skip_explicit(music) -> bool:
    """Si lo que suena es explícito, pasa a la siguiente canción; ``True`` si la saltó."""
    current = await music.now_playing()
    if current is None or not current.playing or not current.explicit:
        return False
    log.info("Modo niños: salto «%s» (explícita)", current.title)
    await music.next()
    return True
