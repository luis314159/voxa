"""Entrena el clasificador de «Hey Voxa» con los datos de ``generar.py`` y lo evalúa.

    python scripts/hey_voxa/entrenar.py --datos DATOS --negativos NEGATIVOS --modelos MODELOS \\
        [--salida src/voxa/audio/hey_voxa.npz]

- NEGATIVOS: características precalculadas de openWakeWord (Hugging Face, davidscripka/openwakeword_features):
  ``acav_parcial.bin`` (las primeras filas de ACAV100M: habla en muchos idiomas, música y ruido) y
  ``validation_set_features.npy`` (~11 h de pláticas y música, solo para medir activaciones falsas).

Se entrena con numpy (sin PyTorch): una red de dos capas ocultas cabe de sobra. Al final se mide:
- detección con voces que el modelo nunca vio (clips completos, en vivo, como en la cocina);
- activaciones falsas por hora en las ~11 h de pláticas y música;
- y se elige el umbral más bajo que deja menos de ``--max-falsas`` por hora.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from voxa.audio.wakeword import CHUNK, WINDOW, Classifier, FeatureModels, StreamingFeatures  # noqa: E402

ACAV_HEADER = 128
ROW = WINDOW * 96


def load_acav(path: Path, limit: int | None) -> np.ndarray:
    rows = (path.stat().st_size - ACAV_HEADER) // (ROW * 2)
    rows = min(rows, limit or rows)
    return np.memmap(path, dtype=np.float16, mode="r", offset=ACAV_HEADER, shape=(rows, WINDOW, 96))


def sliding(features: np.ndarray) -> np.ndarray:
    """(n, 96) → (n-15, 16, 96) sin copiar."""
    return np.lib.stride_tricks.sliding_window_view(features, (WINDOW, 96))[:, 0]


class Mlp:
    def __init__(self, sizes: list[int], rng: np.random.Generator) -> None:
        self.w = [rng.normal(0, np.sqrt(2 / a), (a, b)).astype(np.float32) for a, b in zip(sizes, sizes[1:])]
        self.b = [np.zeros(b, np.float32) for b in sizes[1:]]
        self.m = [np.zeros_like(p) for p in self.w + self.b]
        self.v = [np.zeros_like(p) for p in self.w + self.b]
        self.t = 0

    def forward(self, x: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
        acts = [x]
        h = x
        for i, (w, b) in enumerate(zip(self.w, self.b)):
            h = h @ w + b
            if i < len(self.w) - 1:
                h = np.maximum(h, 0)
            acts.append(h)
        return h[:, 0], acts

    def step(self, x: np.ndarray, y: np.ndarray, weight: np.ndarray, lr: float, l2: float) -> float:
        logits, acts = self.forward(x)
        p = 1 / (1 + np.exp(-np.clip(logits, -30, 30)))
        loss = -np.sum(weight * (y * np.log(p + 1e-7) + (1 - y) * np.log(1 - p + 1e-7))) / weight.sum()
        grad = ((p - y) * weight / weight.sum())[:, None].astype(np.float32)
        grads_w, grads_b = [], []
        for i in range(len(self.w) - 1, -1, -1):
            grads_w.insert(0, acts[i].T @ grad + l2 * self.w[i])
            grads_b.insert(0, grad.sum(0))
            if i:
                grad = (grad @ self.w[i].T) * (acts[i] > 0)
        self.t += 1
        for k, (param, g) in enumerate(zip(self.w + self.b, grads_w + grads_b)):
            self.m[k] = 0.9 * self.m[k] + 0.1 * g
            self.v[k] = 0.999 * self.v[k] + 0.001 * g * g
            m_hat = self.m[k] / (1 - 0.9**self.t)
            v_hat = self.v[k] / (1 - 0.999**self.t)
            param -= lr * m_hat / (np.sqrt(v_hat) + 1e-8)
        return float(loss)

    def classifier(self) -> Classifier:
        return Classifier([w.copy() for w in self.w], [b.copy() for b in self.b])


def predict(clf: Classifier, x: np.ndarray, batch: int = 65536) -> np.ndarray:
    return np.concatenate([clf.predict(np.asarray(x[i : i + batch], np.float32)) for i in range(0, len(x), batch)])


def activations(scores: np.ndarray, threshold: float, patience: int = 2, refractory: int = 25) -> int:
    """Cuenta activaciones como lo haría ``WakeWordDetector`` sobre una secuencia continua."""
    count = streak = cooldown = 0
    for s in scores:
        cooldown = max(cooldown - 1, 0)
        streak = streak + 1 if s >= threshold else 0
        if streak >= patience and not cooldown:
            count, streak, cooldown = count + 1, 0, refractory
    return count


def streaming_hits(clf: Classifier, models: FeatureModels, clips: list[np.ndarray], threshold: float) -> float:
    """Fracción de clips en que el detector, en vivo, se dispara (con dos bloques seguidos)."""
    hits = 0
    for audio in clips:
        stream = StreamingFeatures(models)
        streak, fired = 0, False
        padded = np.concatenate([audio, np.zeros(CHUNK * 3, np.int16)])  # un poco de silencio después
        for i in range(0, len(padded) - CHUNK + 1, CHUNK):
            if stream.feed(padded[i : i + CHUNK]) and stream.ready:
                score = clf.predict(stream.window()[None])[0]
                streak = streak + 1 if score >= threshold else 0
                fired |= streak >= 2
        hits += fired
    return hits / max(len(clips), 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datos", type=Path, required=True)
    parser.add_argument("--negativos", type=Path, required=True)
    parser.add_argument("--modelos", type=Path, required=True)
    parser.add_argument("--salida", type=Path, default=Path("src/voxa/audio/hey_voxa.npz"))
    parser.add_argument("--pasos", type=int, default=24000)
    parser.add_argument("--capas", default="128,64")
    parser.add_argument("--acav", type=int, default=None, help="máximo de filas de ACAV100M a usar")
    parser.add_argument("--max-falsas", type=float, default=0.2, help="activaciones falsas por hora en la validación")
    parser.add_argument("--semilla", type=int, default=3)
    args = parser.parse_args()
    rng = np.random.default_rng(args.semilla)
    d = args.datos

    pos = np.load(d / "pos_entrenamiento.npy")
    hard = np.concatenate([np.load(d / "parcial_entrenamiento.npy"), np.load(d / "neg_entrenamiento.npy")])
    acav = load_acav(args.negativos / "acav_parcial.bin", args.acav)
    print(f"Positivos {len(pos)} · negativos difíciles {len(hard)} · ACAV {len(acav)} filas")
    acav = np.asarray(acav)  # a memoria (float16): el muestreo aleatorio sobre disco sería lentísimo

    val = np.load(args.negativos / "validation_set_features.npy", mmap_mode="r")
    val_windows = sliding(np.asarray(val, np.float32))
    val_hours = len(val) * CHUNK / 16000 / 3600
    pos_test = np.load(d / "pos_prueba.npy")
    neg_test = np.concatenate([np.load(d / "neg_prueba.npy"), np.load(d / "parcial_prueba.npy")])

    sizes = [WINDOW * 96, *[int(s) for s in args.capas.split(",")], 1]
    net = Mlp(sizes, rng)
    n_pos, n_hard, n_acav = 256, 512, 3072
    started = time.time()
    best = None
    for step in range(1, args.pasos + 1):
        x = np.concatenate([
            pos[rng.integers(0, len(pos), n_pos)],
            hard[rng.integers(0, len(hard), n_hard)],
            acav[rng.integers(0, len(acav), n_acav)],
        ]).reshape(n_pos + n_hard + n_acav, -1).astype(np.float32)
        y = np.concatenate([np.ones(n_pos), np.zeros(n_hard + n_acav)]).astype(np.float32)
        # Los negativos pesan cada vez más: primero aprende a reconocer, luego a no equivocarse.
        neg_weight = 1 + 9 * min(1.0, step / (args.pasos * 0.6))
        weight = np.concatenate([np.full(n_pos, 4.0), np.full(n_hard + n_acav, neg_weight)]).astype(np.float32)
        lr = 1e-3 * (0.1 ** (step / args.pasos))
        loss = net.step(x, y, weight, lr, l2=1e-5)
        if step % 2000 == 0 or step == args.pasos:
            clf = net.classifier()
            recall = float((predict(clf, pos_test) >= 0.5).mean())
            fp = float((predict(clf, neg_test) >= 0.5).mean())
            val_scores = predict(clf, val_windows)
            fa = activations(val_scores, 0.5) / val_hours
            print(f"paso {step:6d} · pérdida {loss:.4f} · detección {recall:.3f} · falsos (voces) {fp:.4f} "
                  f"· falsas/h {fa:.2f} · {time.time() - started:.0f} s", flush=True)
            if step >= args.pasos * 0.5 and (best is None or recall - fa / 10 > best[0]):
                best = (recall - fa / 10, step, clf)

    _, step, clf = best
    print(f"\nMejor punto: paso {step}")
    val_scores = predict(clf, val_windows)
    pos_scores = predict(clf, pos_test)
    print("umbral · detección (prueba) · falsas/h (11 h de pláticas y música)")
    chosen = None
    for threshold in np.arange(0.3, 0.96, 0.05):
        fa = activations(val_scores, threshold) / val_hours
        recall = float((pos_scores >= threshold).mean())
        print(f"  {threshold:.2f} · {recall:.3f} · {fa:.2f}")
        if chosen is None and fa <= args.max_falsas:
            chosen = float(round(threshold, 2))
    chosen = chosen or 0.9

    audio = np.load(d / "audio_prueba.npz")
    models = FeatureModels(args.modelos)
    pos_clips = [audio[k] for k in audio.files if k.startswith("pos_")][:600]
    neg_clips = [audio[k] for k in audio.files if k.startswith("neg_")][:600]
    live_recall = streaming_hits(clf, models, pos_clips, chosen)
    live_fp = streaming_hits(clf, models, neg_clips, chosen)
    print(f"\nEn vivo con umbral {chosen}: detecta {live_recall:.1%} de {len(pos_clips)} «Hey Voxa» de voces nuevas; "
          f"se dispara en {live_fp:.1%} de {len(neg_clips)} frases que no lo son.")
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    clf.save(args.salida, threshold=chosen, live_recall=live_recall, false_per_hour=activations(val_scores, chosen) / val_hours)
    print(f"Guardado {args.salida} (umbral recomendado {chosen})")


if __name__ == "__main__":
    main()
