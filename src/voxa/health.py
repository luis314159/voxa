"""¿Algo impide que VOXA funcione bien? Sin internet, sin micrófono, Spotifast cerrado…

La pantalla pinta el anillo en ámbar con el primer problema («Sin internet») y el diagnóstico
muestra todos con su detalle. Unos problemas se revisan solos cada minuto; otros los reporta
quien los detecta (el micrófono que no abre, los modelos de voz que faltan).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from voxa.services.music_backend import BackendUnavailable, NowPlaying

log = logging.getLogger(__name__)

# Orden en que se muestran: lo que deja a VOXA sorda o muda primero.
PRIORITY = ("voz", "microfono", "activacion", "internet", "spotify", "musica")


@dataclass(frozen=True)
class Problem:
    id: str
    text: str
    """Corto, para la pantalla: «Sin internet»."""
    detail: str = ""
    """Qué pasó o qué hacer, para el diagnóstico."""


Check = Callable[[], Awaitable["Problem | None"]]


class Health:
    def __init__(self, checks: list[Check] | None = None, on_change: Callable[[], None] | None = None) -> None:
        self._checks = checks or []
        self.on_change = on_change
        self._reported: dict[str, Problem] = {}
        self._checked: dict[str, Problem] = {}

    @property
    def problems(self) -> list[Problem]:
        found = {**self._checked, **self._reported}
        rank = {name: n for n, name in enumerate(PRIORITY)}
        return sorted(found.values(), key=lambda p: (rank.get(p.id, len(PRIORITY)), p.id))

    def report(self, problem: Problem) -> None:
        if self._reported.get(problem.id) != problem:
            log.warning("Problema: %s (%s)", problem.text, problem.detail)
            self._reported[problem.id] = problem
            self._changed()

    def clear(self, problem_id: str) -> None:
        if self._reported.pop(problem_id, None) is not None:
            self._changed()

    async def check(self) -> None:
        results = await asyncio.gather(*(c() for c in self._checks), return_exceptions=True)
        checked = {}
        for result in results:
            if isinstance(result, BaseException):
                log.error("Una revisión de salud falló", exc_info=result)
            elif result is not None:
                checked[result.id] = result
        if checked != self._checked:
            for problem in checked.values():
                if problem.id not in self._checked:
                    log.warning("Problema: %s (%s)", problem.text, problem.detail)
            self._checked = checked
            self._changed()

    async def run(self, every: float = 60.0) -> None:
        while True:
            await self.check()
            await asyncio.sleep(every)

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()


def internet_check(host: str = "api.spotify.com", port: int = 443, timeout: float = 5.0) -> Check:
    """Abre (y cierra) una conexión TCP: sin enviar nada, basta para saber si hay red y DNS."""

    async def check() -> Problem | None:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        except (OSError, asyncio.TimeoutError) as exc:
            return Problem("internet", "Sin internet", f"No pude conectar con {host}: {exc or 'tiempo agotado'}")
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        return None

    return check


def spotify_check(client_id: str, token_path: Path) -> Check:
    async def check() -> Problem | None:
        if not client_id:
            return Problem("spotify", "Falta conectar Spotify", "Pon el Client ID en config.toml y corre: voxa spotify-login")
        if not token_path.exists():
            return Problem("spotify", "Falta conectar Spotify", "Corre: voxa spotify-login")
        return None

    return check


def player_check(now_playing: Callable[[], Awaitable[NowPlaying | None]], player: str) -> Check:
    async def check() -> Problem | None:
        try:
            await now_playing()
        except BackendUnavailable as exc:
            return Problem("musica", "Spotifast no responde", f"Reproductor «{player}»: {exc}")
        return None

    return check
