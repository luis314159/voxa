import asyncio
import json

from voxa.app import build_app
from voxa.config import Config
from voxa.core.types import Response
from voxa.display import Display, DisplayServer
from voxa.health import Health, Problem
from voxa.service import Service
from voxa.services.music_backend import NowPlaying
from voxa.services.weather import Weather, WeatherUnavailable
from voxa.state.timers import TimerManager
from voxa.voice import TurnResult, TurnTimings


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

    async def handle_text(self, text, *, button=False):
        self.calls.append(f"say:{text}" if button else f"text:{text}")

    async def cancel_timer(self, timer_id):
        self.calls.append(f"cancel:{timer_id}")

    async def stop_alarm(self):
        self.calls.append("stop")

    async def set_muted(self, on):
        self.calls.append(f"mute:{on}")

    def diagnostics(self):
        return {"sections": [], "problems": [], "log": ["⚠ 12:00 algo"]}


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
            b'{"type": "mute", "on": 1}\n{"type": "mute", "on": true}\n'
            b'{"type": "typed", "text": " que hora es "}\n{"type": "typed", "text": "  "}\n'
        )
        await writer.drain()
        display.phase("listening")
        update = json.loads(await asyncio.wait_for(reader.readline(), 2))
        assert update["phase"] == "listening"
        for _ in range(50):
            if len(commands.calls) == 6:
                break
            await asyncio.sleep(0.01)
        assert commands.calls == ["say:pausa", "talk", "cancel:3", "stop", "mute:True", "text:que hora es"]

        writer.write(b'{"type": "diagnostics"}\n')
        report = json.loads(await asyncio.wait_for(reader.readline(), 2))
        assert report["type"] == "diagnostics" and report["log"] == ["⚠ 12:00 algo"]
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


def test_snapshot_has_weather_problems_and_mute():
    display, _, _ = make_display()
    display.health = Health()
    display.health.report(Problem("internet", "Sin internet", "detalle que no va a la pantalla"))
    display.weather = Weather(21.6, 3, 27.4, 11.5, 40, is_day=False)
    display.muted = True
    state = display.snapshot()
    assert state["problems"] == [{"id": "internet", "text": "Sin internet"}]
    assert state["weather"] == {
        "temperature": 22, "high": 27, "low": 12, "rain_probability": 40, "code": 3, "is_day": False,
        "description": "nublado",
    }
    assert state["muted"] is True and state["video"] is None


async def test_weather_keeps_last_value_when_offline():
    calls = []

    async def weather():
        calls.append(1)
        if len(calls) > 1:
            raise WeatherUnavailable("sin red")
        return Weather(20, 0, 25, 10, 0)

    display = Display(TimerManager(), weather=weather)
    assert await display.refresh_weather() is True
    assert await display.refresh_weather() is False
    assert display.snapshot()["weather"]["temperature"] == 20


class FakeMic:
    def __init__(self, fails=False):
        self.fails, self.is_open, self.opened = fails, False, 0

    def open(self):
        if self.fails:
            raise OSError("Error querying device -1")
        self.is_open = True
        self.opened += 1

    def close(self):
        self.is_open = False


class FakeSession:
    def __init__(self, response=None):
        self.observer = None
        self.response = response
        self.said = []

    async def turn(self, mic, after_wake=False):
        self.after_wake = after_wake
        assert mic.is_open
        return TurnResult("algo", self.response, TurnTimings())

    async def say(self, response):
        self.said.append(response)
        return 0.0


def simulated_service():
    app = build_app(Config(), simulated=True)
    return Service.create(app), app


async def test_mute_by_voice_releases_the_microphone_and_a_tap_brings_it_back():
    service, _ = simulated_service()
    mic, session = FakeMic(), FakeSession()
    service.attach_voice(session, mic)
    assert session.observer is service and mic.is_open

    response = await service.handle_text("deja de escuchar")
    assert response.action == "mic.mute"
    assert service.muted and not mic.is_open and service.display.snapshot()["muted"] is True

    result = await service.talk()  # tocar el anillo: enciende y escucha
    assert result.heard == "algo" and not service.muted and mic.is_open


