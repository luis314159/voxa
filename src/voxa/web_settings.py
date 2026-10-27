"""Ajustes desde el celular: todo lo que antes pedía la terminal o editar ``config.toml``.

Spotify, el clima (buscando la ciudad), la IA, Telegram, el calendario, «aprende mi voz», qué
funciones están encendidas y la revisión de la instalación. Las llaves y tokens se guardan en sus
archivos 600 y nunca se devuelven al celular (solo si ya hay una). Tras guardar, VOXA se reinicia
sola para usar lo nuevo.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import voxa
from voxa.services.http import Http, UrllibHttp
from voxa.services.calendar import personal_calendars, save_personal_calendar
from voxa.services.spotifast_setup import REDIRECT as SPOTIFAST_REDIRECT
from voxa.settings import SettingsError, read_secret, restart_soon, save_secret, save_settings, settings_path

if TYPE_CHECKING:
    from voxa.service import Service

log = logging.getLogger(__name__)

SPOTIFY_MINUTES = 10
AI_TEST_QUESTION = "¿Cuántos minutos se cuece un huevo tibio?"
RESTARTING = "Guardado. VOXA se reinicia en unos segundos para usarlo."
RESTART_BY_HAND = "Guardado. Reinicia VOXA para usarlo."


@dataclass
class _SpotifyPending:
    verifier: str
    state: str
    until: float
    server: asyncio.base_events.Server | None = None


def _from_package() -> bool:
    from voxa.update import from_package

    return from_package()


class SettingsApi:
    def __init__(
        self,
        service: Service,
        config_file: Path,
        *,
        http: Http | None = None,
        restart: Callable[[], Awaitable[bool]] = restart_soon,
        checkup: Callable[[Path], Awaitable[list]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._service = service
        self._config_file = config_file
        self._http = http or UrllibHttp()
        self._restart = restart
        self._checkup = checkup
        self._clock = clock
        self._spotify: _SpotifyPending | None = None

    @property
    def config(self):
        return self._service.app.config

    # --- lo que ve el celular ---------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        from voxa.audio.speaker import family_names
        from voxa.telegram import Chats, read_token

        app, config = self._service.app, self.config
        updater = app.updater
        client_id = config.spotify.client_id
        return {
            "version": voxa.__version__,
            "nueva": updater.available if updater else None,
            "spotify": {
                "client_id": f"{client_id[:4]}…{client_id[-4:]}" if len(client_id) > 8 else client_id,
                "autorizado": config.spotify_token_path.exists(),
                "me_gusta": self._library_granted(),
                "redirect": config.spotify.redirect_uri,
                "redirect_spotifast": SPOTIFAST_REDIRECT,
                "musica": config.music.provider,
                "dispositivo": config.spotify.device_name,
            },
            "clima": {"lugar": config.weather.place, "lat": config.weather.latitude, "lon": config.weather.longitude},
            "ia": {
                "enabled": config.ai.enabled, "provider": config.ai.provider, "model": config.ai.model,
                "endpoint": config.ai.endpoint, "llave": config.ai_key_path.exists(),
                "presupuesto": config.ai.monthly_budget_usd, "listo": app.ai is not None,
                "estado": f"{app.ai.chat.name} · {app.ai.usage.summary()}" if app.ai else app.ai_problem,
            },
            "telegram": {
                "enabled": config.telegram.enabled,
                "token": read_token(config.telegram_token_path) is not None,
                "chats": [{"id": c, "nombre": n} for c, n in
                          Chats(config.telegram_chats_path, config.telegram_code_path).all().items()],
            },
            "calendario": {"enabled": config.calendar.enabled, "url": read_secret(config.calendar_url_path) is not None,
                           "avisar": config.calendar.remind_minutes,
                           "personas": sorted(personal_calendars(config))},
            "voz": {
                "personas": family_names(config.wake_recordings_dir),
                "verificador": config.verifier_path.exists(),
                "grabando": self._service.enrolling,
                "lista": self._enroll_ready(),
                "whisper": config.voice.whisper_model,
                "idioma": config.voice.language,
                "bilingue": config.voice.bilingual,
            },
            "casa": {**(app.house.status() if app.house else {}), "invitacion": self.invitation()},
            "silencio": {"enabled": config.quiet.enabled, "start": config.quiet.start, "end": config.quiet.end,
                         "level": config.quiet.level},
            "ninos": {
                "enabled": config.kids.enabled, "everyone": config.kids.everyone, "children": list(config.kids.children),
                "clean_music": config.kids.clean_music, "max_volume": config.kids.max_volume,
                "video_from": config.kids.video_from, "video_until": config.kids.video_until,
            },
            "rutina": {"salida": config.routine.departure, "dias": list(config.routine.departure_days),
                       "llevar": config.routine.checklist, "musica": config.routine.morning_music},
            "paquete": _from_package(),
            "funciones": {
                "video": config.video.enabled, "actualizar_solo": config.update.automatic,
                "avisar_version": config.update.check,
            },
        }

    def _library_granted(self) -> bool | None:
        from voxa.services.http import UrllibHttp as _Http
        from voxa.services.spotify_auth import LIBRARY_SCOPE, SpotifyAuth

        config = self.config
        if not config.spotify_token_path.exists():
            return None
        auth = SpotifyAuth(config.spotify.client_id, config.spotify.redirect_uri, config.spotify_token_path, _Http())
        return auth.granted(LIBRARY_SCOPE)

    def _enroll_ready(self) -> bool:
        skill = self._service.app.assistant.skill("voice")
        return bool(skill is not None and getattr(skill, "ready", lambda: False)())

    # --- lo que cambia --------------------------------------------------------------------
    async def post(self, path: str, data: dict[str, Any]) -> tuple[int, Any]:
        try:
            match path:
                case "/api/ajustes":
                    return await self._save(str(data.get("seccion", "")), data.get("valores"))
                case "/api/ajustes/revisar":
                    return 200, {"hallazgos": await self._review()}
                case "/api/clima/buscar":
                    return await self._find_city(str(data.get("texto") or ""))
                case "/api/secreto":
                    return await self._secret(str(data.get("tipo", "")), str(data.get("valor") or "").strip(),
                                              str(data.get("persona") or "").strip()[:40] or None)
                case "/api/spotify/autorizar":
                    return await self._spotify_start()
                case "/api/spotify/codigo":
                    return await self._spotify_finish(str(data.get("direccion") or ""))
                case "/api/spotify/abrir":
                    return await self._open_spotifast()
                case "/api/telegram/codigo":
                    return await self._telegram_code()
                case "/api/telegram/quitar":
                    return self._telegram_forget(data.get("id"))
                case "/api/voz/aprender":
                    return self._enroll(str(data.get("nombre") or "").strip()[:40])
                case "/api/ia/probar":
                    return await self._try_ai()
                case "/api/casa/unir":
                    return await self._join(str(data.get("direccion") or ""), str(data.get("cuarto") or ""))
                case "/api/casa/olvidar":
                    house = self._service.app.house
                    if house is None or not house.forget(str(data.get("nombre") or "")):
                        return 404, {"error": "no existe ese cuarto"}
                    return 200, {"respuesta": "Listo: ese cuarto ya no recibe avisos."}
        except SettingsError as exc:
            return 400, {"error": str(exc)}
        return 404, {"error": "no existe"}

    async def _save(self, section: str, values: Any) -> tuple[int, Any]:
        if not isinstance(values, dict) or not values:
            return 400, {"error": "faltan los valores"}
        save_settings(settings_path(self._config_file), section, values)
        return 200, await self._saved()

    async def _saved(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        restarting = await self._restart()
        return {"respuesta": RESTARTING if restarting else RESTART_BY_HAND, "reinicio": restarting, **(extra or {})}

    async def _review(self) -> list[dict[str, str]]:
        from voxa.checkup import run_checkup

        findings = await (self._checkup or run_checkup)(self._config_file)
        return [{"grupo": f.group, "nombre": f.name, "estado": f.status, "detalle": f.detail, "arreglo": f.fix}
                for f in findings]

    async def _find_city(self, text: str) -> tuple[int, Any]:
        from voxa.services.weather import WeatherUnavailable, find_places

        if len(text.strip()) < 2:
            return 400, {"error": "escribe el nombre de la ciudad"}
        try:
            places = await find_places(self._http, text)
        except WeatherUnavailable as exc:
            return 502, {"error": str(exc)}
        return 200, {"lugares": [{"nombre": p.label, "lat": p.latitude, "lon": p.longitude} for p in places]}

    async def _secret(self, kind: str, value: str, person: str | None = None) -> tuple[int, Any]:
        config = self.config
        if not value:
            return 400, {"error": "falta el valor"}
        if kind == "ia":
            save_secret(config.ai_key_path, value)
            save_settings(settings_path(self._config_file), "ai", {"enabled": True})
            return 200, await self._saved()
        if kind == "telegram":
            from voxa.telegram import TelegramApi, TelegramError

            try:
                me = await TelegramApi(value, self._http).call("getMe")
            except TelegramError as exc:
                return 400, {"error": f"Telegram no aceptó el token: {exc}"}
            save_secret(config.telegram_token_path, value)
            save_settings(settings_path(self._config_file), "telegram", {"enabled": True})
            return 200, await self._saved({"bot": me.get("username")})
        if kind == "calendario":
            from voxa.services.calendar import Calendar, CalendarUnavailable, valid_url

            if not valid_url(value):
                return 400, {"error": "esa no parece la dirección iCal (empieza con https:// o webcal://)"}
            try:
                count = await Calendar(lambda: value, self._http, config.calendar_cache_path).check()
            except CalendarUnavailable as exc:
                return 400, {"error": f"no pude leer el calendario: {exc}"}
            if person:
                save_personal_calendar(config, person, value)
            else:
                save_secret(config.calendar_url_path, value)
            save_settings(settings_path(self._config_file), "calendar", {"enabled": True})
            return 200, await self._saved({"eventos": count})
        return 400, {"error": "¿qué llave es?"}

    # --- Spotify: el celular abre la autorización; la respuesta llega al 127.0.0.1 de esta PC ---
    async def _spotify_start(self) -> tuple[int, Any]:
        from voxa.services.spotify_auth import SpotifyAuth, new_verifier

        config = self.config
        if not config.spotify.client_id:
            return 400, {"error": "primero guarda el Client ID de tu app de Spotify"}
        await self._spotify_close()
        pending = _SpotifyPending(new_verifier(), secrets.token_urlsafe(16), self._clock() + SPOTIFY_MINUTES * 60)
        redirect = urllib.parse.urlsplit(config.spotify.redirect_uri)
        try:
            # Si se autoriza desde el navegador de esta misma PC, la respuesta llega sola.
            pending.server = await asyncio.start_server(self._spotify_callback, redirect.hostname or "127.0.0.1",
                                                        redirect.port or 80)
        except OSError as exc:
            log.info("Sin escucha local para Spotify (%s): se pega la dirección desde el celular", exc)
        self._spotify = pending
        auth = SpotifyAuth(config.spotify.client_id, config.spotify.redirect_uri, config.spotify_token_path, self._http)
        return 200, {"url": auth.authorization_url(pending.verifier, pending.state), "redirect": config.spotify.redirect_uri}

    async def _spotify_finish(self, address: str) -> tuple[int, Any]:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(address.strip()).query))
        error = await self._spotify_exchange(query)
        if error:
            return 400, {"error": error}
        return 200, await self._saved()

    async def _spotify_exchange(self, query: dict[str, str]) -> str | None:
        from voxa.services.music_backend import AuthRequired, BackendUnavailable
        from voxa.services.spotify_auth import SpotifyAuth

        pending, config = self._spotify, self.config
        if pending is None or self._clock() > pending.until:
            return "la autorización venció: vuelve a tocar «Conectar con Spotify»"
        if query.get("error"):
            return f"Spotify no autorizó: {query['error']}"
        if "code" not in query or not secrets.compare_digest(query.get("state", ""), pending.state):
            return "esa dirección no es la de la respuesta de Spotify (empieza con " + config.spotify.redirect_uri + ")"
        auth = SpotifyAuth(config.spotify.client_id, config.spotify.redirect_uri, config.spotify_token_path, self._http)
        try:
            await auth.exchange_code(query["code"], pending.verifier)
        except (AuthRequired, BackendUnavailable) as exc:
            return str(exc)
        await self._spotify_close()
        return None

    async def _spotify_callback(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = (await asyncio.wait_for(reader.readline(), 10)).decode("latin-1")
            target = line.split(" ")[1] if line.count(" ") >= 2 else "/"
            error = await self._spotify_exchange(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(target).query)))
            message = "Listo: VOXA ya puede usar Spotify. Puedes cerrar esta pestaña." if error is None else error
            body = f"<!doctype html><meta charset='utf-8'><h2>{message}</h2>".encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n"
                         + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            await writer.drain()
            if error is None:
                await self._restart()
        except (asyncio.TimeoutError, ConnectionError, IndexError):
            pass
        finally:
            writer.close()

    async def _spotify_close(self) -> None:
        pending, self._spotify = self._spotify, None
        if pending is not None and pending.server is not None:
            pending.server.close()

    async def _open_spotifast(self) -> tuple[int, Any]:
        """Abre Spotifast en la pantalla de la cocina (una vez, para «Sign in with Spotify»)."""
        command = list(self.config.spotifast.command)
        try:
            await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.DEVNULL,
                                                 stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        except (FileNotFoundError, OSError):
            return 400, {"error": "Spotifast no está instalado en esta PC (voxa revisar dice cómo)."}
        return 200, {"respuesta": "Listo: Spotifast se abrió en la pantalla de la cocina."}

    # --- Telegram, voz, IA ---------------------------------------------------------------
    async def _telegram_code(self) -> tuple[int, Any]:
        from voxa.telegram import Chats, TelegramApi, TelegramError, read_token

        config = self.config
        token = read_token(config.telegram_token_path)
        if token is None:
            return 400, {"error": "primero pega el token del bot"}
        if not config.telegram.enabled:
            return 400, {"error": "enciende Telegram y espera a que VOXA se reinicie"}
        try:
            me = await TelegramApi(token, self._http).call("getMe")
        except TelegramError as exc:
            return 502, {"error": str(exc)}
        code = Chats(config.telegram_chats_path, config.telegram_code_path).new_code()
        return 200, {"codigo": code, "bot": me.get("username")}

    def _telegram_forget(self, chat: Any) -> tuple[int, Any]:
        from voxa.telegram import Chats

        if not isinstance(chat, int):
            return 400, {"error": "falta el chat"}
        removed = Chats(self.config.telegram_chats_path, self.config.telegram_code_path).remove(chat)
        return (200, {"respuesta": "Ese chat ya no puede usar el bot."}) if removed else (404, {"error": "no existe"})

    def _enroll(self, name: str) -> tuple[int, Any]:
        service = self._service
        if not self._enroll_ready():
            return 400, {"error": "VOXA necesita el micrófono de la cocina y «Hey Voxa» encendido"}
        if service.enrolling:
            return 409, {"error": f"ya está grabando a {service.enrolling}"}
        service.start_enrollment(name)
        return 200, {"respuesta": "Ve a la cocina: VOXA te va a guiar en voz alta."}

    async def _try_ai(self) -> tuple[int, Any]:
        ai = self._service.app.ai
        if ai is None:
            return 400, {"error": self._service.app.ai_problem or "la IA está apagada"}
        started = time.perf_counter()
        response = await ai(AI_TEST_QUESTION)
        return 200, {
            "pregunta": AI_TEST_QUESTION, "respuesta": response.speech or "",
            "segundos": round(time.perf_counter() - started, 1), "uso": ai.usage.summary(),
        }

    async def _join(self, link: str, room: str) -> tuple[int, Any]:
        from voxa.house import HouseError, join

        try:
            main_room = await join(link, room, self.config, self._config_file, self._http)
        except HouseError as exc:
            return 400, {"error": str(exc)}
        return 200, await self._saved({"principal": main_room})

    def invitation(self) -> str | None:
        """El comando para unir otra PC a la casa (con la clave de esta, que es la principal)."""
        web, house = self._service.web, self._service.app.house
        if web is None or house is None or not house.is_main:
            return None
        from voxa import diagnostics

        return web.url(diagnostics.local_ip() or "127.0.0.1")

    async def close(self) -> None:
        await self._spotify_close()
