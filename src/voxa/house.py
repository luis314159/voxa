"""VOXA en varios cuartos: una principal (la cocina) y las de la sala, el comedor, las recámaras…

Cada cuarto es una VOXA completa (su micrófono, su bocina, su «Hey Voxa», sus temporizadores y su
música como dispositivo de Spotify «VOXA Sala»). Lo de toda la familia vive en la principal: la
lista del súper y el calendario; cuando se le piden a un cuarto, los pregunta a la principal.

Los cuartos se anuncian solos con la principal cada minuto (con su propia clave, para que la
principal les pueda hablar) y así funcionan los avisos: «avisa a todos que ya está la comida»,
«dile a la sala que se bajen a cenar». Todo va por la red de la casa con la clave de cada VOXA.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from voxa.nlu.normalize import normalize
from voxa.services.http import Http, HttpError
from voxa.settings import read_secret, write_private

log = logging.getLogger(__name__)

COOKIE = "voxa_clave"
HEARTBEAT_SECONDS = 60
ONLINE_SECONDS = 3 * 60
# Lo que un cuarto le pregunta a la principal: lo que es de toda la casa.
SHARED_DOMAINS = ("shopping", "calendar")


class HouseError(Exception):
    pass


@dataclass(frozen=True)
class Room:
    name: str
    url: str
    key: str
    seen: float

    def online(self, now: float) -> bool:
        return now - self.seen < ONLINE_SECONDS


def same_room(a: str, b: str) -> bool:
    """«la sala», «Sala» y «sala» son el mismo cuarto."""
    def clean(text: str) -> str:
        words = normalize(text).split()
        return " ".join(w for w in words if w not in ("el", "la", "los", "las", "voxa", "de"))

    return clean(a) == clean(b)


def parse_invitation(link: str) -> tuple[str, str]:
    """«http://192.168.1.10:8770/?k=CLAVE» → (dirección de la principal, clave)."""
    parts = urllib.parse.urlsplit(link.strip())
    key = urllib.parse.parse_qs(parts.query).get("k", [""])[0]
    if parts.scheme != "http" or not parts.hostname or len(key) < 16:
        raise HouseError("esa no es la dirección de la VOXA principal (http://…/?k=…)")
    return f"http://{parts.netloc}", key


