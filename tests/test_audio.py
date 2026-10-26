import json

import numpy as np
import pytest

from voxa.audio.clip import MIC_RATE, Clip, resample
from voxa.audio.ducking import PipeWireDucker
from voxa.audio.endpoint import FRAME_SAMPLES, EndpointConfig, State, UtteranceCollector
from voxa.audio.sounds import make_sounds
from voxa.audio.stt import UNKNOWN, HybridStt, accent_variants
from voxa.nlu.normalize import normalize, phonetic_key
from voxa.services.process import CommandResult

rng = np.random.default_rng(0)


def tone(freq, seconds, rate, amp=0.5):
    t = np.arange(int(rate * seconds)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_resample_keeps_duration_and_filters_aliasing():
    voice_band = tone(1000, 1.0, 22050)
    above_nyquist = tone(10000, 1.0, 22050)  # no cabe en 16 kHz: debe desaparecer, no «doblarse»
    assert len(resample(voice_band, 22050, 16000)) == 16000
    kept = np.std(resample(voice_band, 22050, 16000))
    leaked = np.std(resample(above_nyquist, 22050, 16000))
    assert kept > 0.3 and leaked < 0.02


def test_clip_wav_roundtrip(tmp_path):
    clip = Clip(tone(440, 0.2, 22050), 22050)
    clip.save(tmp_path / "x.wav")
    loaded = Clip.load(tmp_path / "x.wav")
    assert loaded.rate == 22050 and np.allclose(loaded.samples, clip.samples, atol=1e-3)


def test_sounds_are_short_and_never_clip():
    sounds = make_sounds()
    assert set(sounds) == {"listening", "ok", "error", "cancel", "alarm"}
    for name, clip in sounds.items():
        assert np.max(np.abs(clip.samples)) <= 0.5 + 1e-6, name
        assert clip.seconds < (2.5 if name == "alarm" else 0.7), name


# --- fin de frase ---------------------------------------------------------
def frames(seconds, amp):
    n = int(seconds * 1000 / 80)
    return [(rng.standard_normal(FRAME_SAMPLES) * amp * 32767).astype(np.int16) for _ in range(n)]


def run(collector, chunks):
    for frame in chunks:
        if collector.feed(frame) in (State.DONE, State.NO_SPEECH):
            break
    return collector.state


def test_detects_utterance_and_keeps_preroll():
    collector = UtteranceCollector()
    state = run(collector, frames(0.5, 0.002) + frames(1.2, 0.2) + frames(1.5, 0.002))
    assert state is State.DONE
    seconds = len(collector.audio) / MIC_RATE
    assert 1.4 <= seconds <= 2.1  # habla + ~300 ms previos + un poco de cola


def test_no_speech_times_out():
    collector = UtteranceCollector(EndpointConfig(no_speech_timeout_ms=1000))
    assert run(collector, frames(2.0, 0.002)) is State.NO_SPEECH


def test_long_speech_is_capped():
    collector = UtteranceCollector(EndpointConfig(max_ms=2000))
    assert run(collector, frames(0.3, 0.002) + frames(5.0, 0.2)) is State.DONE
    assert len(collector.audio) / MIC_RATE <= 2.1


def test_constant_kitchen_noise_is_not_speech():
    collector = UtteranceCollector(EndpointConfig(no_speech_timeout_ms=3000))
    assert run(collector, frames(4.0, 0.05)) is State.NO_SPEECH


# --- STT ------------------------------------------------------------------
class FakeStt:
    def __init__(self, name, text):
        self.name, self.text, self.calls = name, text, 0

    def transcribe(self, samples):
        self.calls += 1
        return self.text


def hybrid(fast_text, accurate_text):
    from voxa.nlu import load_matcher

    matcher = load_matcher()
    fast, accurate = FakeStt("vosk", fast_text), FakeStt("whisper", accurate_text)
    return HybridStt(fast, accurate, matcher.needs_accurate_stt, matcher.understands), fast, accurate


def test_hybrid_keeps_fast_result_for_closed_commands():
    stt, _, accurate = hybrid("pausa", "Pausa.")
    assert stt.transcribe(np.zeros(10)) == "pausa" and accurate.calls == 0


def test_hybrid_uses_accurate_engine_for_song_names():
    stt, _, accurate = hybrid("pon soda estero", "Pon Soda Stereo.")
    assert stt.transcribe(np.zeros(10)) == "Pon Soda Stereo." and accurate.calls == 1


def test_hybrid_falls_back_when_accurate_engine_invents():
    stt, _, _ = hybrid("con soda stereo", "¡Giores!")
    assert stt.transcribe(np.zeros(10)) == "con soda stereo"


def test_hybrid_sends_unknown_words_to_accurate_engine():
    stt, _, accurate = hybrid(f"pausa {UNKNOWN}", "Pausa la música.")
    assert stt.transcribe(np.zeros(10)) == "Pausa la música." and accurate.calls == 1


def closed_first(closed_text, fast_text, accurate_text):
    from voxa.nlu import load_matcher

    matcher = load_matcher()
    closed = FakeStt("vosk-gramatica", closed_text)
    fast, accurate = FakeStt("vosk", fast_text), FakeStt("whisper", accurate_text)
    stt = HybridStt(fast, accurate, matcher.needs_accurate_stt, matcher.understands, closed=closed)
    return stt, fast, accurate


def test_closed_grammar_wins_for_short_commands():
    stt, fast, accurate = closed_first("pausa", "volsa", "¡Volsar!")
    assert stt.transcribe(np.zeros(10)) == "pausa" and fast.calls == accurate.calls == 0


def test_closed_grammar_is_ignored_with_unknown_words_or_free_text():
    stt, _, accurate = closed_first(f"pon {UNKNOWN}", "pon soda estero", "Pon Soda Stereo.")
    assert stt.transcribe(np.zeros(10)) == "Pon Soda Stereo." and accurate.calls == 1
    # «pon salsa» lleva texto libre (lo que se busca): no se confía en el vocabulario cerrado.
    stt, _, accurate = closed_first("pon salsa", "pon salsa", "Pon salsa.")
    assert stt.transcribe(np.zeros(10)) == "Pon salsa." and accurate.calls == 1


def test_accent_variants():
    assert {"musica", "música", "musíca"} <= accent_variants("musica")
    assert "añade" in accent_variants("anade")


@pytest.mark.parametrize(
    ("a", "b"), [("abizame", "avisame"), ("posole", "pozole"), ("reseta", "receta"), ("ola", "hola")]
)
def test_phonetic_key_merges_spanish_homophones(a, b):
    assert phonetic_key(a) == phonetic_key(b)


def test_phonetic_key_keeps_ch():
    assert phonetic_key("noche") == "noche"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("cómo van los temporizador es", "como van los temporizadores"), ("baja le mucho", "bajale mucho"),
     ("con algo de música", "pon algo de musica"), ("baja la música", "baja la musica")],
)
def test_stt_fixes(raw, expected):
    assert normalize(raw) == expected


