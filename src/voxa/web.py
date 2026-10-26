"""VOXA desde el celular (misma red de la casa): temporizadores, lista del súper, música, órdenes y fotos.

Apagado por defecto (``[web] enabled``). Para entrar hace falta la clave de esta PC: va en el código
QR que muestra la pantalla («conecta mi celular»); al abrirlo, el celular la guarda en una cookie.
Sin la clave, nadie más en la red puede usarlo. Las órdenes del celular no se dicen en voz alta en
la cocina (salvo que se pida).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from voxa.service import Service

log = logging.getLogger(__name__)

COOKIE = "voxa_clave"
MAX_BODY = 1 << 14
MAX_PHOTO = 15 << 20
_PHOTO_TYPES = {b"\xff\xd8\xff": "jpg", b"\x89PNG\r\n\x1a\n": "png", b"RIFF": "webp"}
_STATUS = {200: "OK", 303: "See Other", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 413: "Payload Too Large"}

FORBIDDEN_PAGE = """<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>VOXA</title>
<body style="font-family:sans-serif;background:#0b1020;color:#f8faff;padding:2em;line-height:1.5">
<h1>VOXA</h1><p>Para usar VOXA desde este celular, escanea el código de la pantalla de la cocina
(dile «conecta mi celular»).</p></body></html>"""


def load_or_create_key(path: Path) -> str:
    """La clave de acceso de esta PC: se crea una vez y se guarda solo legible por el usuario (600)."""
    try:
        key = path.read_text(encoding="utf-8").strip()
        if len(key) >= 16:
            return key
    except OSError:
        pass
    key = secrets.token_urlsafe(18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key + "\n")
    return key


def photo_kind(data: bytes) -> str | None:
    for magic, ext in _PHOTO_TYPES.items():
        if data.startswith(magic) and (ext != "webp" or data[8:12] == b"WEBP"):
            return ext
    return None


class WebServer:
    def __init__(self, service: Service, key: str, photos_dir: Path, *, host: str = "0.0.0.0", port: int = 8770) -> None:
        self._service = service
        self._key = key
        self._photos = photos_dir
        self._host = host
        self._port = port
        self._server: asyncio.base_events.Server | None = None
        self.page = resources.files("voxa").joinpath("telefono.html").read_text(encoding="utf-8")

    @property
    def port(self) -> int:
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    def url(self, ip: str) -> str:
        return f"http://{ip}:{self.port}/?k={self._key}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._client, self._host, self._port)
        log.info("VOXA para el celular en el puerto %d", self.port)

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # --- HTTP mínimo -------------------------------------------------------------------
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            status, headers, payload = await self._handle(reader)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError, UnicodeDecodeError):
            status, headers, payload = 400, {"Content-Type": "text/plain; charset=utf-8"}, b"Peticion invalida"
        head = [f"HTTP/1.1 {status} {_STATUS.get(status, 'OK')}", f"Content-Length: {len(payload)}", "Connection: close",
                "Cache-Control: no-store", "X-Content-Type-Options: nosniff", "Referrer-Policy: no-referrer"]
        head += [f"{name}: {value}" for name, value in headers.items()]
        try:
            writer.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + payload)
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    async def _handle(self, reader: asyncio.StreamReader) -> tuple[int, dict[str, str], bytes]:
        line = (await asyncio.wait_for(reader.readline(), 10)).decode("latin-1").strip()
        method, target, _ = line.split(" ", 2)
        headers: dict[str, str] = {}
        while (raw := await asyncio.wait_for(reader.readline(), 10)) not in (b"\r\n", b"\n", b""):
            if len(headers) > 60:
                raise ValueError("demasiados encabezados")
            name, _, value = raw.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()
        url = urllib.parse.urlsplit(target)
        query = urllib.parse.parse_qs(url.query)
        length = int(headers.get("content-length") or 0)
        limit = MAX_PHOTO if url.path == "/api/foto" else MAX_BODY
        if length < 0 or length > limit:
            return self._json(413, {"error": "demasiado grande"})

        given = query.get("k", [""])[0]
        if url.path == "/" and given and hmac.compare_digest(given, self._key):
            # Primera visita desde el código QR: el celular guarda la clave y la URL queda limpia.
            cookie = f"{COOKIE}={self._key}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict"
            return 303, {"Location": "/", "Set-Cookie": cookie}, b""
        if not self._authorized(headers):
            if url.path.startswith("/api/"):
                return self._json(403, {"error": "falta la clave: escanea el código de la pantalla"})
            return 403, {"Content-Type": "text/html; charset=utf-8"}, FORBIDDEN_PAGE.encode()

        body = await asyncio.wait_for(reader.readexactly(length), 60) if length else b""
        if method == "GET" and url.path == "/":
            return 200, {"Content-Type": "text/html; charset=utf-8"}, self.page.encode()
        if method == "GET" and url.path == "/api/estado":
            return self._json(200, self._state())
        if method == "POST" and url.path == "/api/foto":
            return self._json(*self._save_photo(body))
        if method == "POST" and url.path.startswith("/api/"):
            if not headers.get("content-type", "").startswith("application/json"):
                return self._json(400, {"error": "se esperaba JSON"})  # y así un formulario ajeno no puede mandar órdenes
            data = json.loads(body or b"{}")
            if not isinstance(data, dict):
                return self._json(400, {"error": "se esperaba un objeto"})
            return self._json(*await self._post(url.path, data))
        return self._json(404, {"error": "no existe"})

    def _authorized(self, headers: dict[str, str]) -> bool:
        cookies = dict(
            part.strip().split("=", 1) for part in headers.get("cookie", "").split(";") if "=" in part
        )
        return hmac.compare_digest(cookies.get(COOKIE, ""), self._key)

    @staticmethod
    def _json(status: int, data: Any) -> tuple[int, dict[str, str], bytes]:
        return status, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(data, ensure_ascii=False).encode()

    # --- lo que hace -----------------------------------------------------------------------
    def _state(self) -> dict:
        snapshot = self._service.display.snapshot()
        keys = ("phase", "heard", "answer", "timers", "music", "shopping", "recipe", "muted", "weather")
        return {"now": time.time(), **{k: snapshot.get(k) for k in keys}}

    async def _post(self, path: str, data: dict) -> tuple[int, Any]:
        service, app = self._service, self._service.app
        text = str(data.get("texto") or "").strip()[:200]
        match path:
            case "/api/orden":
                if not text:
                    return 400, {"error": "falta el texto"}
                response = await service.handle_text(text, speak=bool(data.get("en_voz")))
                return 200, {"respuesta": response.speech or "Listo."}
            case "/api/musica":
                action = {"pausa": "pausa", "sigue": "sigue", "siguiente": "siguiente", "anterior": "anterior"}
                if data.get("accion") not in action:
                    return 400, {"error": "acción desconocida"}
                response = await service.handle_text(action[data["accion"]], speak=False)
                return 200, {"respuesta": response.speech or "Listo."}
            case "/api/temporizador":
                minutes = data.get("minutos")
                if not isinstance(minutes, (int, float)) or not 0 < minutes <= 24 * 60:
                    return 400, {"error": "minutos inválidos"}
                app.timers.add(round(minutes * 60), text or None)
                service.display.publish()
                return 200, {"respuesta": "Listo."}
            case "/api/temporizador/cancelar":
                if not isinstance(data.get("id"), int):
                    return 400, {"error": "falta el id"}
                await service.cancel_timer(data["id"])
                return 200, {"respuesta": "Cancelado."}
            case "/api/lista":
                if add := str(data.get("agregar") or "").strip()[:80]:
                    app.shopping.add([add])
                elif remove := str(data.get("quitar") or "").strip()[:80]:
                    app.shopping.remove(remove)
                else:
                    return 400, {"error": "¿qué agrego o quito?"}
                service.display.publish()
                return 200, {"lista": list(app.shopping.items)}
        return 404, {"error": "no existe"}

    def _save_photo(self, data: bytes) -> tuple[int, Any]:
        ext = photo_kind(data)
        if ext is None:
            return 400, {"error": "solo fotos JPG, PNG o WebP"}
        self._photos.mkdir(parents=True, exist_ok=True)
        path = self._photos / f"celular-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}.{ext}"
        path.write_bytes(data)
        log.info("Foto nueva para el fondo: %s", path.name)
        return 200, {"respuesta": "Foto guardada: aparecerá en la rotación de fondos."}