class House:
    def __init__(
        self,
        room: str,
        http: Http,
        rooms_path: Path,
        *,
        main_url: str = "",
        main_key_path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.room = room or "Cocina"
        self.main_url = main_url.rstrip("/")
        self._main_key_path = main_key_path
        self._http = http
        self._rooms_path = rooms_path
        self._clock = clock
        self.speak: Callable[[str], Awaitable[None]] | None = None
        """Lo pone el servicio: decir un aviso en este cuarto."""
        self.main_online: bool | None = None
        self._rooms: dict[str, Room] = self._load() if self.is_main else {}

    @property
    def is_main(self) -> bool:
        return not self.main_url

    # --- la principal ---------------------------------------------------------------------
    def register(self, name: str, ip: str, port: int, key: str) -> None:
        name = name.strip()[:40]
        if not name or same_room(name, self.room) or not 0 < port < 65536 or len(key) < 16:
            raise HouseError("cuarto inválido")
        room = Room(name, f"http://{ip}:{port}", key, self._clock())
        known = self._rooms.get(name)
        self._rooms[name] = room
        if known is None or (known.url, known.key) != (room.url, room.key):
            log.info("Cuarto conectado: %s (%s)", name, room.url)
            self._save()

    def rooms(self) -> list[Room]:
        return sorted(self._rooms.values(), key=lambda r: r.name)

    def status(self) -> dict:
        now = self._clock()
        return {
            "cuarto": self.room,
            "principal": self.is_main,
            "en_linea": self.main_online,
            "cuartos": [{"nombre": r.name, "en_linea": r.online(now)} for r in self.rooms()],
        }

    def forget(self, name: str) -> bool:
        if self._rooms.pop(name, None) is None:
            return False
        self._save()
        return True

    async def announce(self, text: str, from_room: str | None = None, target: str | None = None) -> list[str]:
        """Dice el aviso en los cuartos (todos, o solo ``target``); devuelve dónde se oyó."""
        text = text.strip()[:300]
        if not text:
            raise HouseError("aviso vacío")
        if not self.is_main:
            data = await self._call_main("/api/casa/aviso", {"texto": text, "desde": self.room, "a": target or ""})
            return list(data.get("llego_a", []))
        source = from_room or self.room
        heard: list[str] = []
        if not same_room(source, self.room) and (not target or same_room(target, self.room)):
            if self.speak is not None:
                await self.speak(_spoken(text, source))
                heard.append(self.room)
        now = self._clock()
        rooms = [r for r in self.rooms() if r.online(now) and not same_room(r.name, source)
                 and (not target or same_room(target, r.name))]
        results = await asyncio.gather(*(self._tell(r, _spoken(text, source)) for r in rooms))
        heard += [r.name for r, ok in zip(rooms, results) if ok]
        return heard

    async def _tell(self, room: Room, text: str) -> bool:
        try:
            response = await self._http.request("POST", f"{room.url}/api/casa/decir", json_body={"texto": text},
                                                headers={"Cookie": f"{COOKIE}={room.key}"}, timeout=6)
        except HttpError as exc:
            log.info("No pude avisar en %s: %s", room.name, exc)
            return False
        return response.status == 200

    # --- un cuarto --------------------------------------------------------------------------
    async def ask_main(self, text: str) -> str:
        """Una orden de lo que es de toda la casa (la lista, el calendario): la contesta la principal."""
        data = await self._call_main("/api/orden", {"texto": text, "en_voz": False})
        return str(data.get("respuesta") or "Listo.")

    async def check_in(self, port: int, own_key: str) -> None:
        await self._call_main("/api/casa/registrar", {"nombre": self.room, "puerto": port, "clave": own_key})

    async def run(self, port: int, own_key: str) -> None:
        """Cada minuto le dice a la principal «aquí estoy» (y en qué puerto y con qué clave hablarle)."""
        while True:
            try:
                await self.check_in(port, own_key)
                if self.main_online is not True:
                    log.info("Conectada a la VOXA principal (%s)", self.main_url)
                self.main_online = True
            except HouseError as exc:
                if self.main_online is not False:
                    log.warning("Sin la VOXA principal: %s", exc)
                self.main_online = False
            await asyncio.sleep(HEARTBEAT_SECONDS)

    async def _call_main(self, path: str, body: dict) -> dict:
        key = read_secret(self._main_key_path) if self._main_key_path else None
        if self.is_main or not key:
            raise HouseError("este cuarto no está unido a la casa")
        try:
            response = await self._http.request("POST", f"{self.main_url}{path}", json_body=body,
                                                headers={"Cookie": f"{COOKIE}={key}"}, timeout=8)
        except HttpError as exc:
            raise HouseError(f"no contesta la VOXA principal ({exc})") from None
        if response.status != 200 or not isinstance(response.data, dict):
            detail = response.data.get("error") if isinstance(response.data, dict) else response.status
            raise HouseError(f"la VOXA principal respondió: {detail}")
        return response.data

    # --- persistencia (solo la principal) -------------------------------------------------
    def _load(self) -> dict[str, Room]:
        try:
            data = json.loads(self._rooms_path.read_text(encoding="utf-8"))
            return {r["name"]: Room(r["name"], r["url"], r["key"], 0.0) for r in data}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _save(self) -> None:
        rooms = [{"name": r.name, "url": r.url, "key": r.key} for r in self.rooms()]
        try:
            write_private(self._rooms_path, json.dumps(rooms, ensure_ascii=False))
        except OSError as exc:
            log.warning("No pude guardar los cuartos: %s", exc)


async def join(link: str, room: str, config, config_file: Path, http: Http) -> str:
    """Une esta VOXA a la casa como ``room``: prueba la dirección, guarda la clave (600) y los ajustes.

    Devuelve el nombre del cuarto de la principal.
    """
    from voxa.settings import save_secret, save_settings, settings_path

    room = room.strip()[:40]
    if not room:
        raise HouseError("falta el nombre de este cuarto (Sala, Comedor, Recámara…)")
    main_url, key = parse_invitation(link)
    try:
        response = await http.request("GET", f"{main_url}/api/casa", headers={"Cookie": f"{COOKIE}={key}"}, timeout=8)
    except HttpError as exc:
        raise HouseError(f"no contesta la VOXA principal en {main_url} ({exc})") from None
    if response.status != 200 or not isinstance(response.data, dict):
        raise HouseError("la VOXA principal no aceptó la clave")
    if not response.data.get("principal"):
        raise HouseError("esa VOXA es un cuarto, no la principal")
    if same_room(room, str(response.data.get("cuarto", ""))):
        raise HouseError("ese nombre ya lo usa la principal: elige otro")
    save_secret(config.house_key_path, key)
    overlay = settings_path(config_file)
    save_settings(overlay, "house", {"room": room, "main": main_url})
    if config.spotify.device_name == "VOXA Cocina":
        save_settings(overlay, "spotify", {"device_name": f"VOXA {room}"})
    return str(response.data.get("cuarto", ""))


def place_name(room: str) -> str:
    """«Sala» → «la sala», «Comedor» → «el comedor», «Cuarto de Ana» → «el cuarto de Ana»."""
    words = room.split()
    if len(words) > 1 and normalize(words[0]) in ("el", "la"):
        room = " ".join(words[1:])
    first = (normalize(room).split() or [""])[0]
    article = "la" if first.endswith(("a", "ion")) else "el"
    return f"{article} {room[:1].lower()}{room[1:]}"


def _spoken(text: str, source: str) -> str:
    place = place_name(source)
    return f"Aviso {'del ' + place[3:] if place.startswith('el ') else 'de ' + place}: {text}"
