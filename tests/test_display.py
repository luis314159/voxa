import asyncio
import json

from voxa.app import build_app
from voxa.config import Config
from voxa.core.types import Response
from voxa.display import Display, DisplayServer
from voxa.service import Service
from voxa.services.music_backend import NowPlaying
from voxa.state.timers import TimerManager


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_display(music=None):
    clock = Clock()
    timers = TimerManager(clock=clock)

    async def now_playing():
        return music[0] if music else None

    return Display(timers, now_playing, clock=clock), timers, clock


def drain(queue):
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_snapshot_lists_ringing_timers_first():
    display, timers, clock = make_display()
    timers.add(600, "arroz")
    timers.add(60, "huevo")
    clock.now += 61
    timers.check()
    state = display.snapshot()
    assert [(t["label"], t["ringing"]) for t in state["timers"]] == [("huevo", True), ("arroz", False)]
    assert state["timers"][1]["ends_at"] == 1600 and state["timers"][1]["total"] == 600


def test_publishes_only_changes():
    display, timers, _ = make_display()
    queue = display.subscribe()
    assert len(drain(queue)) == 1  # la foto inicial
    display.publish()
    assert drain(queue) == []
    display.phase("listening")
    display.phase("listening")
    assert [s["phase"] for s in drain(queue)] == ["listening"]
    timers.add(300, "pasta")
    display.publish()
    assert drain(queue)[0]["timers"][0]["label"] == "pasta"


def test_exchange_shows_heard_and_answer():
    display, _, _ = make_display()
    display.exchange("cuánto falta", Response("Faltan 3 minutos."))
    state = display.snapshot()
    assert (state["heard"], state["answer"], state["exchange_at"]) == ("cuánto falta", "Faltan 3 minutos.", 1000.0)


async def test_song_position_is_resent_only_when_it_jumps():
    song = [NowPlaying("Persiana americana", "Soda Stereo", position=10.0, length=290.0)]
    display, _, clock = make_display(song)
    queue = display.subscribe()
    drain(queue)
    await display.refresh_music()
    display.publish()
    assert drain(queue)[0]["music"]["title"] == "Persiana americana"

    clock.now += 2  # avanzó lo esperado: la pantalla lo calcula sola
    song[0] = NowPlaying("Persiana americana", "Soda Stereo", position=12.0, length=290.0)
    await display.refresh_music()
    display.publish()
    assert drain(queue) == []

    clock.now += 2  # «adelanta 30 segundos»
    song[0] = NowPlaying("Persiana americana", "Soda Stereo", position=44.0, length=290.0)
    await display.refresh_music()
    display.publish()
    assert drain(queue)[0]["music"]["position"] == 44.0


class RecordingCommands:
    def __init__(self):
        self.calls = []

    async def talk(self):
        self.calls.append("talk")

    async def handle_text(self, text):
        self.calls.append(f"say:{text}")

    async def cancel_timer(self, timer_id):
        self.calls.append(f"cancel:{timer_id}")

    async def stop_alarm(self):
        self.calls.append("stop")


async def test_server_sends_state_and_receives_commands():
    display, _, _ = make_display()
    commands = RecordingCommands()
    server = DisplayServer(display, commands, port=0)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        first = json.loads(await reader.readline())
        assert first["type"] == "state" and first["phase"] == "idle"

        writer.write(
            b'{"type": "say", "text": "  pausa  "}\nno es json\n[1, 2]\n{"type": "talk"}\n'
            b'{"type": "cancel_timer", "id": "3"}\n{"type": "cancel_timer", "id": 3}\n{"type": "stop_alarm"}\n'
        )
        await writer.drain()
        display.phase("listening")
        update = json.loads(await asyncio.wait_for(reader.readline(), 2))
        assert update["phase"] == "listening"
        for _ in range(50):
            if len(commands.calls) == 4:
                break
            await asyncio.sleep(0.01)
        assert commands.calls == ["say:pausa", "talk", "cancel:3", "stop"]
        writer.close()
    finally:
        await server.close()


async def test_service_text_command_updates_display():
    app = build_app(Config(), simulated=True)
    service = Service(app, Display(app.timers, app.now_playing))
    response = await service.handle_text("pon un temporizador de cinco minutos para el pan")
    state = service.display.snapshot()
    assert state["answer"] == response.speech
    assert state["timers"][0]["label"] == "pan"
    assert await service.talk() is None  # sin voz cargada no hay turno


async def test_service_display_shows_simulated_music():
    app = build_app(Config(), simulated=True)
    service = Service(app, Display(app.timers, app.now_playing))
    await service.handle_text("pon soda stereo")
    await service.display.refresh_music()
    assert service.display.snapshot()["music"]["title"] == "Soda Stereo"


async def test_service_cancels_timer_and_stops_alarm_from_screen():
    app = build_app(Config(), simulated=True)
    service = Service(app, Display(app.timers, app.now_playing))
    timer = app.timers.add(300, "pan")
    await service.cancel_timer(999)
    assert app.timers.active == [timer]
    await service.cancel_timer(timer.id)
    assert app.timers.active == []
    await service.stop_alarm()  # sin alarma sonando no pasa nada
