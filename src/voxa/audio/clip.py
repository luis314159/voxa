from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MIC_RATE = 16_000
OUTPUT_RATE = 48_000


@dataclass(frozen=True)
class Clip:
    """Audio mono en float32 dentro de [-1, 1]."""

    samples: np.ndarray
    rate: int

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate

    def resampled(self, rate: int) -> Clip:
        return self if rate == self.rate else Clip(resample(self.samples, self.rate, rate), rate)

    def with_silence(self, before_ms: int = 0, after_ms: int = 0) -> Clip:
        pad = lambda ms: np.zeros(int(self.rate * ms / 1000), dtype=np.float32)  # noqa: E731
        return Clip(np.concatenate([pad(before_ms), self.samples, pad(after_ms)]), self.rate)

    def to_int16(self) -> np.ndarray:
        return (np.clip(self.samples, -1.0, 1.0) * 32767).astype(np.int16)

    @classmethod
    def from_int16(cls, samples: np.ndarray, rate: int) -> Clip:
        return cls(samples.astype(np.float32) / 32768.0, rate)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.rate)
            wav.writeframes(self.to_int16().tobytes())

    @classmethod
    def load(cls, path: Path) -> Clip:
        with wave.open(str(path), "rb") as wav:
            if wav.getsampwidth() != 2:
                raise ValueError(f"{path}: solo se admite WAV de 16 bits")
            data = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
            channels, rate = wav.getnchannels(), wav.getframerate()
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
        return cls.from_int16(data, rate)


def _lowpass(samples: np.ndarray, cutoff: float, rate: int, taps: int = 101) -> np.ndarray:
    """FIR de sinc con ventana de Blackman: evita aliasing al bajar la frecuencia de muestreo."""
    n = np.arange(taps) - (taps - 1) / 2
    kernel = np.sinc(2 * cutoff / rate * n) * np.blackman(taps)
    kernel /= kernel.sum()
    return np.convolve(samples, kernel, mode="same")


def resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Interpolación lineal (con filtro anti-aliasing al bajar): suficiente para voz, sin scipy."""
    if src_rate == dst_rate or len(samples) == 0:
        return samples.astype(np.float32)
    if dst_rate < src_rate:
        samples = _lowpass(samples.astype(np.float64), 0.45 * dst_rate, src_rate)
    duration = len(samples) / src_rate
    target = np.arange(int(round(duration * dst_rate))) / dst_rate
    source = np.arange(len(samples)) / src_rate
    return np.interp(target, source, samples).astype(np.float32)
