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
    assert said.speech.startswith("Escanea el código con la cámara del celular.")
    url = service.display.snapshot()["phone"]
    assert url.startswith("http://") and url.endswith(f":{server.port}/?k={KEY}")
    await service.handle_text("cierra el código")
    assert service.display.snapshot()["phone"] is None


async def test_a_new_kitchen_shows_the_setup_code(tmp_path):
    from voxa.config import WebConfig

    config = Config(config_dir=tmp_path, state_dir=tmp_path, web=WebConfig(port=0))
    service = Service.create(build_app(config, simulated=True))
    assert service.needs_setup()
    async with service.running(None):
        assert service.display.snapshot()["phone"].startswith("http://")


async def test_phone_shows_todays_medicine_and_marks_it_taken(phone):
    server, service, _ = phone
    timers = service.app.timers
    timer = timers.add(60, "tomar la pastilla", kind="reminder")
    timer.person = "Ana"
    service.app.medicine.unanswered(timer)  # nadie contestó
    state = json.loads((await http(server.port, "GET", "/api/estado", headers=logged_in()))[2])
    assert state["medicinas"][0]["medicina"] == "la pastilla" and state["medicinas"][0]["sin_confirmar"]
    status, _, body = await http(server.port, "POST", "/api/medicinas", **as_json({"tomada": 0}))
    assert status == 200 and json.loads(body)["medicinas"][0]["tomada"]
    status, _, _ = await http(server.port, "POST", "/api/medicinas", **as_json({"tomada": 0}))
    assert status == 400  # ya estaba anotada


async def test_phone_leaves_and_deletes_notes(phone):
    server, service, _ = phone
    status, _, body = await http(server.port, "POST", "/api/notas", **as_json({"texto": "compra pan", "para": "ana"}))
    assert status == 200 and json.loads(body)["notas"] == [{"id": 1, "text": "compra pan", "to": "Ana", "from": None}]
    assert service.display.snapshot()["notes"][0]["to"] == "Ana"
    status, _, body = await http(server.port, "POST", "/api/notas", **as_json({"borrar": 1}))
    assert json.loads(body)["notas"] == []


async def test_phone_shows_how_voxa_is_doing(phone):
    server, service, _ = phone
    await http(server.port, "POST", "/api/orden", **as_json({"texto": "blablá blablá"}))
    status, _, body = await http(server.port, "GET", "/api/como-va", headers=logged_in())
    summary = json.loads(body)
    assert status == 200 and summary["no_entendidas"] == 1 and "blablá" in summary["reporte"]
    status, _, body = await http(server.port, "POST", "/api/como-va", **as_json({"borrar": True}))
    assert json.loads(body)["ordenes"] == 0


def connect_screen_skill(service, server):
    """Lo que hace el servicio al arrancar con la página del celular encendida."""
    service.web = server
    screen = service.app.assistant.skill("display")
    screen.phone_ready = lambda: True
    screen.without_screen = service.pairing_phrase


async def test_without_a_screen_a_spoken_code_lets_the_phone_in(phone):
    """Una VOXA sin pantalla (una Raspberry Pi en la sala): «conecta mi celular» dice un código de 6 dígitos."""
    server, service, _ = phone
    connect_screen_skill(service, server)
    said = await service.handle_text("conecta mi celular")
    assert "punto local, dos puntos" in said.speech and "escribe el código" in said.speech
    code = "".join(c for c in said.speech.rsplit(":", 1)[1] if c.isdigit())
    assert len(code) == 6
    wrong = await http(server.port, "POST", "/api/emparejar", body=b'{"codigo": "000000"}',
                       headers={"Content-Type": "application/json"})
    assert wrong[0] == 403
    status, headers, _ = await http(server.port, "POST", "/api/emparejar", body=json.dumps({"codigo": code}).encode(),
                                    headers={"Content-Type": "application/json"})
    assert status == 200 and f"voxa_clave={KEY}" in headers["Set-Cookie"]
    again = await http(server.port, "POST", "/api/emparejar", body=json.dumps({"codigo": code}).encode(),
                       headers={"Content-Type": "application/json"})
    assert again[0] == 403  # un solo uso


async def test_the_pairing_code_allows_few_tries(phone):
    server, *_ = phone
    code = server.new_pairing_code()
    for _ in range(5):
        await http(server.port, "POST", "/api/emparejar", body=b'{"codigo": "111111"}',
                   headers={"Content-Type": "application/json"})
    status, _, _ = await http(server.port, "POST", "/api/emparejar", body=json.dumps({"codigo": code}).encode(),
                              headers={"Content-Type": "application/json"})
    assert status == 403  # tras 5 intentos fallidos, ese código ya no sirve


async def test_with_a_screen_it_shows_the_qr(phone):
    server, service, _ = phone
    connect_screen_skill(service, server)
    service.display.subscribe()  # la pantalla de la cocina está conectada
    said = await service.handle_text("conecta mi celular")
    assert said.speech.startswith("Escanea el código")


async def test_the_settings_page_shows_the_qr_for_another_phone(phone):
    server, service, _ = phone
    service.web = server
    status, headers, body = await http(server.port, "GET", "/api/qr.svg", headers=logged_in())
    assert status in (200, 404)  # 404: esta PC no tiene qrencode
    if status == 200:
        assert headers["Content-Type"] == "image/svg+xml" and body.lstrip().startswith(b"<")
    status, _, _ = await http(server.port, "GET", "/api/qr.svg")
    assert status == 403  # sin la clave, nada

    status, _, body = await http(server.port, "POST", "/api/mostrar-qr", **as_json({}))
    assert status == 200 and service.display.snapshot()["phone"].endswith(f"/?k={KEY}")


async def test_the_qr_comes_from_qrencode(phone, monkeypatch):
    import asyncio

    server, _, _ = phone
    calls = []

    class Done:
        returncode = 0

        async def communicate(self):
            return b'<?xml version="1.0"?><svg/>', b""

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return Done()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    status, headers, body = await http(server.port, "GET", "/api/qr.svg", headers=logged_in())
    assert status == 200 and body.startswith(b"<?xml")
    assert calls[0][:6] == ("qrencode", "-t", "SVG", "-m", "2", "-o") and calls[0][7].endswith(f"/?k={KEY}")
