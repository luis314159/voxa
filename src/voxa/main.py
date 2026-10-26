"""Punto de entrada: ``voxa texto | voz | servicio | decir | escuchar | sonidos | spotify-login | ia-…``."""

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
from dataclasses import replace
from pathlib import Path

import voxa
from voxa import diagnostics
from voxa.app import SetupError, build_app, build_tts, build_voice, build_wake
from voxa.config import Config, config_path, load_config
from voxa.core.types import Response
from voxa.health import Problem
from voxa.service import Service
from voxa.services.http import UrllibHttp
from voxa.services.spotify_auth import SpotifyAuth, new_verifier
from voxa.skills.timers import ring_phrase
from voxa.state.timers import Timer

_EXIT_WORDS = {"salir", "exit", "quit", "adios"}


def render(response: Response) -> str:
    if response.speech:
        return f"VOXA: {response.speech}"
    return f"VOXA: [sonido: {response.sound or 'ok'}]"


def _service(config: Config, simulated: bool, on_ring_print: bool = True) -> Service:
    service: Service | None = None

    def on_ring(timer: Timer) -> None:
        if on_ring_print:
            print(f"\n[alarma] {ring_phrase(timer)}")
        if service is not None:
            service.on_ring(timer)

    app = build_app(config, simulated=simulated, on_ring=on_ring)
    service = Service.create(app)
    return service


def _display_port(config: Config) -> int | None:
    return config.display.port if config.display.enabled else None


async def run_text_mode(config: Config, simulated: bool) -> None:
    service = _service(config, simulated)
    async with service.running(_display_port(config)):
        mode = "simulado" if simulated else "real"
        print(f"VOXA en modo texto ({mode}). Escribe una orden como si la dijeras; «salir» para terminar.")
        while True:
            try:
                line = await asyncio.to_thread(input, "> ")
            except EOFError:
                break
            if line.strip().lower() in _EXIT_WORDS:
                break
            if line.strip():
                print(render(await service.handle_text(line)))


def _device(value: str) -> str | int | None:
    if not value:
        return None
    return int(value) if value.isdigit() else value


async def _with_voice(config: Config, service: Service, simulated: bool):
    print("Cargando modelos de voz…")
    session = await asyncio.to_thread(build_voice, config, service.app, simulated=simulated)
    await asyncio.to_thread(session.warm_up)
    return session


def _attach_wake(config: Config, service: Service) -> bool:
    """Carga «Hey Voxa» si está activado; si faltan sus modelos, VOXA sigue con «toca para hablar»."""
    if not config.wake.enabled:
        return False
    try:
        service.attach_wake(build_wake(config))
    except SetupError as exc:
        logging.getLogger(__name__).error("Sin «Hey Voxa»: %s", exc)
        service.health.report(Problem("activacion", "«Hey Voxa» no está disponible", str(exc)))
        return False
    return True


async def run_voice_mode(config: Config, simulated: bool) -> None:
    from voxa.audio.devices import Microphone

    service = _service(config, simulated)
    session = await _with_voice(config, service, simulated)
    async with service.running(_display_port(config)):
        service.attach_voice(session, Microphone(_device(config.voice.input_device)))
        if not service.mic.is_open:
            print("No pude abrir el micrófono; revisa input_device en config.toml (python -m sounddevice).")
            return
        wake = "di «Hey Voxa» o " if _attach_wake(config, service) else ""
        print(f"Listo: {wake}pulsa Enter y habla (o escribe una orden). «salir» para terminar.")
        while True:
            try:
                line = await asyncio.to_thread(input, "🎙  ")
            except EOFError:
                break
            if line.strip().lower() in _EXIT_WORDS:
                break
            if line.strip():
                print(render(await service.handle_text(line)))
                continue
            result = await service.talk()
            if result is None:
                continue
            if result.heard is None:
                print("(no escuché nada)")
                continue
            print(f"Escuché: «{result.heard}»")
            if result.response:
                print(render(result.response))
            print(f"   {result.timings}")


async def run_service(config: Config, simulated: bool) -> None:
    """Modo permanente (systemd): sin teclado; las órdenes llegan por la pantalla y, en la Fase 3, «Hey Voxa»."""
    from voxa.audio.devices import Microphone

    log = logging.getLogger(__name__)
    service = _service(config, simulated, on_ring_print=False)
    # La pantalla se conecta desde el principio: si falta la voz, al menos lo dice en ámbar.
    async with service.running(_display_port(config)):
        try:
            session = await _with_voice(config, service, simulated)
        except SetupError as exc:
            log.error("Sin voz: %s", exc)
            service.health.report(Problem("voz", "Faltan los modelos de voz", str(exc)))
        else:
            service.attach_voice(session, Microphone(_device(config.voice.input_device)))
            _attach_wake(config, service)
            print("VOXA lista.")
        await asyncio.Event().wait()


