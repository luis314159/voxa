import asyncio
import collections

import numpy as np
import pytest

from voxa.app import build_app
from voxa.audio.wakeword import CHUNK, WINDOW, Classifier, WakeWordDetector, recommended_threshold
from voxa.config import Config
from voxa.service import Service
from voxa.voice import TurnResult, TurnTimings


class FakeFeatures:
    """Un resumen nuevo por bloque; el «modelo» lee la puntuación del propio audio."""

    def __init__(self):
        self.embeddings = collections.deque(maxlen=WINDOW)

    @property
    def ready(self):
        return len(self.embeddings) == WINDOW

    def reset(self):
        self.embeddings.clear()

    def feed(self, samples):
        self.embeddings.append(np.full(96, samples[0] / 1000.0, np.float32))
        return 1

    def window(self):
        return np.stack(self.embeddings)


class LastScore:
    def predict(self, x):
        return x[:, -1, 0]


def frames(*scores):
    return [np.full(CHUNK, int(s * 1000), np.int16) for s in scores]


def run(detector, scores):
    return [detector.feed(f) for f in frames(*scores)]


def test_needs_consecutive_blocks_and_waits_after_firing():
    detector = WakeWordDetector(FakeFeatures(), LastScore(), threshold=0.5, patience=2, refractory=0.4)
    warmup = run(detector, [0.0] * WINDOW)
    assert not any(warmup)
    assert run(detector, [0.9, 0.1, 0.9, 0.9]) == [False, False, False, True]  # un pico suelto no basta
    assert run(detector, [0.9] * 6) == [False, False, False, False, True, False]  # 5 bloques de pausa
    assert detector.last_score == pytest.approx(0.9)


def test_reset_forgets_the_context():
    detector = WakeWordDetector(FakeFeatures(), LastScore(), threshold=0.5, patience=1)
    run(detector, [0.0] * WINDOW)
    detector.reset()
    assert run(detector, [0.9] * (WINDOW - 1)) == [False] * (WINDOW - 1)  # aún no hay 1.28 s de contexto
    assert run(detector, [0.9]) == [True]


def test_classifier_round_trip_and_recommended_threshold(tmp_path):
    rng = np.random.default_rng(0)
    clf = Classifier([rng.normal(size=(WINDOW * 96, 8)).astype(np.float32), rng.normal(size=(8, 1)).astype(np.float32)],
                     [np.zeros(8, np.float32), np.zeros(1, np.float32)])
    path = tmp_path / "modelo.npz"
    clf.save(path, threshold=0.65)
    x = rng.normal(size=(3, WINDOW, 96)).astype(np.float32)
    loaded = Classifier.load(path)
    np.testing.assert_allclose(loaded.predict(x), clf.predict(x), rtol=1e-6)
    assert ((loaded.predict(x) >= 0) & (loaded.predict(x) <= 1)).all()
    assert recommended_threshold(path) == pytest.approx(0.65)
    Classifier.load(path).save(tmp_path / "sin_umbral.npz")
    assert recommended_threshold(tmp_path / "sin_umbral.npz") == 0.5


def test_missing_base_models_are_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="melspectrogram.onnx"):
        WakeWordDetector.load(tmp_path)


class QueueMic:
    """Micrófono de prueba: entrega los bloques que se le pongan."""

    def __init__(self):
        self.queue = asyncio.Queue()
        self.pushed = collections.deque()
        self.is_open = True

    def open(self):
        self.is_open = True

    def close(self):
        self.is_open = False

    def push_back(self, frames):
        self.pushed.extendleft(reversed(frames))

    def clear(self):
        self.pushed.clear()
        while not self.queue.empty():
            self.queue.get_nowait()

    async def read(self):
        return self.pushed.popleft() if self.pushed else await self.queue.get()


class OnceDetector:
    """Se «oye» «Hey Voxa» en el bloque marcado con 7777."""

    patience = 2
    last_score = 0.9

    def __init__(self):
        self.resets = 0

    def feed(self, frame):
        return bool(frame[0] == 7777)

    def reset(self):
        self.resets += 1


