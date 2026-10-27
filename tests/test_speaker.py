from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from voxa.audio.speaker import (
    SpeakerIdentifier,
    Voices,
    build_voices,
    fbank,
    person_name,
    segments,
)
from voxa.core.people import speaker, speaking
from voxa.nlu import load_matcher
from voxa.skills.routine import RoutineSkill
from voxa.skills.timers import TimerSkill, ring_phrase
from voxa.state.timers import TimerManager

REPO = Path(__file__).resolve().parents[1]
MODEL = REPO / "models/speaker/wespeaker_en_voxceleb_resnet34_LM.onnx"
RNG = np.random.default_rng(7)


def voice_of(center, n=6, spread=0.35):
    out = []
    for _ in range(n):
        v = center + RNG.normal(0, spread / np.sqrt(len(center)), len(center))
        out.append(v / np.linalg.norm(v))
    return out


def unit(v):
    return v / np.linalg.norm(v)


def test_fbank_like_kaldi_shapes():
    feats = fbank((RNG.normal(0, 3000, 16000)).astype(np.int16))
    assert feats.shape == (98, 80)  # 1 s: 25 ms cada 10 ms
    assert abs(float(feats.mean())) < 1e-3  # media restada
    assert fbank(np.zeros(100, np.int16)).shape == (1, 80)


def test_segments_cut_long_talk_and_drop_tiny_bits():
    assert len(segments(np.zeros(16000 * 20, np.int16))) == 6
    assert len(segments(np.zeros(16000 * 2, np.int16))) == 1
    assert segments(np.zeros(4000, np.int16)) == []


def test_prototypes_identify_and_say_dont_know():
    ana, luis = unit(RNG.normal(size=256)), unit(RNG.normal(size=256))
    voices = build_voices({"Ana": voice_of(ana), "Luis": voice_of(luis)})
    assert voices.names == ["Ana", "Luis"]
    assert 0.25 <= voices.threshold <= 0.75
    assert voices.identify(voice_of(ana, 1)[0]).person == "Ana"
    assert voices.identify(voice_of(luis, 1)[0]).person == "Luis"
    stranger = unit(RNG.normal(size=256))
    assert voices.identify(stranger).person is None  # alguien de visita: «no sé»
    halfway = unit(ana + luis)
    assert voices.identify(halfway).person is None  # muy parecido a dos: tampoco


def test_voices_round_trip(tmp_path):
    voices = build_voices({"Ana": voice_of(unit(RNG.normal(size=256)))})
    voices.save(tmp_path / "voces.npz")
    again = Voices.load(tmp_path / "voces.npz")
    assert again.names == ["Ana"] and again.threshold == pytest.approx(voices.threshold)


def test_identifier_without_recordings_knows_nobody(tmp_path):
    identify = SpeakerIdentifier(tmp_path / "modelo.onnx", tmp_path / "voces.npz")
    assert identify(np.zeros(32000, np.int16)) is None


def test_names_come_from_the_recording(tmp_path):
    folder = tmp_path / "maria-jose"
    folder.mkdir()
    assert person_name(folder) == "Maria Jose"
    (folder / "nombre.txt").write_text("María José", encoding="utf-8")
    assert person_name(folder) == "María José"


async def test_reminders_are_for_whoever_asked(tmp_path):
    matcher = load_matcher()
    timers = TimerManager(tmp_path / "t.json")
    skill = TimerSkill(timers, now=lambda: datetime(2026, 10, 27, 10, 0))
    with speaking("Ana"):
        said = (await skill.handle(matcher.match("recuérdame tomar la medicina a las 8 de la noche"))).speech
    assert said == "A las 8 de la noche te recuerdo tomar la medicina."
    assert ring_phrase(timers.active[0]) == "Ana, te recuerdo: tomar la medicina."
    said = (await skill.handle(matcher.match("recuérdale a Luis que saque la basura a las 9 de la noche"))).speech
    assert said == "A las 9 de la noche le recuerdo a Luis saque la basura."
    assert timers.active[1].person == "Luis"
    assert speaker() is None


async def test_good_morning_greets_by_name(tmp_path):
    routine = RoutineSkill(TimerManager(tmp_path / "t.json"), now=lambda: datetime(2026, 10, 27, 7, 5))
    with speaking("Ana"):
        said = (await routine.handle(load_matcher().match("buenos días"))).speech
    assert said.startswith("¡Buenos días, Ana!")


@pytest.mark.skipif(not MODEL.exists() or not (REPO / "models/piper/es_MX-ald-medium.onnx").exists(),
                    reason="modelos locales (models/speaker, models/piper)")
def test_two_real_voices_are_told_apart():
    from voxa.audio.speaker import SpeakerModel
    from voxa.audio.tts import PiperTts

    model = SpeakerModel(MODEL)
    voices = {n: PiperTts(REPO / f"models/piper/es_MX-{n}.onnx") for n in ("claude-high", "ald-medium")}

    def audio(tts, text):
        return tts.synthesize(text).resampled(16000).to_int16()

    enroll = ["Hey Voxa"] * 4 + ["Hoy vamos a cocinar arroz rojo con pollo y una ensalada para toda la familia."]
    family = build_voices({n: [model.embed(s) for t in enroll for s in segments(audio(tts, t))]
                           for n, tts in voices.items()})
    for name, tts in voices.items():
        assert family.identify(model.embed(audio(tts, "pon música de Soda Stereo"))).person == name
