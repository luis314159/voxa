import json

from voxa.app import build_app
from voxa.config import Config
from voxa.display import DisplayServer
from voxa.service import Service


async def test_photo_mode_by_voice_and_from_the_screen():
    service = Service.create(build_app(Config(), simulated=True))
    assert service.display.snapshot()["photo"] is False
    response = await service.handle_text("modo foto")
    assert response.speech is None and response.sound == "ok"
    assert service.display.snapshot()["photo"] is True
    await service.handle_text("muestra la información")
    assert service.display.snapshot()["photo"] is False

    server = DisplayServer(service.display, service, port=0)
    server._dispatch(json.dumps({"type": "photo", "on": True}).encode())
    for task in list(server._tasks):
        await task
    assert service.display.snapshot()["photo"] is True
