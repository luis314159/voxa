"""Punto de entrada: ``voxa texto`` y ``voxa spotify-login``."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import http.server
import logging
import secrets
import sys
import threading
import urllib.parse
import webbrowser

from voxa.app import build_app
from voxa.config import Config, load_config
from voxa.core.types import Response
from voxa.services.http import UrllibHttp
from voxa.services.spotify_auth import SpotifyAuth, new_verifier
from voxa.skills.timers import ring_phrase
from voxa.state.timers import Timer

_EXIT_WORDS = {"salir", "exit", "quit", "adios"}


def render(response: Response) -> str:
    if response.speech:
        return f"VOXA: {response.speech}"
    return f"VOXA: [sonido: {response.sound or 'ok'}]"


async def run_text_mode(config: Config, simulated: bool) -> None:
    def on_ring(timer: Timer) -> None:
        print(f"\n[alarma] {ring_phrase(timer)}  (di «ya» o «para»)\n> ", end="", flush=True)

    app = build_app(config, simulated=simulated, on_ring=on_ring)
    ticker = asyncio.create_task(app.timers.run())
    mode = "simulado" if simulated else "real"
    print(f"VOXA en modo texto ({mode}). Escribe una orden como si la dijeras; «salir» para terminar.")
    try:
        while True:
            try:
                line = await asyncio.to_thread(input, "> ")
            except EOFError:
                break
            if line.strip().lower() in _EXIT_WORDS:
                break
            if not line.strip():
                continue
            print(render(await app.assistant.handle_text(line)))
    finally:
        ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ticker


def spotify_login(config: Config) -> int:
    """Autoriza a VOXA en Spotify una sola vez (OAuth PKCE con redirect a 127.0.0.1)."""
    if not config.spotify.client_id:
        print("Falta spotify.client_id en ~/.config/voxa/config.toml (ver docs/fase0_guia.md).")
        return 1
    auth = SpotifyAuth(config.spotify.client_id, config.spotify.redirect_uri, config.spotify_token_path, UrllibHttp())
    verifier, state = new_verifier(), secrets.token_urlsafe(16)
    redirect = urllib.parse.urlparse(config.spotify.redirect_uri)
    received: dict[str, str] = {}
    done = threading.Event()

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if urllib.parse.urlparse(self.path).path != redirect.path:
                self.send_error(404)
                return
            received.update(query)
            ok = query.get("state") == state and "code" in query
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = "Listo. VOXA ya puede usar Spotify; puedes cerrar esta pestaña." if ok else "La autorización falló."
            self.wfile.write(f"<h2>{message}</h2>".encode())
            done.set()

        def log_message(self, *args) -> None:
            pass

    server = http.server.HTTPServer((redirect.hostname or "127.0.0.1", redirect.port or 80), Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = auth.authorization_url(verifier, state)
    print("Abre este enlace para autorizar a VOXA (se intentará abrir solo):\n" + url)
    webbrowser.open(url)
    try:
        if not done.wait(timeout=300):
            print("Se agotó el tiempo de espera.")
            return 1
    finally:
        server.shutdown()

    if received.get("state") != state or "code" not in received:
        print(f"Spotify no autorizó: {received.get('error', 'respuesta inválida')}")
        return 1
    asyncio.run(auth.exchange_code(received["code"], verifier))
    print(f"Autorizado. Token guardado en {config.spotify_token_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voxa", description="VOXA — asistente de voz familiar.")
    parser.add_argument("-v", "--verbose", action="store_true", help="muestra el registro detallado")
    sub = parser.add_subparsers(dest="command", required=True)
    text = sub.add_parser("texto", help="usa VOXA escribiendo en lugar de hablar")
    text.add_argument("--simulado", action="store_true", help="música y volumen simulados (sin Spotify ni PipeWire)")
    sub.add_parser("spotify-login", help="autoriza a VOXA en tu cuenta de Spotify")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")
    config = load_config()

    if args.command == "spotify-login":
        return spotify_login(config)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_text_mode(config, args.simulado))
    return 0
