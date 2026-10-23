"""Sonidos de VOXA (earcons), sintetizados al arrancar: no hace falta distribuir archivos.

Timbre tipo campana suave (seno + armónicos con caída exponencial), coherente
con la marca: brillante pero cálido. Pico a -6 dBFS para no saturar la bocina.
"""

from __future__ import annotations

import numpy as np

from voxa.audio.clip import OUTPUT_RATE, Clip

_PEAK = 0.5

# Notas (Hz)
_E5, _G5, _B5 = 659.25, 783.99, 987.77
_F4, _B4 = 349.23, 493.88
_C6, _E6, _G6 = 1046.50, 1318.51, 1567.98


def _bell(freq: float, ms: float, rate: int, decay: float = 18.0) -> np.ndarray:
    t = np.arange(int(rate * ms / 1000)) / rate
    tone = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t) + 0.08 * np.sin(6 * np.pi * freq * t)
    attack = np.minimum(1.0, t / 0.006)  # 6 ms: sin «clic» al inicio
    return (tone * attack * np.exp(-decay * t)).astype(np.float32)


def _sequence(notes: list[tuple[float, float]], rate: int, gap_ms: float, decay: float = 18.0) -> np.ndarray:
    """Notas que se encadenan: cada una empieza ``gap_ms`` después de la anterior y se deja sonar."""
    step = int(rate * gap_ms / 1000)
    parts = [_bell(f, ms, rate, decay) for f, ms in notes]
    out = np.zeros(step * (len(parts) - 1) + max(len(p) for p in parts), dtype=np.float32)
    for i, part in enumerate(parts):
        out[i * step : i * step + len(part)] += part
    return out


def _normalized(samples: np.ndarray, peak: float = _PEAK) -> np.ndarray:
    return (samples / np.max(np.abs(samples)) * peak).astype(np.float32)


def make_sounds(rate: int = OUTPUT_RATE) -> dict[str, Clip]:
    sounds = {
        # Subida de quinta: «te escucho».
        "listening": _sequence([(_E5, 260), (_B5, 320)], rate, gap_ms=85),
        # Una nota breve: «hecho».
        "ok": _sequence([(_G5, 220)], rate, gap_ms=0, decay=22),
        # Bajada: «no pude».
        "error": _sequence([(_B4, 240), (_F4, 320)], rate, gap_ms=120, decay=14),
        # Bajada de quinta, espejo de «listening»: «dejé de escuchar».
        "cancel": _sequence([(_B5, 220), (_E5, 300)], rate, gap_ms=85),
        # Arpegio que se repite: audible desde otra habitación sin ser estridente.
        "alarm": _sequence([(_C6, 300), (_E6, 300), (_G6, 300), (_C6, 300), (_E6, 300), (_G6, 500)], rate,
                           gap_ms=160, decay=8),
    }
    return {name: Clip(_normalized(s, 0.35 if name == "error" else _PEAK), rate) for name, s in sounds.items()}