# --- ducking --------------------------------------------------------------
class PipeWireFake:
    def __init__(self):
        self.calls = []
        nodes = [
            {"id": 51, "type": "PipeWire:Interface:Node",
             "info": {"props": {"media.class": "Stream/Output/Audio", "application.process.id": 900}}},
            {"id": 60, "type": "PipeWire:Interface:Node",
             "info": {"props": {"media.class": "Stream/Output/Audio", "application.process.id": 4242}}},
            {"id": 70, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Sink"}}},
        ]
        self.dump = json.dumps(nodes)

    async def __call__(self, args, timeout=5.0):
        self.calls.append(list(args))
        if args[0] == "pw-dump":
            return CommandResult(0, self.dump)
        if args[1] == "get-volume":
            return CommandResult(0, "Volume: 0.80\n")
        return CommandResult(0, "")


async def test_ducking_lowers_other_streams_and_restores_them():
    run_fake = PipeWireFake()
    ducker = PipeWireDucker(level=0.25, run=run_fake, own_pid=4242)
    await ducker.duck()
    await ducker.duck()  # idempotente
    await ducker.restore()
    sets = [c for c in run_fake.calls if c[1:2] == ["set-volume"]]
    assert sets == [["wpctl", "set-volume", "51", "0.200"], ["wpctl", "set-volume", "51", "0.800"]]