class RecordingSession:
    def __init__(self, heard="ya"):
        self.observer = None
        self.turns = []
        self.heard = heard
        self.said = []

    async def turn(self, mic, after_wake=False):
        first = await mic.read()  # lo primero de la orden
        self.turns.append((after_wake, int(first[0])))
        return TurnResult("pon música", None, TurnTimings())

    async def transcribe(self, audio):
        return self.heard

    async def say(self, response):
        self.said.append(response)
        return 0.0

    async def announce(self, text):
        pass


async def wait_for(condition, seconds=3.0):
    for _ in range(int(seconds / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no pasó a tiempo")


async def test_wake_word_starts_a_turn_keeping_what_followed():
    service = Service.create(build_app(Config(), simulated=True))
    mic, session, detector = QueueMic(), RecordingSession(), OnceDetector()
    service.attach_voice(session, mic)
    service.attach_wake(detector)
    assert service.display.snapshot()["wake_word"] == "Hey Voxa"
    async with service.running(None):
        for value in (1, 2, 3, 4, 7777):
            mic.queue.put_nowait(np.full(CHUNK, value, np.int16))
        await wait_for(lambda: session.turns)
    # El turno empieza con el bloque que disparó la detección (pudo traer el inicio de la orden).
    assert session.turns == [(True, 7777)]
    assert service.wake_count == 1 and detector.resets >= 1

    await service.set_muted(True)
    assert service.display.snapshot()["wake_word"] is None


def speech(level):
    rng = np.random.default_rng(level)
    return (rng.normal(0, level, CHUNK)).astype(np.int16)


async def test_saying_ya_stops_a_ringing_alarm_without_the_wake_word():
    app = build_app(Config(), simulated=True)
    service = Service.create(app)
    mic, session = QueueMic(), RecordingSession(heard="ya")
    service.attach_voice(session, mic)
    service.attach_wake(OnceDetector())
    app.timers.add(0, "el pan")
    app.timers.check()
    assert app.timers.ringing
    async with service.running(None):
        for frame in [speech(20)] * 5 + [speech(8000)] * 6 + [speech(20)] * 10:
            mic.queue.put_nowait(frame)
        await wait_for(lambda: not app.timers.ringing)
    assert session.turns == []  # no hizo falta «Hey Voxa»


async def test_other_words_do_not_stop_the_alarm():
    app = build_app(Config(), simulated=True)
    service = Service.create(app)
    mic, session = QueueMic(), RecordingSession(heard="pon música")
    service.attach_voice(session, mic)
    service.attach_wake(OnceDetector())
    app.timers.add(0, "el pan")
    app.timers.check()
    async with service.running(None):
        for frame in [speech(20)] * 5 + [speech(8000)] * 6 + [speech(20)] * 10:
            mic.queue.put_nowait(frame)
        await wait_for(lambda: mic.queue.empty())
        await asyncio.sleep(0.05)
    assert app.timers.ringing


async def test_microphone_reads_pushed_back_frames_first():
    from voxa.audio.devices import Microphone
    from voxa.audio.endpoint import EndpointConfig, UtteranceCollector

    mic = Microphone()
    loud = [np.full(CHUNK, 9000, np.int16) * (1 if i % 2 else -1) for i in range(4)]
    for i in range(3):
        mic._put(np.full(CHUNK, 10 + i, np.int16))
    mic.push_back([np.full(CHUNK, 1, np.int16), np.full(CHUNK, 2, np.int16)])
    assert [int((await mic.read())[0]) for _ in range(4)] == [1, 2, 10, 11]

    # Tras «Hey Voxa» no se vacía la cola: la orden ya venía en camino.
    mic.clear()
    quiet = np.zeros(CHUNK, np.int16)
    for frame in [quiet] * 3 + loud + [quiet] * 12:
        mic._put(frame)
    mic.push_back([loud[0]])
    audio = await mic.record_utterance(UtteranceCollector(EndpointConfig(end_silence_ms=480)), clear=False)
    assert audio is not None and np.abs(audio).max() == 9000
