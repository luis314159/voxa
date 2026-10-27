"""OAuth de Spotify con PKCE: sin client secret; el refresh token se guarda en local."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from pathlib import Path
from typing import Callable

from voxa.services.http import Http, HttpError
from voxa.services.music_backend import AuthRequired, BackendUnavailable

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    # Tus «Me gusta»: ponerlos («pon mis me gusta») y guardar canciones («me gusta esta canción»).
    "user-library-read",
    "user-library-modify",
)
LIBRARY_SCOPE = "user-library-read"


def new_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class SpotifyAuth:
    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        token_path: Path,
        http: Http,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self._token_path = token_path
        self._http = http
        self._clock = clock
        self._token: dict | None = None

    def authorization_url(self, verifier: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge_for(verifier),
            "scope": " ".join(SCOPES),
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str, verifier: str) -> None:
        await self._request_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": verifier,
            }
        )

    async def access_token(self) -> str:
        token = self._token or self._load()
        if token is None:
            raise AuthRequired("Spotify no está autorizado: conéctalo en Ajustes → Spotify (o voxa spotify-login)")
        if token["expires_at"] - 60 <= self._clock():
            token = await self.refresh()
        return token["access_token"]

    async def refresh(self) -> dict:
        token = self._token or self._load()
        if token is None or not token.get("refresh_token"):
            raise AuthRequired("no hay refresh token")
        return await self._request_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
                "client_id": self.client_id,
            },
            previous_refresh=token["refresh_token"],
        )

    async def _request_token(self, form: dict[str, str], previous_refresh: str | None = None) -> dict:
        if not self.client_id:
            raise AuthRequired("falta spotify.client_id en la configuración")
        try:
            resp = await self._http.request("POST", TOKEN_URL, form=form)
        except HttpError as exc:
            raise BackendUnavailable(f"sin conexión con Spotify: {exc}") from exc
        if resp.status != 200 or not isinstance(resp.data, dict):
            raise AuthRequired(f"Spotify rechazó la autorización ({resp.status}): {resp.data}")
        token = {
            "access_token": resp.data["access_token"],
            "refresh_token": resp.data.get("refresh_token") or previous_refresh,
            "expires_at": self._clock() + int(resp.data.get("expires_in", 3600)),
            # El refresh no siempre repite los permisos: se conservan los de la autorización.
            "scope": resp.data.get("scope") or (self._token or {}).get("scope", ""),
        }
        self._save(token)
        return token

    def granted(self, scope: str) -> bool | None:
        """Si la autorización guardada incluye ese permiso (``None``: no se sabe, token viejo)."""
        token = self._token or self._load()
        if token is None:
            return False
        if "scope" not in token:
            return None
        return scope in str(token["scope"]).split()

    def _load(self) -> dict | None:
        try:
            self._token = json.loads(self._token_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("No pude leer el token de Spotify: %s", exc)
            return None
        return self._token

    def _save(self, token: dict) -> None:
        self._token = token
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._token_path.with_suffix(".tmp")
        # Se crea con permisos 600 desde el inicio: nunca queda legible para otros.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(token, fh)
        tmp.replace(self._token_path)
