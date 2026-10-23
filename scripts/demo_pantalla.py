"""Demo de la pantalla de cocina sin micrófono ni Spotify.

    python scripts/demo_pantalla.py            # y en otra terminal: voxa-ui
    python scripts/demo_pantalla.py --fase listening --alarma

Llena temporizadores, música y una conversación de ejemplo y recorre las fases del anillo.
Los botones de la pantalla funcionan contra la música y los temporizadores simulados.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
from dataclasses import replace

from voxa.app import build_app
from voxa.config import Config
from voxa.core.types import Response
from voxa.display import Display
from voxa.service import Service
from voxa.services.music_backend import NowPlaying

EXCHANGES = [
    ("cuánto le falta al arroz", "Faltan 7 minutos y 30 segundos."),
    ("pon a juan gabriel", "Juan Gabriel."),
    ("va a llover hoy", "No se esperan lluvias hoy. Máxima de 24 grados."),
]
CYCLE = [("listening", 3.0), ("thinking", 1.0), ("speaking", 2.5), ("idle", 6.0)]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fase", choices=[name for name, _ in CYCLE], help="fija la fase (para capturas)")
    parser.add_argument("--alarma", action="store_true", help="incluye un temporizador sonando")
    parser.add_argument("--sin-temporizadores", action="store_true")
    parser.add_argument("--sin-musica", action="store_true")
    parser.add_argument("--portada", help="URL (https:// o file://) de la portada del disco")
    parser.add_argument("--puerto", type=int, default=8766)
    args = parser.parse_args()

    app = build_app(Config(), simulated=True)
    service = Service(app, Display(app.timers, app.now_playing))
    music = app.now_playing.__self__  # la música simulada de la demo

    if not args.sin_temporizadores:
        app.timers.add(900, "el arroz").ends_at -= 450
        app.timers.add(180, "los huevos").ends_at -= 108
        if args.alarma:
            app.timers.add(0, "el pan")
    if not args.sin_musica:
        music.current = NowPlaying(
            "Amor eterno", "Rocío Dúrcal", album="Canta a Juan Gabriel", art_url=args.portada, position=61.0, length=287.0
        )

    async with service.running(args.puerto):
        print(f"Demo lista en el puerto {args.puerto}. Abre la pantalla: voxa-ui (Ctrl+C para salir)")
        for n in itertools.count():
            heard, answer = EXCHANGES[n % len(EXCHANGES)]
            for phase, seconds in CYCLE if not args.fase else [(args.fase, 8.0)]:
                service.display.phase(phase)
                if phase == "speaking" or args.fase:
                    service.display.exchange(heard, Response(answer))
                await asyncio.sleep(seconds)
                if music.current and music.current.playing:
                    current = music.current
                    position = ((current.position or 0) + seconds) % (current.length or 1)
                    music.current = replace(current, position=position)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
