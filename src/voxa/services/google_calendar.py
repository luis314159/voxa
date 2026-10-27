"""Agregar citas al calendario de Google («agrega dentista el martes a las 5»).

Leer el calendario sigue siendo con su dirección iCal (sin cuenta); para escribir hace falta conectar
la cuenta de Google con OAuth. Google no deja usar el calendario con el flujo de «código en la tele», así
que se hace como con Spotify: el celular abre la autorización y se pega la dirección de regreso.

La familia crea su propio cliente OAuth (tipo «App de escritorio») en Google Cloud, con la API de
Google Calendar activada y la pantalla de consentimiento «En producción» (en «Prueba», Google corta el
permiso a los 7 días). El permiso es solo ``calendar.events``: crear y ver eventos, nada más de la cuenta.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from voxa.services.http import Http, HttpError
from voxa.services.spotify_auth import challenge_for

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar}/events"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
REDIRECT = "http://127.0.0.1:8767/"


class GoogleError(Exception):
    """No se pudo hablar con Google (sin red, permiso vencido, calendario que no existe)."""


class GoogleNotConnected(GoogleError):
    pass


@dataclass(frozen=True)
class GoogleClient:
    client_id: str
    client_secret: str

    @classmethod
    def load(cls, path: Path) -> GoogleClient | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not data.get("client_id") or not data.get("client_secret"):
            return None
        return cls(str(data["client_id"]), str(data["client_secret"]))

    def save(self, path: Path) -> None:
        _write_private(path, json.dumps({"client_id": self.client_id, "client_secret": self.client_secret}))


class GoogleAuth:
    def __init__(self, client: GoogleClient, token_path: Path, http: Http, *, clock: Callable[[], float] = time.time) -> None:
        self.client = client
        self._token_path = token_path
        self._http = http
        self._clock = clock

    def authorization_url(self, verifier: str, state: str) -> str:
        params = {
            "client_id": self.client.client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": SCOPE,
            "code_challenge": challenge_for(verifier),
            "code_challenge_method": "S256",
            "access_type": "offline",  # para que dure: con refresh token
            "prompt": "consent",
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str, verifier: str) -> None:
        await self._token({"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                           "redirect_uri": REDIRECT})

    async def access_token(self) -> str:
        token = self._load()
        if token is None:
            raise GoogleNotConnected("falta conectar Google Calendar")
        if token["expires_at"] - 60 <= self._clock():
            token = await self._token({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]},
                                      keep_refresh=token["refresh_token"])
        return token["access_token"]

    async def _token(self, form: dict[str, str], keep_refresh: str | None = None) -> dict:
        form = {**form, "client_id": self.client.client_id, "client_secret": self.client.client_secret}
        try:
            resp = await self._http.request("POST", TOKEN_URL, form=form)
        except HttpError as exc:
            raise GoogleError(f"sin conexión con Google: {exc}") from exc
        if resp.status != 200 or not isinstance(resp.data, dict) or "access_token" not in resp.data:
            raise GoogleError(f"Google no dio el permiso ({resp.status}): {resp.data}")
        refresh = resp.data.get("refresh_token") or keep_refresh
        if not refresh:
            raise GoogleError("Google no mandó el permiso para seguir conectado: vuelve a conectar")
        token = {"access_token": resp.data["access_token"], "refresh_token": refresh,
                 "expires_at": self._clock() + int(resp.data.get("expires_in", 3600))}
        _write_private(self._token_path, json.dumps(token))
        return token

    def _load(self) -> dict | None:
        try:
            return json.loads(self._token_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


class GoogleCalendarWriter:
    def __init__(self, auth: GoogleAuth, http: Http, calendar_id: str = "primary") -> None:
        self._auth = auth
        self._http = http
        self.calendar_id = calendar_id or "primary"

    async def add(self, title: str, start: datetime | date, *, minutes: int = 60) -> str:
        """Crea el evento (con hora: de ``minutes``; sin hora: todo el día); devuelve su enlace."""
        if isinstance(start, datetime):
            begin = start.astimezone()  # con la zona de la PC
            body = {"summary": title, "start": {"dateTime": begin.isoformat()},
                    "end": {"dateTime": (begin + timedelta(minutes=minutes)).isoformat()}}
        else:
            body = {"summary": title, "start": {"date": start.isoformat()},
                    "end": {"date": (start + timedelta(days=1)).isoformat()}}
        url = EVENTS_URL.format(calendar=urllib.parse.quote(self.calendar_id, safe=""))
        headers = {"Authorization": f"Bearer {await self._auth.access_token()}"}
        try:
            resp = await self._http.request("POST", url, headers=headers, json_body=body)
        except HttpError as exc:
            raise GoogleError(f"sin conexión con Google: {exc}") from exc
        if resp.status in (401, 403):
            raise GoogleError(f"Google no dejó agregar la cita ({resp.status}): revisa la conexión en Ajustes")
        if resp.status == 404:
            raise GoogleError(f"no encontré el calendario «{self.calendar_id}»")
        if resp.status >= 400:
            raise GoogleError(f"Google respondió {resp.status}: {resp.data}")
        return str((resp.data or {}).get("htmlLink") or "")


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    tmp.replace(path)
