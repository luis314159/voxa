"""Punto de entrada: ``voxa texto | voz | decir | escuchar | sonidos | spotify-login``."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import http.server
import logging
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

from voxa.app import SetupError, build_app, build_tts, build_voice
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


def _device(value: str) -> str | int | None:
    if not value:
        return None
    return int(value) if value.isdigit() else value


async def run_voice_mode(config: Config, simulated: bool) -> None:
    from voxa.audio.devices import Microphone

    loop = asyncio.get_running_loop()
    session = None

    def on_ring(timer: Timer) -> None:
        print(f"\n[alarma] {ring_phrase(timer)}")
        if session is not None:
            loop.create_task(session.announce(ring_phrase(timer)))

    app = build_app(config, simulated=simulated, on_ring=on_ring)
    print("Cargando modelos de voz…")
    session = await asyncio.to_thread(build_voice, config, app, simulated=simulated)
    await asyncio.to_thread(session.warm_up)
    ticker = asyncio.create_task(app.timers.run())
    try:
        async with Microphone(_device(config.voice.input_device)) as mic:
            print("Listo. Pulsa Enter y habla (o escribe una orden). «salir» para terminar.")
            while True:
                try:
                    line = await asyncio.to_thread(input, "🎙  ")
                except EOFError:
                    break
                if line.strip().lower() in _EXIT_WORDS:
                    break
                if line.strip():
                    response = await app.assistant.handle_text(line)
                    print(render(response))
                    await session.say(response)
                    continue
                result = await session.turn(mic)
                if result.heard is None:
                    print("(no escuché nada)")
                    continue
                print(f"Escuché: «{result.heard}»")
                if result.response:
                    print(render(result.response))
                print(f"   {result.timings}")
    finally:
        ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ticker


async def say_text(config: Config, text: str) -> None:
    from voxa.audio.devices import SpeakerOutput

    tts = await asyncio.to_thread(build_tts, config)
    start = time.perf_counter()
    clip = await asyncio.to_thread(tts.synthesize, text)
    print(f"Síntesis: {time.perf_counter() - start:.2f}s · audio: {clip.seconds:.1f}s")
    await SpeakerOutput(_device(config.voice.output_device), config.voice.lead_in_ms).play(clip)


async def listen_file(config: Config, path: Path, simulated: bool) -> None:
    from voxa.audio.clip import MIC_RATE, Clip

    app = build_app(config, simulated=simulated)
    session = await asyncio.to_thread(build_voice, config, app, simulated=simulated)
    audio = Clip.load(path).resampled(MIC_RATE).to_int16()
    result = await session.respond_to_audio(audio)
    print(f"Escuché: «{result.heard}»")
    if result.response:
        print(render(result.response))
    print(f"   {result.timings}")


async def play_sounds(config: Config, save_dir: Path | None) -> None:
    from voxa.audio.devices import SpeakerOutput
    from voxa.audio.sounds import make_sounds

    output = SpeakerOutput(_device(config.voice.output_device), config.voice.lead_in_ms)
    for name, clip in make_sounds().items():
        if save_dir:
            clip.save(save_dir / f"{name}.wav")
            print(f"Guardado {save_dir / f'{name}.wav'}")
        else:
            print(f"♪ {name}")
            await output.play(clip.with_silence(after_ms=600))


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
    voice = sub.add_parser("voz", help="pulsa Enter y habla: micrófono, STT, respuesta hablada")
    voice.add_argument("--simulado", action="store_true", help="música y volumen simulados")
    say = sub.add_parser("decir", help="prueba la voz de VOXA")
    say.add_argument("texto", nargs="+")
    listen = sub.add_parser("escuchar", help="procesa una grabación WAV como si fuera una orden")
    listen.add_argument("archivo", type=Path)
    listen.add_argument("--simulado", action="store_true")
    sounds = sub.add_parser("sonidos", help="reproduce los sonidos de VOXA")
    sounds.add_argument("--guardar", type=Path, metavar="CARPETA", help="guarda los WAV en lugar de reproducirlos")
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
    commands = {
        "texto": lambda: run_text_mode(config, args.simulado),
        "voz": lambda: run_voice_mode(config, args.simulado),
        "decir": lambda: say_text(config, " ".join(args.texto)),
        "escuchar": lambda: listen_file(config, args.archivo, args.simulado),
        "sonidos": lambda: play_sounds(config, args.guardar),
    }
    try:
        asyncio.run(commands[args.command]())
    except SetupError as exc:
        print(exc)
        return 2
    except KeyboardInterrupt:
        pass
    return 0
