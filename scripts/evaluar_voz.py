"""Evalúa la cadena completa voz → texto → intención con el corpus de frases.

Piper «dice» cada frase de tests/data/utterances.yaml (idealmente con una voz
distinta a la de VOXA), se le agrega ruido y se pasa por Vosk, Whisper y el
modo híbrido. Mide qué tan seguido se llega a la intención correcta y cuánto
tarda cada motor. Sirve en la PC de desarrollo y en la PC de la cocina.

    python scripts/evaluar_voz.py --voz models/piper/es_MX-ald-medium.onnx \
        --vosk models/vosk/vosk-model-small-es-0.42 --whisper base --ruido-db 15

    # música de fondo (la que queda bajita mientras VOXA escucha) y eco de cocina
    python scripts/evaluar_voz.py --voz ... --fondo musica --ruido-db 12 --eco
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import yaml

from voxa.audio.clip import MIC_RATE
from voxa.audio.stt import HybridStt, VoskStt, WhisperStt
from voxa.audio.tts import PiperTts
from voxa.nlu import load_matcher

CORPUS = Path(__file__).parents[1] / "tests" / "data" / "utterances.yaml"
WAKE = re.compile(r"^(?:hey|oye)\s+voxa[,\s]*", re.IGNORECASE)


def add_noise(samples: np.ndarray, snr_db: float | None, rng: np.random.Generator) -> np.ndarray:
    """Ruido rosa (parecido a extractor/refrigerador) a la relación señal/ruido indicada."""
    if snr_db is None:
        return samples
    white = rng.standard_normal(len(samples))
    # Filtro 1/f aproximado (Paul Kellet, versión económica).
    b0 = b1 = b2 = 0.0
    pink = np.empty_like(white)
    for i, w in enumerate(white):
        b0 = 0.99765 * b0 + w * 0.0990460
        b1 = 0.96300 * b1 + w * 0.2965164
        b2 = 0.57000 * b2 + w * 1.0526913
        pink[i] = b0 + b1 + b2 + w * 0.1848
    signal_power = np.mean(samples**2)
    noise = pink * np.sqrt(signal_power / (np.mean(pink**2) * 10 ** (snr_db / 10)))
    return np.clip(samples + noise, -1, 1).astype(np.float32)


def music(n: int, rng: np.random.Generator) -> np.ndarray:
    """Acordes con armónicos y una batería de ruido: no es música real, pero ocupa el espectro igual."""
    out = np.zeros(n, np.float32)
    t = np.arange(n) / MIC_RATE
    beat = int(MIC_RATE * rng.uniform(0.25, 0.6))
    for start in range(0, n, beat * 2):
        root = 110 * 2 ** (rng.integers(0, 24) / 12)
        seg = slice(start, min(start + beat * 2, n))
        for interval in (0, 4, 7, 12)[: rng.integers(2, 5)]:
            f = root * 2 ** (interval / 12)
            for h in range(1, 5):
                out[seg] += np.sin(2 * np.pi * f * h * t[seg]) / h**1.5
    for start in range(0, n, beat):
        k = min(int(0.05 * MIC_RATE), n - start)
        out[start : start + k] += rng.normal(size=k) * np.exp(-np.arange(k) / (0.01 * MIC_RATE)) * 2
    return out / (np.abs(out).max() + 1e-9)


def add_background(samples: np.ndarray, kind: str, snr_db: float | None, rng: np.random.Generator) -> np.ndarray:
    if snr_db is None:
        return samples
    if kind == "rosa":
        return add_noise(samples, snr_db, rng)
    noise = music(len(samples), rng)
    scale = np.sqrt(np.mean(samples**2) / (np.mean(noise**2) * 10 ** (snr_db / 10)))
    return np.clip(samples + noise * scale, -1, 1).astype(np.float32)


def reverb(samples: np.ndarray, rng: np.random.Generator, rt60: float = 0.4) -> np.ndarray:
    """Eco de un cuarto con azulejo: respuesta al impulso exponencial."""
    n = int(MIC_RATE * rt60)
    ir = rng.normal(size=n) * np.exp(-6.9 * np.arange(n) / n) * 0.3
    ir[0] = 1.0
    size = len(samples) + n
    wet = np.fft.irfft(np.fft.rfft(samples, size) * np.fft.rfft(ir, size), size)[: len(samples)]
    return (wet / (np.abs(wet).max() + 1e-9) * np.abs(samples).max()).astype(np.float32)


def matches(intent, case) -> bool:
    if intent is None or intent.name != case["intent"]:
        return False
    return all(intent.slots.get(k) == v for k, v in (case.get("slots") or {}).items())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--voz", type=Path, required=True, help="voz de Piper que «habla» las frases")
    parser.add_argument("--vosk", type=Path, help="carpeta del modelo de Vosk")
    parser.add_argument("--whisper", default="base", help="tamaño de faster-whisper (vacío para omitir)")
    parser.add_argument("--ruido-db", type=float, default=None, help="SNR del ruido agregado (p. ej. 15)")
    parser.add_argument("--fondo", choices=("rosa", "musica"), default="rosa", help="qué ruido: extractor (rosa) o música")
    parser.add_argument("--eco", action="store_true", help="agrega eco de cocina")
    parser.add_argument("--limite", type=int, default=0, help="evaluar solo las primeras N frases")
    sys.stdout.reconfigure(encoding="utf-8")  # «» y acentos aunque se redirija a un archivo en Windows
    args = parser.parse_args()

    matcher = load_matcher()
    cases = [c for c in yaml.safe_load(CORPUS.read_text(encoding="utf-8")) if c["intent"] and c["text"]]
    if args.limite:
        cases = cases[: args.limite]

    engines = {}
    if args.vosk:
        engines["vosk"] = VoskStt(args.vosk)
        engines["vosk-gramatica"] = VoskStt(args.vosk, matcher.vocabulary, model=engines["vosk"].model)
    if args.whisper:
        engines["whisper"] = WhisperStt(args.whisper)
    if args.vosk and args.whisper:
        engines["hibrido"] = HybridStt(
            engines["vosk"], engines["whisper"], matcher.needs_accurate_stt, matcher.understands,
            closed=engines["vosk-gramatica"],
        )
    if not engines:
        parser.error("indica al menos --vosk o --whisper")

    tts = PiperTts(args.voz)
    rng = np.random.default_rng(7)
    hits = {name: 0 for name in engines}
    times: dict[str, list[float]] = {name: [] for name in engines}
    failures: dict[str, list[str]] = {name: [] for name in engines}

    for n, case in enumerate(cases, 1):
        # En producción el detector consume «Hey Voxa» antes de grabar la orden, y el
        # endpointer conserva ~300 ms previos: se reproduce esa situación.
        spoken = WAKE.sub("", case["text"]) or case["text"]
        clip = tts.synthesize(spoken).with_silence(300, 300).resampled(MIC_RATE)
        samples = reverb(clip.samples, rng) if args.eco else clip.samples
        audio = (add_background(samples, args.fondo, args.ruido_db, rng) * 32767).astype(np.int16)
        for name, engine in engines.items():
            start = time.perf_counter()
            heard = engine.transcribe(audio)
            times[name].append(time.perf_counter() - start)
            if matches(matcher.match(heard), case):
                hits[name] += 1
            else:
                failures[name].append(f"«{case['text']}» → «{heard}»")
        print(f"\r{n}/{len(cases)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    noise = f"{'música' if args.fondo == 'musica' else 'ruido rosa'} a {args.ruido_db:g} dB SNR" if args.ruido_db is not None else "sin ruido"
    if args.eco:
        noise += " · con eco"
    print(f"\n{len(cases)} frases · voz {args.voz.stem} · {noise}\n")
    print(f"{'motor':<15}{'intención correcta':>20}{'tiempo medio':>15}{'p90':>10}")
    for name in engines:
        t = sorted(times[name])
        p90 = t[int(0.9 * (len(t) - 1))]
        print(f"{name:<15}{hits[name] / len(cases):>19.0%} {statistics.mean(t):>13.2f}s{p90:>9.2f}s")
    for name in engines:
        if failures[name]:
            print(f"\nFallos de {name}:")
            for line in failures[name]:
                print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
