import asyncio
import json
import os

import pytest

from voxa.app import build_app
from voxa.config import Config
from voxa.service import Service
from voxa.web import COOKIE, WebServer, load_or_create_key, photo_kind

KEY = "clave-de-prueba-123456"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


async def http(port, method, path, *, body=b"", headers=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    lines = [f"{method} {path} HTTP/1.1", "Host: voxa", f"Content-Length: {len(body)}"]
    lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    status = int(head.split()[1])
    response_headers = dict(line.split(": ", 1) for line in head.decode().split("\r\n")[1:])
    return status, response_headers, payload


def logged_in(extra=None):
    return {"Cookie": f"{COOKIE}={KEY}", **(extra or {})}


def as_json(data):
    return {"body": json.dumps(data).encode(), "headers": logged_in({"Content-Type": "application/json"})}


@pytest.fixture
async def phone(tmp_path):
    service = Service.create(build_app(Config(), simulated=True))
    server = WebServer(service, KEY, tmp_path / "fondos", host="127.0.0.1", port=0)
    await server.start()
    yield server, service, tmp_path / "fondos"
    await server.close()


async def test_without_the_key_nothing_works(phone):
    server, service, _ = phone
    status, _, page = await http(server.port, "GET", "/")
    assert status == 403 and "escanea el código" in page.decode()
    status, _, _ = await http(server.port, "POST", "/api/orden", body=b'{"texto": "pon salsa"}',
                              headers={"Content-Type": "application/json", "Cookie": f"{COOKIE}=otra"})
    assert status == 403
    status, _, _ = await http(server.port, "GET", "/?k=adivinando")
    assert status == 403


async def test_the_qr_link_logs_the_phone_in(phone):
    server, *_ = phone
    status, headers, _ = await http(server.port, "GET", f"/?k={KEY}")
    assert status == 303 and headers["Location"] == "/"
    assert headers["Set-Cookie"].startswith(f"{COOKIE}={KEY};") and "HttpOnly" in headers["Set-Cookie"]
    status, _, page = await http(server.port, "GET", "/", headers=logged_in())
    assert status == 200 and b"<title>VOXA</title>" in page


async def test_phone_controls_timers_list_and_commands(phone):
    server, service, _ = phone
    status, _, _ = await http(server.port, "POST", "/api/temporizador", **as_json({"minutos": 5, "texto": "arroz"}))
    assert status == 200
    status, _, body = await http(server.port, "GET", "/api/estado", headers=logged_in())
    state = json.loads(body)
    assert [t["label"] for t in state["timers"]] == ["arroz"]

    await http(server.port, "POST", "/api/lista", **as_json({"agregar": "tortillas"}))
    assert service.app.shopping.items == ["tortillas"]
    await http(server.port, "POST", "/api/lista", **as_json({"quitar": "tortillas"}))
    assert service.app.shopping.items == []

    status, _, body = await http(server.port, "POST", "/api/orden", **as_json({"texto": "pon salsa"}))
    assert status == 200 and json.loads(body)["respuesta"] == "La playlist Salsa."
    timer_id = service.app.timers.active[0].id
    await http(server.port, "POST", "/api/temporizador/cancelar", **as_json({"id": timer_id}))
    assert not service.app.timers.active


async def test_commands_need_json(phone):
    server, *_ = phone
    status, _, _ = await http(server.port, "POST", "/api/orden", body=b"texto=pon+salsa",
                              headers=logged_in({"Content-Type": "application/x-www-form-urlencoded"}))
    assert status == 400


async def test_photos_for_the_background(phone):
    server, _, photos = phone
    status, _, _ = await http(server.port, "POST", "/api/foto", body=JPEG, headers=logged_in())
    assert status == 200 and [p.suffix for p in photos.iterdir()] == [".jpg"]
    status, _, _ = await http(server.port, "POST", "/api/foto", body=b"#!/bin/sh\nrm -rf ~", headers=logged_in())
    assert status == 400 and len(list(photos.iterdir())) == 1
    assert photo_kind(b"RIFF1234WEBPxxxx") == "webp" and photo_kind(b"RIFF1234WAVExxxx") is None


def test_the_key_is_created_once_and_private(tmp_path):
    path = tmp_path / "web_clave"
    key = load_or_create_key(path)
    assert len(key) >= 16 and load_or_create_key(path) == key
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0


async def test_conecta_mi_celular_shows_the_code(phone):
    server, service, _ = phone
    service.web = server
    service.app.assistant.skill("display").phone_ready = lambda: True
    said = await service.handle_text("conecta mi celular")
    assert said.speech == "Escanea el código con la cámara del celular."
    url = service.display.snapshot()["phone"]
    assert url.startswith("http://") and url.endswith(f":{server.port}/?k={KEY}")
    await service.handle_text("cierra el código")
    assert service.display.snapshot()["phone"] is None