async def probe_wake_word(config: Config, threshold: float | None, path: Path | None) -> None:
    """Muestra en vivo qué tan seguro está el detector de oír «Hey Voxa» (para calibrar el umbral)."""
    from voxa.audio.clip import MIC_RATE, Clip
    from voxa.audio.wakeword import CHUNK

    if threshold is not None:
        config = replace(config, wake=replace(config.wake, threshold=threshold))
    detector = build_wake(config)
    print(f"Umbral: {detector.threshold:.2f} · bloques seguidos: {config.wake.patience}")

    def show(at: float, detected: bool) -> None:
        score = detector.last_score
        bar = "█" * int(score * 40)
        mark = "  ← «Hey Voxa»" if detected else ""
        print(f"{at:7.2f}s {score:4.2f} {bar:<40}|{mark}", flush=True)

    if path is not None:  # una grabación: cada activación con su segundo
        audio = Clip.load(path).resampled(MIC_RATE).to_int16()
        hits = 0
        for i in range(0, len(audio) - CHUNK + 1, CHUNK):
            if detector.feed(audio[i : i + CHUNK]):
                hits += 1
                show(i / MIC_RATE, True)
        print(f"{hits} activaciones en {len(audio) / MIC_RATE:.0f} s")
        return

    from voxa.audio.devices import Microphone

    print("Di «Hey Voxa» unas cuantas veces, de cerca y de lejos, con y sin música. Ctrl+C para terminar.")
    async with Microphone(_device(config.voice.input_device)) as mic:
        started = time.monotonic()
        while True:
            frame = await mic.read()
            detected = detector.feed(frame)
            if detected or detector.last_score >= 0.1:
                show(time.monotonic() - started, detected)
            await asyncio.sleep(0)


async def record_wake_samples(config: Config, person: str, times: int, talk_seconds: int) -> None:
    """Graba a una persona diciendo «Hey Voxa» y platicando normal (para el verificador familiar)."""
    import numpy as np

    from voxa.audio.clip import MIC_RATE, Clip
    from voxa.audio.devices import Microphone

    from voxa.enroll import folder_name

    folder = config.wake_recordings_dir / folder_name(person)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    async def record(mic: Microphone, seconds: float) -> np.ndarray:
        mic.clear()
        frames = [await mic.read() for _ in range(int(seconds * MIC_RATE / 1280))]
        return np.concatenate(frames)

    print(f"Grabaciones en {folder} (se quedan en esta PC).")
    async with Microphone(_device(config.voice.input_device)) as mic:
        for n in range(1, times + 1):
            await asyncio.to_thread(input, f"[{n}/{times}] Pulsa Enter y di «Hey Voxa» (como le hablarías desde la cocina)…")
            audio = await record(mic, 2.5)
            Clip.from_int16(audio, MIC_RATE).save(folder / f"si_{stamp}_{n:02d}.wav")
        if talk_seconds:
            await asyncio.to_thread(
                input, f"Ahora platica normal o lee algo en voz alta durante {talk_seconds} s, SIN decir «Voxa». Enter para empezar…"
            )
            audio = await record(mic, talk_seconds)
            Clip.from_int16(audio, MIC_RATE).save(folder / f"no_{stamp}.wav")
    print("Listo. Cuando hayan grabado todos: voxa entrenar-verificador")


def update(check_only: bool, version: str | None, force: bool) -> int:
    from voxa import update as updates

    current = voxa.__version__
    if version is None:
        try:
            latest = asyncio.run(updates.latest_version(UrllibHttp()))
        except updates.NoReleases:
            print(f"Todavía no hay releases publicados en {updates.RELEASES}.")
            return 1
        if latest is None:
            print(f"No pude consultar los releases ({updates.RELEASES}). ¿Hay internet?")
            return 1
        if not updates.is_newer(latest, current) and not force:
            print(f"Ya tienes la versión más reciente: {current}.")
            return 0
        print(f"Tienes la {current}; la más reciente es la {latest}.")
        if check_only:
            print("Para instalarla: voxa actualizar")
            return 0
    elif check_only:
        print(f"Tienes la {current}.")
        return 0
    print("Instalando… (VOXA se reinicia al final; puede pedir tu contraseña)")
    return updates.run_installer(version)


def check_installation() -> int:
    from voxa.checkup import FAIL, render, run_checkup

    findings = asyncio.run(run_checkup(config_path()))
    print(render(findings, color=sys.stdout.isatty()))
    return 1 if any(f.status == FAIL for f in findings) else 0


