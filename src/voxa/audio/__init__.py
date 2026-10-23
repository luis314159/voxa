"""Pipeline de voz: micrófono, fin de frase, STT, TTS, sonidos y ducking.

Todo el audio interno es mono. El micrófono trabaja a 16 kHz (lo que esperan
los motores de STT); la salida trabaja a 48 kHz.
"""

from voxa.audio.clip import MIC_RATE, OUTPUT_RATE, Clip

__all__ = ["Clip", "MIC_RATE", "OUTPUT_RATE"]