async def test_mute_from_the_screen_acknowledges_with_a_sound():
    service, _ = simulated_service()
    session = FakeSession()
    service.attach_voice(session, FakeMic())
    await service.set_muted(True)
    await service.set_muted(True)
    await service.set_muted(False)
    assert [r.sound for r in session.said] == ["cancel", "ok"]


async def test_missing_microphone_is_a_problem_until_it_opens():
    service, _ = simulated_service()
    mic, session = FakeMic(fails=True), FakeSession()
    service.attach_voice(session, mic)
    assert [p.id for p in service.health.problems] == ["microfono"]
    assert await service.talk() is None
    assert session.said[-1].speech == "No encuentro el micrófono."
    mic.fails = False
    assert (await service.talk()).heard == "algo"
    assert service.health.problems == []


async def test_video_shows_voxa_on_top_and_reports_its_title():
    service, app = simulated_service()
    await service.handle_text("pon un video de cómo hacer pan de elote")
    assert service.display.snapshot()["video"] == {"title": "Cómo hacer pan de elote"}
    service.phase("listening")
    await asyncio.sleep(0)
    assert "osd:🎙 Te escucho…" in app.video.calls
    app.video.finish()
    assert service.display.snapshot()["video"] is None


def test_diagnostics_report_is_plain_json():
    service, _ = simulated_service()
    report = service.diagnostics()
    json.dumps(report)
    titles = [s["title"] for s in report["sections"]]
    assert titles == ["VOXA", "Voz", "Música y video", "Red"]
    assert dict(report["sections"][1]["items"])["Micrófono"] == "sin voz cargada"


async def test_voice_turns_are_measured():
    service, app = simulated_service()
    session = FakeSession()
    service.attach_voice(session, FakeMic())
    await service.talk()  # «algo»: no lo entendió (sin IA)
    heard = []

    async def silence(mic, after_wake=False):
        return TurnResult(heard.pop() if heard else None, None, TurnTimings())

    session.turn = silence
    await service.talk(after_wake=True)  # «Hey Voxa» y nada: activación falsa
    await service.talk()  # tocar el anillo y no hablar no es una activación falsa
    summary = app.metrics.summary()
    assert summary["ordenes"] == 1 and summary["no_entendidas"] == 1
    assert app.metrics.days and next(iter(app.metrics.days.values()))["sin_orden"] == 1


async def test_after_answering_it_keeps_listening_for_a_command_only():
    """Accesibilidad: unos segundos sin «Hey Voxa»; la plática de alrededor se ignora."""
    from dataclasses import replace as changed

    from voxa.config import AccessibilityConfig

    service, app = simulated_service()
    app.config = changed(app.config, accessibility=AccessibilityConfig(follow_up_seconds=6))
    session = FakeSession(Response("Son las 5."))
    service.attach_voice(session, FakeMic())
    heard, answered = [], []

    async def transcribe(audio):
        return heard.pop()

    async def respond_to_text(text, audio):
        answered.append(text)
        return TurnResult(text, Response("Listo."), TurnTimings())

    session.transcribe, session.respond_to_text = transcribe, respond_to_text
    await service.talk()
    assert service._follow_until > 0 and service.display.snapshot()["phase"] == "listening"
    heard.append("y cómo te fue hoy en la escuela")  # plática: no es una orden
    await service._maybe_follow_up(b"")
    heard.append("súbele")
    await service._maybe_follow_up(b"")
    assert answered == ["súbele"]


def test_accessibility_settings():
    import pytest

    from voxa.settings import SettingsError, validate

    assert validate("accessibility", {"slow_for": ["Abuela Rosa"], "big_text": True, "follow_up_seconds": 6}) == {
        "slow_for": ["Abuela Rosa"], "big_text": True, "follow_up_seconds": 6}
    assert validate("voice", {"speech_rate": 1.2}) == {"speech_rate": 1.2}
    with pytest.raises(SettingsError):
        validate("voice", {"speech_rate": 3})
    with pytest.raises(SettingsError):
        validate("accessibility", {"follow_up_seconds": 60})


def test_big_text_reaches_the_screen():
    from dataclasses import replace as changed

    from voxa.config import AccessibilityConfig

    app = build_app(changed(Config(), accessibility=AccessibilityConfig(big_text=True)), simulated=True)
    assert Service.create(app).display.snapshot()["big_text"] is True