def set_ai_key(config: Config) -> int:
    """Pide la llave sin mostrarla y la guarda con permisos 600 (nunca en el repositorio)."""
    import getpass

    from voxa.services.ai import save_key

    provider = config.ai.provider
    print(f"Llave de la IA ({provider}). Se guarda en {config.ai_key_path}, solo legible por tu usuario.")
    key = getpass.getpass("Pega la llave y pulsa Enter (no se verá): ").strip()
    if not key:
        print("No se guardó nada.")
        return 1
    save_key(config.ai_key_path, key)
    print("Guardada. Pruébala con: voxa ia-probar")
    if not config.ai.enabled:
        print("Ojo: la IA sigue apagada. Pon enabled = true en [ai] de ~/.config/voxa/config.toml.")
    return 0


async def link_telegram(config: Config, new_token: bool) -> int:
    """Guarda el token del bot (si hace falta) y vincula un chat con un código de 6 dígitos."""
    import getpass

    from voxa.services.ai import save_key
    from voxa.telegram import Chats, TelegramApi, TelegramError, link_chat, read_token

    token = None if new_token else read_token(config.telegram_token_path)
    if token is None:
        print("Crea el bot en Telegram con @BotFather (/newbot) y copia el token que te da.")
        token = getpass.getpass("Pega el token y pulsa Enter (no se verá): ").strip()
        if not token:
            print("No se guardó nada.")
            return 1
    api = TelegramApi(token, UrllibHttp(daemon=True))
    try:
        me = await api.call("getMe")
    except TelegramError as exc:
        print(f"Telegram no aceptó el token: {exc}")
        return 2
    save_key(config.telegram_token_path, token)
    print(f"Bot: @{me.get('username')} (token guardado en {config.telegram_token_path}, solo legible por ti).")
    chats = Chats(config.telegram_chats_path, config.telegram_code_path)
    try:
        linked = await link_chat(api, chats)
    except TelegramError as exc:
        print(f"Telegram: {exc}")
        return 2
    if not linked:
        print("Nadie mandó el código a tiempo. Vuelve a correr: voxa telegram-vincular")
        return 1
    print("Chat vinculado: " + ", ".join(chats.all().values()))
    if not config.telegram.enabled:
        print("Falta encenderlo: pon enabled = true en [telegram] de ~/.config/voxa/config.toml y reinicia VOXA.")
    return 0


async def probe_ai(config: Config, question: str) -> int:
    """Una pregunta de prueba: muestra respuesta, tiempo y costo (aunque la IA esté apagada en config)."""
    # Simulado: si la IA pide una orden («pon música…»), se ve qué haría sin tocar Spotify ni el volumen.
    app = build_app(replace(config, ai=replace(config.ai, enabled=True)), simulated=True)
    ai = app.ai
    if ai is None:
        print(f"La IA no está lista: {app.ai_problem}")
        return 2
    ai.on_setup_error = lambda detail: print(f"  ⚠ {detail}")
    print(f"{ai.chat.name} · pregunta: «{question}»")
    start = time.perf_counter()
    response = await ai(question)
    elapsed = time.perf_counter() - start
    print(render(response) if response else "VOXA: (no es una pregunta: no se mandó)")
    print(f"{elapsed:.1f} s · {ai.last_cost:.5f} USD · llevas {ai.usage.summary()}")
    return 0


def train_wake_verifier(config: Config) -> int:
    from voxa.enroll import NotEnoughRecordings, train_family_verifier

    try:
        result = train_family_verifier(config)
    except NotEnoughRecordings as exc:
        print(f"Faltan grabaciones: {exc} (di «Hey Voxa, aprende mi voz» o voxa grabar-activacion --persona NOMBRE).")
        return 1
    for note in result.notes:
        print(f"  ⚠ {note}")
    print(f"Verificador ({result.people} personas): acepta {result.accepted:.0%} de los «Hey Voxa» grabados "
          f"y descarta {result.rejected:.0%} de la plática.")
    print(f"Guardado en {config.verifier_path}. Reinicia VOXA: systemctl --user restart voxa")
    return 0


