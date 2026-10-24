"""«Hey Voxa»: detector de la palabra de activación.

Usa el mismo esquema que openWakeWord, sin su paquete (que en Python 3.12 pide ``tflite-runtime``):

1. ``melspectrogram.onnx`` convierte cada bloque de 80 ms en 8 cuadros de espectrograma mel.
2. ``embedding_model.onnx`` (el *speech embedding* de Google) resume cada 76 cuadros en 96 números.
3. Un clasificador pequeño, entrenado para VOXA (``scripts/hey_voxa/``), mira los últimos 16
   resúmenes (1.28 s) y da la probabilidad de que se acabe de decir «Hey Voxa».

Los dos primeros modelos se descargan con el instalador (``models/wakeword/``); el clasificador
viene con VOXA (``hey_voxa.npz``). Cuesta unos pocos milisegundos por bloque en CPU.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from voxa.audio.verifier import Verifier

log = logging.getLogger(__name__)

CHUNK = 1280  # 80 ms a 16 kHz
MEL_BINS = 32
MEL_WINDOW = 76  # cuadros mel por resumen
MEL_STEP = 8  # cuadros mel por bloque de 80 ms
EMBEDDING_DIM = 96
WINDOW = 16  # resúmenes que mira el clasificador
_MEL_CONTEXT = 480  # muestras previas que necesita el espectrograma para empalmar bloques

FEATURE_MODEL_URLS = {
    "melspectrogram.onnx": "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx",
    "embedding_model.onnx": "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx",
}
DEFAULT_MODEL = Path(__file__).with_name("hey_voxa.npz")


class FeatureModels:
    """Los dos modelos ONNX que convierten audio en resúmenes de 96 números."""

    def __init__(self, folder: Path, threads: int = 1) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.inter_op_num_threads = threads
        options.intra_op_num_threads = threads
        providers = ["CPUExecutionProvider"]
        self._mel = ort.InferenceSession(str(folder / "melspectrogram.onnx"), options, providers=providers)
        self._embedding = ort.InferenceSession(str(folder / "embedding_model.onnx"), options, providers=providers)

    def melspectrogram(self, samples: np.ndarray) -> np.ndarray:
        """int16 → (cuadros, 32), con el mismo ajuste que openWakeWord (``x / 10 + 2``)."""
        x = samples.astype(np.float32)[None, :]
        spec = np.squeeze(self._mel.run(None, {"input": x})[0])
        return (spec / 10 + 2).reshape(-1, MEL_BINS)

    def embed_mel(self, windows: np.ndarray) -> np.ndarray:
        """(n, 76, 32) → (n, 96)."""
        out = self._embedding.run(None, {"input_1": windows[..., None].astype(np.float32)})[0]
        return out.reshape(-1, EMBEDDING_DIM)

    def embed_clip(self, samples: np.ndarray) -> np.ndarray:
        """Un clip completo → un resumen cada 80 ms (para entrenar y evaluar)."""
        spec = self.melspectrogram(samples)
        starts = range(0, spec.shape[0] - MEL_WINDOW + 1, MEL_STEP)
        windows = np.stack([spec[i : i + MEL_WINDOW] for i in starts]) if len(starts) else np.empty((0, MEL_WINDOW, MEL_BINS))
        return self.embed_mel(windows) if len(windows) else np.empty((0, EMBEDDING_DIM), np.float32)


class StreamingFeatures:
    """Recibe bloques de 80 ms y mantiene los últimos resúmenes, igual que openWakeWord en vivo."""

    def __init__(self, models: FeatureModels) -> None:
        self._models = models
        self.reset()

    def reset(self) -> None:
        self._audio = np.zeros(0, dtype=np.int16)
        self._pending = np.zeros(0, dtype=np.int16)
        self._mel = np.ones((MEL_WINDOW, MEL_BINS), dtype=np.float32)
        self.embeddings: deque[np.ndarray] = deque(maxlen=WINDOW)

    @property
    def ready(self) -> bool:
        return len(self.embeddings) == WINDOW

    def feed(self, samples: np.ndarray) -> int:
        """Agrega audio (int16); devuelve cuántos resúmenes nuevos hay."""
        self._pending = np.concatenate([self._pending, samples.astype(np.int16)])
        added = 0
        while len(self._pending) >= CHUNK:
            chunk, self._pending = self._pending[:CHUNK], self._pending[CHUNK:]
            self._audio = np.concatenate([self._audio, chunk])[-(CHUNK + _MEL_CONTEXT) :]
            self._mel = np.vstack([self._mel, self._models.melspectrogram(self._audio)])[-MEL_WINDOW * 2 :]
            window = self._mel[-MEL_WINDOW:][None]
            self.embeddings.append(self._models.embed_mel(window)[0])
            added += 1
        return added

    def window(self) -> np.ndarray:
        return np.stack(self.embeddings)


@dataclass
class Classifier:
    """Red pequeña (capas densas con ReLU y salida sigmoide) guardada como arreglos de numpy."""

    weights: list[np.ndarray]
    biases: list[np.ndarray]

    @classmethod
    def load(cls, path: Path) -> Classifier:
        data = np.load(path)
        layers = sorted({int(k[1:]) for k in data.files if k[0] in "wb" and k[1:].isdigit()})
        return cls([data[f"w{i}"].astype(np.float32) for i in layers], [data[f"b{i}"].astype(np.float32) for i in layers])

    def save(self, path: Path, **metadata: object) -> None:
        arrays = {f"w{i}": w for i, w in enumerate(self.weights)} | {f"b{i}": b for i, b in enumerate(self.biases)}
        np.savez_compressed(path, **arrays, **{k: np.asarray(v) for k, v in metadata.items()})

    def predict(self, x: np.ndarray) -> np.ndarray:
        """(n, 16, 96) → probabilidades (n,)."""
        h = x.reshape(len(x), -1).astype(np.float32)
        for i, (w, b) in enumerate(zip(self.weights, self.biases)):
            h = h @ w + b
            if i < len(self.weights) - 1:
                h = np.maximum(h, 0.0)
        return 1.0 / (1.0 + np.exp(-np.clip(h[:, 0], -30, 30)))


def recommended_threshold(model: Path, default: float = 0.5) -> float:
    data = np.load(model)
    return float(data["threshold"]) if "threshold" in data.files else default


class WakeWordDetector:
    """Da ``True`` una vez por cada «Hey Voxa».

    - ``threshold``: probabilidad mínima (sube con muchas activaciones falsas, baja si no te oye).
    - ``patience``: bloques seguidos sobre el umbral (2 = 160 ms) para no dispararse con un chasquido.
    - ``refractory``: segundos sin volver a disparar después de una activación.
    """

    def __init__(
        self,
        features: StreamingFeatures,
        classifier: Classifier,
        threshold: float = 0.5,
        patience: int = 2,
        refractory: float = 2.0,
        verifier: Verifier | None = None,
    ) -> None:
        self._features = features
        self._classifier = classifier
        self.verifier = verifier
        self.rejected = 0
        """Veces que el verificador familiar descartó una activación del detector general."""
        self.threshold = threshold
        self._patience = patience
        self._refractory_chunks = int(refractory * 16000 / CHUNK)
        self._streak = 0
        self._cooldown = 0
        self.last_score = 0.0

    @classmethod
    def load(
        cls,
        feature_dir: Path,
        model: Path = DEFAULT_MODEL,
        threshold: float | None = None,
        verifier: Path | None = None,
        **kwargs,
    ) -> WakeWordDetector:
        """``threshold=None`` usa el umbral que eligió el entrenamiento (guardado junto al modelo).

        ``verifier``: el verificador familiar (``voxa entrenar-verificador``), si existe.
        """
        missing = [name for name in FEATURE_MODEL_URLS if not (feature_dir / name).exists()]
        if missing:
            raise FileNotFoundError(f"Faltan {', '.join(missing)} en {feature_dir} (los descarga scripts/install.sh)")
        if threshold is None:
            threshold = recommended_threshold(model)
        checker = None
        if verifier is not None and verifier.exists():
            from voxa.audio.verifier import Verifier

            checker = Verifier.load(verifier)
            log.info("«Hey Voxa» con verificador familiar (%s)", verifier)
        features = StreamingFeatures(FeatureModels(feature_dir))
        return cls(features, Classifier.load(model), threshold, verifier=checker, **kwargs)

    def reset(self) -> None:
        """Tras un turno o con el micrófono apagado: lo anterior ya no cuenta."""
        self._features.reset()
        self._streak = 0
        self._cooldown = 0

    def feed(self, frame: np.ndarray) -> bool:
        detected = False
        for _ in range(self._features.feed(frame)):
            if self._cooldown:
                self._cooldown -= 1
            if not self._features.ready:
                continue
            self.last_score = float(self._classifier.predict(self._features.window()[None])[0])
            self._streak = self._streak + 1 if self.last_score >= self.threshold else 0
            if self._streak >= self._patience and not self._cooldown:
                self._streak = 0
                if self.verifier is not None and not self.verifier.accepts(self._features.window()):
                    self.rejected += 1
                    continue  # sonó parecido, pero no es como lo dice la familia
                detected = True
                self._cooldown = self._refractory_chunks
        return detected
