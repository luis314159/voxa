"""Verificador familiar de «Hey Voxa» (plan §3.4).

El detector general se entrenó con voces sintéticas; este segundo filtro, pequeño, se entrena en
la propia cocina con grabaciones de la familia: unas cuantas veces «Hey Voxa» por persona y un
rato de plática normal, música o ruido de la cocina. Solo se consulta cuando el detector general
se dispara, así que casi no cuesta nada, y descarta lo que «sonó parecido» en esa cocina.

Las grabaciones se quedan en la PC (``~/.local/share/voxa/activacion/``) y nunca se suben a ningún lado.

    voxa grabar-activacion --persona mamá      # 8 veces «Hey Voxa» y 30 s de plática
    voxa entrenar-verificador                  # crea verificador.npz junto a los modelos
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from voxa.audio.wakeword import WINDOW, Classifier, FeatureModels

log = logging.getLogger(__name__)

POSITIVE_PREFIX = "si_"
NEGATIVE_PREFIX = "no_"


@dataclass
class Verifier:
    """Regresión logística sobre los 16×96 resúmenes, normalizados con la media y la escala de entrenamiento."""

    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: float
    threshold: float = 0.5

    def predict(self, windows: np.ndarray) -> np.ndarray:
        x = (windows.reshape(len(windows), -1) - self.mean) / self.scale
        return 1 / (1 + np.exp(-np.clip(x @ self.weights + self.bias, -30, 30)))

    def accepts(self, window: np.ndarray) -> bool:
        return bool(self.predict(window[None])[0] >= self.threshold)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, mean=self.mean, scale=self.scale, weights=self.weights,
                            bias=np.float32(self.bias), threshold=np.float32(self.threshold))

    @classmethod
    def load(cls, path: Path) -> Verifier:
        d = np.load(path)
        return cls(d["mean"], d["scale"], d["weights"], float(d["bias"]), float(d["threshold"]))


def train_verifier(
    positives: np.ndarray, negatives: np.ndarray, *, l2: float = 1.0, steps: int = 400, lr: float = 0.1
) -> Verifier:
    """Positivos y negativos de forma (n, 16, 96). Pocos datos: regresión logística con L2 fuerte."""
    x = np.concatenate([positives, negatives]).reshape(len(positives) + len(negatives), -1).astype(np.float64)
    y = np.concatenate([np.ones(len(positives)), np.zeros(len(negatives))])
    # Cada clase pesa lo mismo aunque haya muchos más negativos.
    weight = np.where(y == 1, 0.5 / len(positives), 0.5 / len(negatives))
    mean, scale = x.mean(0), x.std(0) + 1e-3
    x = (x - mean) / scale
    w, b = np.zeros(x.shape[1]), 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-np.clip(x @ w + b, -30, 30)))
        grad = (p - y) * weight
        w -= lr * (x.T @ grad + l2 * w / len(y))
        b -= lr * grad.sum()
    return Verifier(mean.astype(np.float32), scale.astype(np.float32), w.astype(np.float32), float(b))


def windows_from_recordings(
    folder: Path, models: FeatureModels, detector: Classifier
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Lee ``si_*.wav`` y ``no_*.wav`` (en subcarpetas por persona).

    De cada «Hey Voxa» se toma la ventana en que el detector general está más seguro (y sus vecinas):
    es justo la que el verificador tendrá que confirmar. De lo demás, todas las ventanas.
    """
    from voxa.audio.clip import MIC_RATE, Clip

    positives, negatives, notes = [], [], []
    for path in sorted(folder.rglob("*.wav")):
        audio = Clip.load(path).resampled(MIC_RATE).to_int16()
        emb = models.embed_clip(np.concatenate([np.zeros(MIC_RATE, np.int16), audio]))
        if len(emb) < WINDOW:
            continue
        windows = np.stack([emb[i - WINDOW : i] for i in range(WINDOW, len(emb) + 1)])
        if path.name.startswith(POSITIVE_PREFIX):
            scores = detector.predict(windows)
            best = int(scores.argmax())
            if scores[best] < 0.05:
                notes.append(f"{path.relative_to(folder)}: el detector casi no lo oyó ({scores[best]:.2f}); se usa igual")
            positives.extend(windows[max(0, best - 1) : best + 2])
        elif path.name.startswith(NEGATIVE_PREFIX):
            negatives.extend(windows[::2])
    return np.array(positives), np.array(negatives), notes