async def say_text(config: Config, text: str, show_phonemes: bool = False) -> None:
    from voxa.audio.devices import SpeakerOutput

    tts = await asyncio.to_thread(build_tts, config)
    if show_phonemes:
        print(f"Fonemas: {tts.phonemes(text)}")
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
    parser.add_argument("--version", action="version", version=f"VOXA {voxa.__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    text = sub.add_parser("texto", help="usa VOXA escribiendo en lugar de hablar")
    text.add_argument("--simulado", action="store_true", help="música y volumen simulados (sin Spotify ni PipeWire)")
    voice = sub.add_parser("voz", help="pulsa Enter y habla: micrófono, STT, respuesta hablada")
    voice.add_argument("--simulado", action="store_true", help="música y volumen simulados")
    daemon = sub.add_parser("servicio", help="modo permanente para systemd: voz + pantalla, sin teclado")
    daemon.add_argument("--simulado", action="store_true", help="música y volumen simulados")
    say = sub.add_parser("decir", help="prueba la voz de VOXA")
    say.add_argument("texto", nargs="+")
    say.add_argument("--fonemas", action="store_true", help="muestra los fonemas (para ajustar pronunciacion.yaml)")
    listen = sub.add_parser("escuchar", help="procesa una grabación WAV como si fuera una orden")
    listen.add_argument("archivo", type=Path)
    listen.add_argument("--simulado", action="store_true")
    sounds = sub.add_parser("sonidos", help="reproduce los sonidos de VOXA")
    sounds.add_argument("--guardar", type=Path, metavar="CARPETA", help="guarda los WAV en lugar de reproducirlos")
    wake = sub.add_parser("probar-activacion", help="muestra en vivo cómo oye VOXA «Hey Voxa» (para calibrar)")
    wake.add_argument("--umbral", type=float, help="prueba otro umbral (0–1)")
    wake.add_argument("--archivo", type=Path, help="busca «Hey Voxa» en una grabación WAV en lugar del micrófono")
    record = sub.add_parser("grabar-activacion", help="graba a alguien de la familia diciendo «Hey Voxa» (verificador)")
    record.add_argument("--persona", required=True, help="nombre (solo para ordenar las grabaciones)")
    record.add_argument("--veces", type=int, default=8)
    record.add_argument("--platica", type=int, default=30, metavar="SEGUNDOS", help="segundos de plática normal")
    sub.add_parser("entrenar-verificador", help="entrena el verificador familiar con las grabaciones")
    sub.add_parser("revisar", help="revisa la instalación y dice qué falta y cómo arreglarlo")
    upgrade = sub.add_parser("actualizar", help="instala la versión más reciente de VOXA (releases de GitHub)")
    upgrade.add_argument("--revisar", action="store_true", help="solo dice si hay una versión nueva")
    upgrade.add_argument("--version", metavar="X.Y.Z", help="instala esa versión (también sirve para regresar)")
    upgrade.add_argument("--forzar", action="store_true", help="reinstala aunque ya sea la más reciente")
    sub.add_parser("ia-clave", help="guarda la llave de la IA (Claude, OpenAI, Azure…)")
    probe_ai_cmd = sub.add_parser("ia-probar", help="hace una pregunta de prueba a la IA y dice cuánto costó")
    probe_ai_cmd.add_argument("pregunta", nargs="*")
    sub.add_parser("spotify-login", help="autoriza a VOXA en tu cuenta de Spotify")
    telegram = sub.add_parser("telegram-vincular", help="conecta el bot de Telegram de la lista del súper")
    telegram.add_argument("--nuevo-token", action="store_true", help="pide el token otra vez (bot nuevo)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    diagnostics.install()
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "revisar":
        return check_installation()
    if args.command == "actualizar":
        return update(args.revisar, args.version, args.forzar)
    config = load_config()

    if args.command == "spotify-login":
        return spotify_login(config)
    if args.command == "entrenar-verificador":
        return train_wake_verifier(config)
    if args.command == "ia-clave":
        return set_ai_key(config)
    if args.command == "telegram-vincular":
        try:
            return asyncio.run(link_telegram(config, args.nuevo_token))
        except KeyboardInterrupt:
            return 1
    if args.command == "ia-probar":
        question = " ".join(args.pregunta) or "¿Cuántos minutos se cuece un huevo tibio?"
        return asyncio.run(probe_ai(config, question))
    commands = {
        "texto": lambda: run_text_mode(config, args.simulado),
        "voz": lambda: run_voice_mode(config, args.simulado),
        "servicio": lambda: run_service(config, args.simulado),
        "decir": lambda: say_text(config, " ".join(args.texto), args.fonemas),
        "escuchar": lambda: listen_file(config, args.archivo, args.simulado),
        "sonidos": lambda: play_sounds(config, args.guardar),
        "probar-activacion": lambda: probe_wake_word(config, args.umbral, args.archivo),
        "grabar-activacion": lambda: record_wake_samples(config, args.persona, args.veces, args.platica),
    }
    try:
        asyncio.run(commands[args.command]())
    except SetupError as exc:
        print(exc)
        return 2
    except KeyboardInterrupt:
        pass
    return 0
