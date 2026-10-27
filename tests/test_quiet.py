"""Horas de silencio: de noche, voz bajita y sin avisar alarmas en los otros cuartos."""

from datetime import datetime

import numpy as np

from voxa.audio.clip import Clip
from voxa.config import QuietConfig
from voxa.core.types import Response
from voxa.quiet import QuietHours
from voxa.settings import validate

NIGHT = QuietConfig(enabled=True, start="22:00", end="07:00", level=0.3)


def at(hour, minute=0, config=NIGHT):
    return QuietHours(config, clock=lambda: datetime(2026, 10, 27, hour, minute))


def test_quiet_hours_cross_midnight():
    assert at(23).active() and at(3).active() and at(6, 59).active()
    assert not at(7).active() and not at(15).active() and not at(21, 59).active()
    assert at(23).gain() == 0.3 and at(12).gain() == 1.0
    assert not at(23, config=QuietConfig()).active()  # apagadas de entrada
    assert at(14, config=QuietConfig(enabled=True, start="13:00", end="16:00")).active()  # la siesta


class Output:
    def __init__(self):
        self.peaks = []

    async def play(self, clip):
        self.peaks.append(round(float(np.abs(clip.samples).max()), 2))


async def test_the_voice_is_softer_but_the_alarm_is_not():
    from voxa.audio.ducking import NoDucking
    from voxa.voice import VoiceSession

    loud = Clip(np.full(160, 0.8, np.float32), 16000)
    output = Output()
    session = VoiceSession(None, None, None, output, {"ok": loud, "alarm": loud}, NoDucking())
    session.gain = at(23).gain
    await session.say(Response(sound="ok"))
    await session.announce("¡Terminó el temporizador!")
    assert output.peaks[0] == 0.24  # el «ok», bajito
    assert output.peaks[1] == 0.8  # la alarma, normal


def test_quiet_settings_from_the_phone():
    import pytest

    from voxa.settings import SettingsError

    assert validate("quiet", {"enabled": True, "start": "21:30", "level": 0.2}) == {
        "enabled": True, "start": "21:30", "level": 0.2}
    with pytest.raises(SettingsError):
        validate("quiet", {"level": 3})
