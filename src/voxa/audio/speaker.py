"""¿Quién habla? Un prototipo de voz por persona y similitud coseno.

El modelo (WeSpeaker ResNet34, VoxCeleb, CC BY 4.0) convierte unos segundos de voz en una huella de
256 números. Cada persona de la familia tiene su prototipo: el promedio de las huellas (normalizadas)
de lo que grabó con «aprende mi voz». En cada orden se compara la huella de lo que se oyó con los
prototipos por coseno (con vectores normalizados, la distancia euclidiana daría el mismo orden).

Lo importante es poder decir «no sé»: se acepta a la persona más parecida solo si pasa el umbral y
le saca ventaja a la segunda. El umbral se calibra con las grabaciones de cada familia (cada trozo
contra su propio prototipo sin él, y contra los de los demás).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

RATE = 16000
SEGMENT_SECONDS = 3.0
MIN_SECONDS = 0.8
DEFAULT_THRESHOLD = 0.45
MARGIN = 0.06
MODEL_URL = "https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main/wespeaker_en_voxceleb_resnet34_LM.onnx"
MODEL_SHA256 = "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012"


# --- fbank al estilo Kaldi (lo que espera WeSpeaker) ------------------------------------------
_FRAME, _HOP, _FFT, _MELS = 400, 160, 512, 80


def _mel(hz: np.ndarray) -> np.ndarray:
    return 1127.0 * np.log1p(hz / 700.0)


def _mel_banks() -> np.ndarray:
    low, high = _mel(np.array(20.0)), _mel(np.array(RATE / 2))
    centers = np.linspace(low, high, _MELS + 2)
    freqs = _mel(np.arange(_FFT // 2) * RATE / _FFT)
    banks = np.zeros((_MELS, _FFT // 2 + 1), np.float32)
    for m in range(_MELS):
        left, center, right = centers[m], centers[m + 1], centers[m + 2]
        up = (freqs - left) / (center - left)
        down = (right - freqs) / (right - center)
        banks[m, : _FFT // 2] = np.maximum(0.0, np.minimum(up, down))
    return banks


_BANKS = _mel_banks()
_WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(_FRAME) / (_FRAME - 1))) ** 0.85  # ventana «povey»


def fbank(samples: np.ndarray) -> np.ndarray:
    """(cuadros, 80) de log-energías mel, con la media restada (CMN). ``samples``: int16 a 16 kHz."""
    x = samples.astype(np.float32)
    if len(x) < _FRAME:
        x = np.pad(x, (0, _FRAME - len(x)))
    count = 1 + (len(x) - _FRAME) // _HOP
    index = np.arange(_FRAME)[None, :] + _HOP * np.arange(count)[:, None]
    frames = x[index]
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1] * (1 - 0.97), frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    frames = frames * _WINDOW
    power = np.abs(np.fft.rfft(frames, n=_FFT)) ** 2
    feats = np.log(np.maximum(power @ _BANKS.T, np.finfo(np.float32).eps))
    return (feats - feats.mean(axis=0, keepdims=True)).astype(np.float32)


def _normalized(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-9)


class SpeakerModel:
    def __init__(self, path: Path) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self._session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])

    def embed(self, samples: np.ndarray) -> np.ndarray:
        feats = fbank(samples)[None, :, :]
        return _normalized(self._session.run(None, {"feats": feats})[0][0])


def segments(audio: np.ndarray, seconds: float = SEGMENT_SECONDS) -> list[np.ndarray]:
    """Trozos de ~3 s (una orden corta es un solo trozo); se descarta lo muy corto."""
    size = int(seconds * RATE)
    if len(audio) <= size * 1.5:
        return [audio] if len(audio) >= MIN_SECONDS * RATE else []
    return [audio[i : i + size] for i in range(0, len(audio) - size + 1, size)]


@dataclass(frozen=True)
class Guess:
    person: str | None
    score: float
    runner_up: float


class Voices:
    """Los prototipos de la familia y el umbral calibrado."""

    def __init__(self, names: list[str], prototypes: np.ndarray, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.names = names
        self.prototypes = prototypes
        self.threshold = threshold

    def identify(self, embedding: np.ndarray) -> Guess:
        if not self.names:
            return Guess(None, 0.0, 0.0)
        scores = self.prototypes @ embedding
        order = np.argsort(scores)[::-1]
        best = float(scores[order[0]])
        second = float(scores[order[1]]) if len(order) > 1 else -1.0
        person = self.names[order[0]] if best >= self.threshold and best - second >= MARGIN else None
        return Guess(person, best, second)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, names=np.array(self.names), prototypes=self.prototypes, threshold=np.array(self.threshold))

    @classmethod
    def load(cls, path: Path) -> Voices:
        data = np.load(path)
        return cls([str(n) for n in data["names"]], data["prototypes"], float(data["threshold"]))


def build_voices(embeddings: dict[str, list[np.ndarray]]) -> Voices:
    """Prototipos (promedio normalizado) y un umbral entre lo propio y lo ajeno de esta familia."""
    names = sorted(n for n, e in embeddings.items() if e)
    prototypes = np.stack([_normalized(np.mean(embeddings[n], axis=0)) for n in names]) if names else np.zeros((0, 256))
    genuine, impostor = [], []
    for i, name in enumerate(names):
        own = embeddings[name]
        for j, e in enumerate(own):
            rest = [x for k, x in enumerate(own) if k != j]
            if rest:  # contra su prototipo sin esa muestra (si no, el puntaje sale inflado)
                genuine.append(float(_normalized(np.mean(rest, axis=0)) @ e))
            impostor += [float(prototypes[k] @ e) for k in range(len(names)) if k != i]
    threshold = DEFAULT_THRESHOLD
    if genuine and impostor:
        # A medio camino entre lo más bajo de lo propio (percentil 10) y lo más alto de lo ajeno (90).
        threshold = float(np.clip((np.percentile(genuine, 10) + np.percentile(impostor, 90)) / 2, 0.25, 0.75))
    elif genuine:
        threshold = float(np.clip(np.percentile(genuine, 10) - 0.1, 0.25, 0.75))
    return Voices(names, prototypes, threshold)


NAME_FILE = "nombre.txt"


def person_name(folder: Path) -> str:
    """El nombre como se dijo al grabar («María José»); si no está, el de la carpeta."""
    try:
        return (folder / NAME_FILE).read_text(encoding="utf-8").strip() or folder.name.title()
    except OSError:
        return folder.name.replace("-", " ").title()


def family_names(recordings: Path) -> list[str]:
    """Quiénes grabaron su voz («aprende mi voz»), con su nombre como lo dijeron."""
    if not recordings.is_dir():
        return []
    return sorted(person_name(p) for p in recordings.iterdir() if p.is_dir() and any(p.glob("si_*.wav")))


class SpeakerIdentifier:
    """Lo que usa el turno de voz: carga el modelo una vez y los prototipos cada que cambian."""

    def __init__(self, model_path: Path, voices_path: Path) -> None:
        self._model_path = model_path
        self._voices_path = voices_path
        self._model: SpeakerModel | None = None
        self._voices: Voices | None = None
        self._stamp = 0.0

    def __call__(self, audio: np.ndarray) -> str | None:
        try:
            stamp = self._voices_path.stat().st_mtime
        except OSError:
            return None  # nadie ha grabado su voz todavía
        if stamp != self._stamp:
            self._voices, self._stamp = Voices.load(self._voices_path), stamp
        if self._model is None:
            if not self._model_path.exists():
                return None
            self._model = SpeakerModel(self._model_path)
        if len(audio) < MIN_SECONDS * RATE or self._voices is None:
            return None
        guess = self._voices.identify(self._model.embed(audio))
        log.info("Voz: %s (%.2f; la siguiente %.2f)", guess.person or "¿?", guess.score, guess.runner_up)
        return guess.person


def embeddings_from_recordings(
    folder: Path, embed: Callable[[np.ndarray], np.ndarray]
) -> dict[str, list[np.ndarray]]:
    """Las huellas de cada persona (una carpeta por persona: ``si_*.wav`` y ``no_*.wav``)."""
    from voxa.audio.clip import Clip

    out: dict[str, list[np.ndarray]] = {}
    for person in sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []:
        for wav in sorted(person.glob("*.wav")):
            audio = Clip.load(wav).resampled(RATE).to_int16()
            out.setdefault(person_name(person), []).extend(embed(s) for s in segments(audio))
    return out
