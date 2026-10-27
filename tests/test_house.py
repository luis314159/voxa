from dataclasses import replace

import pytest

from voxa.app import build_app
from voxa.config import Config, WebConfig, read_config
from voxa.house import House, HouseError, parse_invitation, place_name, same_room
from voxa.service import Service
from voxa.services.http import UrllibHttp
from voxa.web import WebServer

MAIN_KEY = "clave-principal-1234567890"
ROOM_KEY = "clave-de-la-sala-123456789"


def test_room_names():
    assert same_room("la Sala", "sala") and not same_room("Sala", "Comedor")
    assert place_name("Sala") == "la sala" and place_name("Comedor") == "el comedor"
    assert place_name("la recámara") == "la recámara" and place_name("Cuarto de Ana") == "el cuarto de Ana"
    assert parse_invitation("http://192.168.1.10:8770/?k=" + MAIN_KEY) == ("http://192.168.1.10:8770", MAIN_KEY)
    with pytest.raises(HouseError):
        parse_invitation("https://otra.cosa/?k=corta")


async def start(config, key):
    service = Service.create(build_app(config, simulated=True))
    said = []

    async def speak(text):
        said.append(text)

    service.say_announcement = speak  # sin bocina en las pruebas
    service.app.house.speak = speak
    server = WebServer(service, key, config.config_dir / "fondos", host="127.0.0.1", port=0)
    await server.start()
    service.web = server
    return service, server, said


@pytest.fixture
async def house(tmp_path):
    main_config = Config(config_dir=tmp_path / "cocina", state_dir=tmp_path / "cocina-estado", web=WebConfig(port=0))
    main, main_server, main_said = await start(main_config, MAIN_KEY)

    room_dir = tmp_path / "sala"
    room_config = Config(config_dir=room_dir, state_dir=tmp_path / "sala-estado", web=WebConfig(port=0))
    link = f"http://127.0.0.1:{main_server.port}/?k={MAIN_KEY}"
    from voxa.house import join

    assert await join(link, "Sala", room_config, room_dir / "config.toml", UrllibHttp()) == "Cocina"
    joined = replace(read_config(room_dir / "config.toml")[0], config_dir=room_dir, state_dir=tmp_path / "sala-estado",
                     web=WebConfig(port=0))
    assert joined.house.main == f"http://127.0.0.1:{main_server.port}" and joined.spotify.device_name == "VOXA Sala"
    room, room_server, room_said = await start(joined, ROOM_KEY)
    await room.app.house.check_in(room_server.port, ROOM_KEY)
    yield main, room, main_said, room_said
    await main_server.close()
    await room_server.close()


async def test_a_room_joins_and_shows_up(house):
    main, room, *_ = house
    assert not room.app.house.is_main
    status = main.app.house.status()
    assert [c["nombre"] for c in status["cuartos"]] == ["Sala"] and status["cuartos"][0]["en_linea"]
    assert (main.app.config.state_dir / "cuartos.json").exists()


async def test_announcements_reach_the_other_rooms(house):
    main, room, main_said, room_said = house
    response = await room.handle_text("avisa a todos que ya está la comida", speak=False)
    assert main_said == ["Aviso de la sala: Ya está la comida."]
    assert response.speech == "Listo, avisé en la cocina."

    response = await main.handle_text("dile a la sala que se bajen a cenar", speak=False)
    assert room_said == ["Aviso de la cocina: Se bajen a cenar."]
    assert response.speech == "Listo, avisé en la sala."

    await main.handle_text("llama a todos a comer", speak=False)
    assert room_said[-1] == "Aviso de la cocina: ¡A comer!"

    response = await main.handle_text("dile al comedor que ya voy", speak=False)
    assert response.sound == "error" and "el comedor" in response.speech


async def test_rooms_share_the_kitchen_shopping_list(house):
    main, room, *_ = house
    response = await room.handle_text("agrega leche y huevos a la lista", speak=False)
    assert main.app.shopping.items == ["leche", "huevos"]
    assert response.speech == "Agregué leche y huevos a la lista."
    assert room.app.shopping.items == []  # la de la sala no se usa


async def test_a_room_without_the_main_says_so(house, tmp_path):
    _, room, *_ = house
    room.app.house.main_url = "http://127.0.0.1:9"  # nadie escucha ahí
    response = await room.handle_text("qué hay en la lista", speak=False)
    assert response.sound == "error" and "cocina" in response.speech


async def test_strangers_cannot_register_or_announce(house):
    from test_web import http

    main, *_ = house
    status, _, _ = await http(main.web.port, "POST", "/api/casa/aviso", body=b'{"texto": "hola"}',
                              headers={"Content-Type": "application/json"})
    assert status == 403


def test_bad_registrations_are_refused(tmp_path):
    house = House("Cocina", UrllibHttp(), tmp_path / "cuartos.json")
    for name, port, key in (("Cocina", 8770, ROOM_KEY), ("", 8770, ROOM_KEY), ("Sala", 0, ROOM_KEY), ("Sala", 8770, "corta")):
        with pytest.raises(HouseError):
            house.register(name, "192.168.1.20", port, key)
