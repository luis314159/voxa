"""Genera los datos para entrenar «Hey Voxa»: miles de voces sintéticas diciéndolo y lo que no es.

    python scripts/hey_voxa/generar.py --voces VOCES --modelos MODELOS --salida DATOS [--procesos 12]

- VOCES: carpeta con voces de Piper (.onnx + .onnx.json). Las de varios hablantes (LibriTTS-R,
  VCTK, L2-ARCTIC) dan la variedad; las de español, el acento de la casa.
- MODELOS: melspectrogram.onnx y embedding_model.onnx (los mismos que usa VOXA).

Cada «Hey Voxa» se arma como en la cocina: con algo antes (silencio, ruido o alguien hablando),
a veces seguido de la orden, con eco de cuarto, ruido (extractor, agua, plática, música) y a
distintos volúmenes. Se guardan solo los resúmenes de 16×96 que ve el clasificador.

Las voces de prueba (``TEST_VOICES``) nunca se usan para entrenar: miden qué tan bien se
generaliza a voces que el modelo no conoce.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from voxa.audio.clip import resample  # noqa: E402
from voxa.audio.wakeword import WINDOW, FeatureModels  # noqa: E402

RATE = 16000
CLIP_SECONDS = 2.6  # alcanza para 16 resúmenes (1.28 s + la ventana de 0.78 s) con margen

POSITIVE = {
    "es": ["hey voxa", "hey, voxa", "oye voxa", "oye, voxa", "ey voxa", "¡hey voxa!", "oye, voxa,", "hey voxa,"],
    "en": ["hey voxa", "hey, voxa", "hey voxa!", "hey vocsa", "hey voksa", "hey, voxa,"],
}
# Lo que se dice después de «Hey Voxa» (a veces se pega sin pausa).
FOLLOW = {
    "es": ["pon música", "qué hora es", "pausa", "súbele", "temporizador de diez minutos", "pon a Juan Gabriel"],
    "en": ["play some music", "what time is it", "stop", "set a timer"],
}
# Parecidos que NO deben activarla.
CONFUSABLE = {
    "es": [
        "oye", "hey", "oye tú", "oye, ¿qué tal?", "oye Rosa", "hey, boca", "oye, la bolsa", "oye, toca", "hay boxeo",
        "ey, baja", "oye, ¿y la sopa?", "la voz", "boca", "Oaxaca", "taxi", "Roxana", "Alexa", "oye Siri",
        "oye Google", "oye mamá", "hey papá", "oye Sofía", "foca", "vaca", "oye, bocina", "hay que ir", "ok",
        "oye, ¿ya está?", "hey, mira", "oye, vosotros", "boxer", "oye, voy", "hey, vamos", "oye, baja la voz",
        "hay mucha sal", "ay, no sé", "oye Vicky", "oye Vero", "hey Bocha", "oye, Vanesa", "toxina", "Oxxo",
        "el boxeador", "la caja", "oye, ¿y el arroz?", "oye, Lupita", "hey, Dora", "oye Moisés", "oye, Óscar",
    ],
    "en": [
        "hey", "hey there", "Alexa", "hey Siri", "okay Google", "box", "hey boss", "hey Rosa", "Oaxaca",
        "hey, look", "hey Jarvis", "the vodka", "hey Vicky", "hey, Mocha", "hey Max", "a box of socks", "hey Sasha",
        "hey, wait", "hey Jackson", "the volcano", "hey, buddy", "hey Lexa", "hey, folks",
    ],
}
SENTENCES = {
    "es": [
        "Pon un temporizador de diez minutos para el arroz.", "¿Cuánto le falta al arroz?", "Súbele a la música.",
        "¿Qué hora es?", "¿Va a llover hoy?", "Pásame la sal, por favor.", "Ya está la comida, vengan a comer.",
        "¿Dónde dejaste las llaves?", "Hoy hace mucho calor en la cocina.", "Mañana vamos al mercado temprano.",
        "¿Quién quiere más tortillas?", "No le eches tanto chile.", "Apaga la estufa cuando hierva.",
        "Mi mamá hace el mejor pozole del mundo.", "¿Ya hiciste la tarea?", "Hay que comprar leche y huevos.",
        "La reunión es a las cinco de la tarde.", "Ponle tantito limón a la sopa.", "¿Me ayudas a poner la mesa?",
        "Ese video de recetas estuvo muy bueno.", "El perro se comió el pan otra vez.", "Cierra la puerta, que hace frío.",
        "¿Viste el partido de anoche?", "Voy a lavar los trastes.", "Hay que sacar la basura esta noche.",
        "Los frijoles ya están listos.", "¿Le pusiste sal al agua?", "Me encanta esta canción.",
        "Mañana es el cumpleaños de la abuela.", "Prende el horno a ciento ochenta grados.",
        "Bájale tantito al volumen.", "¿Qué vamos a cenar hoy?", "El café está muy caliente.",
        "Pon la canción de Vicente Fernández.", "Oye, ¿y si pedimos pizza?", "Hey, ¿cómo te fue en la escuela?",
        "Ay, se me quemó la cebolla.", "Ahorita voy, espérame tantito.", "La boca me sabe a chocolate.",
        "Tenemos que llevar el coche al taller.", "¿Cuántos huevos lleva el pastel?", "Ya llegó tu hermano.",
    ],
    "en": [
        "Turn on the oven, please.", "What are we having for dinner?", "Can you pass me the salt?",
        "The meeting starts at five.", "I love this song so much.", "Put the box on the table.",
        "Hey, can you help me with the dishes?", "It's going to rain tomorrow.", "The coffee is still hot.",
        "Did you feed the dog?", "We need milk, eggs and bread.", "Let's watch a movie tonight.",
        "I'll be there in five minutes.", "The kids are playing outside.", "Close the window, it's cold.",
    ],
}
# Voces que nunca se usan para entrenar (para medir con voces desconocidas).
TEST_VOICES = {"es_AR-daniela-high", "es_MX-ald-x_low", "en_US-arctic-medium"}
TEST_SPEAKER_FROM = {"en_US-libritts_r-medium": 820, "en_GB-vctk-medium": 100, "en_US-l2arctic-medium": 21, "es_ES-sharvard-medium": 1}


@dataclass(frozen=True)
class Voice:
    name: str
    path: Path
    speakers: int
    language: str

    def split(self, speaker: int) -> str:
        if self.name in TEST_VOICES:
            return "prueba"
        start = TEST_SPEAKER_FROM.get(self.name)
        return "prueba" if start is not None and speaker >= start else "entrenamiento"


def find_voices(folder: Path) -> list[Voice]:
    voices = []
    for path in sorted(folder.glob("*.onnx")):
        config = json.loads(Path(f"{path}.json").read_text(encoding="utf-8"))
        language = config.get("language", {}).get("family") or path.name[:2]
        voices.append(Voice(path.stem, path, int(config.get("num_speakers", 1)), "es" if language == "es" else "en"))
    return voices


# --- trabajo en cada proceso ---------------------------------------------------------------
_voices: dict[str, object] = {}
_features: FeatureModels | None = None


def _init(models: str) -> None:
    """Un hilo por proceso: con todos los núcleos ocupados, los hilos extra de ONNX solo estorban."""
    import onnxruntime as ort

    original = ort.InferenceSession

    def single_thread(path, sess_options=None, *args, **kwargs):
        sess_options = sess_options or ort.SessionOptions()
        sess_options.intra_op_num_threads = 1
        sess_options.inter_op_num_threads = 1
        sess_options.enable_cpu_mem_arena = False  # 14 procesos × 13 voces no caben en memoria con la arena
        return original(path, sess_options, *args, **kwargs)

    ort.InferenceSession = single_thread
    global _features
    _features = FeatureModels(Path(models))


def synthesize(voice: Voice, text: str, speaker: int, rng: np.random.Generator) -> np.ndarray:
    from piper import PiperVoice, SynthesisConfig

    if voice.name not in _voices:
        while len(_voices) >= 2:  # las tareas llegan agrupadas por voz: basta con dos cargadas
            _voices.pop(next(iter(_voices)))
        _voices[voice.name] = PiperVoice.load(voice.path)
    piper_voice = _voices[voice.name]
    config = SynthesisConfig(
        speaker_id=speaker if voice.speakers > 1 else None,
        length_scale=float(rng.uniform(0.75, 1.3)),
        noise_scale=float(rng.uniform(0.4, 1.0)),
        noise_w_scale=float(rng.uniform(0.5, 1.1)),
    )
    chunks = list(piper_voice.synthesize(text, config))
    if not chunks:
        return np.zeros(0, np.float32)
    rate = chunks[0].sample_rate
    audio = np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32)
    return resample(audio, rate, RATE) if rate != RATE else audio


def trim(audio: np.ndarray, threshold: float = 0.02) -> np.ndarray:
    loud = np.flatnonzero(np.abs(audio) > threshold * max(np.abs(audio).max(), 1e-6))
    return audio[max(loud[0] - 400, 0) : loud[-1] + 800] if len(loud) else audio


# --- aumentos: cómo suena de verdad en una cocina ----------------------------------------------
def colored_noise(n: int, rng: np.random.Generator, exponent: float) -> np.ndarray:
    """0 = blanco (agua), 1 = rosa, 2 = café (extractor, refri)."""
    spectrum = np.fft.rfft(rng.normal(size=n))
    freqs = np.maximum(np.fft.rfftfreq(n), 1.0 / n)
    noise = np.fft.irfft(spectrum / freqs ** (exponent / 2), n)
    return noise / (np.abs(noise).max() + 1e-9)


def synthetic_music(n: int, rng: np.random.Generator) -> np.ndarray:
    """Acordes con armónicos y una batería de ruido: no es música real, pero ocupa el espectro igual."""
    out = np.zeros(n, np.float32)
    t = np.arange(n) / RATE
    beat = int(RATE * rng.uniform(0.25, 0.6))
    for start in range(0, n, beat * 2):
        root = 110 * 2 ** (rng.integers(0, 24) / 12)
        seg = slice(start, min(start + beat * 2, n))
        for interval in (0, 4, 7, 12)[: rng.integers(2, 5)]:
            f = root * 2 ** (interval / 12)
            for h in range(1, 5):
                out[seg] += np.sin(2 * np.pi * f * h * t[seg]) / h**1.5
    for start in range(0, n, beat):
        k = min(int(0.05 * RATE), n - start)
        out[start : start + k] += rng.normal(size=k) * np.exp(-np.arange(k) / (0.01 * RATE)) * 2
    return out / (np.abs(out).max() + 1e-9)


def reverb(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    rt60 = rng.uniform(0.15, 0.7)
    n = int(RATE * rt60)
    ir = rng.normal(size=n) * np.exp(-6.9 * np.arange(n) / n)
    ir[0] = 1.0 / rng.uniform(0.2, 1.0)  # sonido directo: más fuerte cerca del micrófono
    size = len(audio) + n
    wet = np.fft.irfft(np.fft.rfft(audio, size) * np.fft.rfft(ir, size), size)[: len(audio)]
    return wet / (np.abs(wet).max() + 1e-9) * np.abs(audio).max()


def equalize(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Micrófono barato: recorta graves o agudos."""
    spectrum = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(len(audio), 1 / RATE)
    low, high = rng.uniform(50, 300), rng.uniform(3500, 7900)
    gain = 1 / (1 + (low / np.maximum(freqs, 1)) ** 2) / (1 + (freqs / high) ** 4)
    return np.fft.irfft(spectrum * gain, len(audio)).astype(np.float32)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x**2)) + 1e-9)


def kitchen(audio: np.ndarray, rng: np.random.Generator, babble: list[np.ndarray]) -> np.ndarray:
    if rng.random() < 0.6:
        audio = reverb(audio, rng)
    if rng.random() < 0.4:
        audio = equalize(audio, rng)
    if rng.random() < 0.85:
        kind = rng.choice(["blanco", "rosa", "cafe", "musica", "platica"], p=[0.15, 0.2, 0.2, 0.25, 0.2])
        n = len(audio)
        if kind == "musica":
            noise = synthetic_music(n, rng)
        elif kind == "platica" and babble:
            noise = np.zeros(n, np.float32)
            for clip in rng.choice(len(babble), size=min(3, len(babble)), replace=False):
                b = np.resize(babble[clip], n)
                noise += np.roll(b, rng.integers(0, n))
        else:
            noise = colored_noise(n, rng, {"blanco": 0.0, "rosa": 1.0, "cafe": 2.0}.get(str(kind), 1.0))
        snr = rng.uniform(0, 30)
        audio = audio + noise * rms(audio) / rms(noise) / 10 ** (snr / 20)
    level = 10 ** (rng.uniform(-40, -12) / 20)  # de lejos y bajito a cerca y fuerte
    audio = audio / rms(audio) * level
    return np.clip(audio, -1, 1)


def to_int16(audio: np.ndarray) -> np.ndarray:
    return (np.clip(audio, -1, 1) * 32767).astype(np.int16)


def fit(audio: np.ndarray, n: int) -> np.ndarray:
    return audio[-n:] if len(audio) >= n else np.concatenate([np.zeros(n - len(audio), np.float32), audio])


# --- tareas -------------------------------------------------------------------------------------
def positive_task(args) -> dict:
    voice, speaker, seed = args
    rng = np.random.default_rng(seed)
    lang = voice.language
    wake = trim(synthesize(voice, str(rng.choice(POSITIVE[lang])), speaker, rng))
    n = int(CLIP_SECONDS * RATE)
    before = np.zeros(n, np.float32)
    if rng.random() < 0.5:  # alguien venía hablando
        speech = trim(synthesize(voice, str(rng.choice(SENTENCES[lang])), speaker, rng))
        before = fit(np.concatenate([before, speech, np.zeros(int(rng.uniform(0.1, 0.6) * RATE), np.float32)]), n)
    after = np.zeros(int(rng.uniform(0.0, 0.25) * RATE), np.float32)
    if rng.random() < 0.3:  # «Hey Voxa, pon música» de corrido: solo cabe el inicio de la orden
        follow = trim(synthesize(voice, str(rng.choice(FOLLOW[lang])), speaker, rng))
        after = np.concatenate([np.zeros(int(rng.uniform(0.0, 0.15) * RATE), np.float32), follow])[: len(after) + int(0.2 * RATE)]
    # El clip termina justo después de «Voxa» (y lo poco que siguió): ahí debe dispararse.
    audio = kitchen(np.concatenate([before, wake, after]), rng, [])
    pcm = to_int16(audio)
    windows = {"pos": [], "parcial": []}
    emb = _features.embed_clip(pcm)
    if len(emb) >= WINDOW:
        windows["pos"].append(emb[-WINDOW:])
    # Cortado a media frase (solo se oyó «Hey» o «Hey Vo-»): negativo difícil.
    cut = len(before) + int(len(wake) * rng.uniform(0.25, 0.55))
    emb = _features.embed_clip(pcm[:cut])
    if len(emb) >= WINDOW:
        windows["parcial"].append(emb[-WINDOW:])
    return {"split": voice.split(speaker), "audio": pcm if voice.split(speaker) == "prueba" else None, **windows}


def negative_task(args) -> dict:
    voice, speaker, seed = args
    rng = np.random.default_rng(seed)
    lang = voice.language
    pool = CONFUSABLE[lang] if rng.random() < 0.5 else SENTENCES[lang]
    texts = [str(t) for t in rng.choice(pool, size=int(rng.integers(1, 4)))]
    pieces = []
    for text in texts:
        pieces += [trim(synthesize(voice, text, speaker, rng)), np.zeros(int(rng.uniform(0.05, 0.5) * RATE), np.float32)]
    speech = np.concatenate([np.zeros(int(1.0 * RATE), np.float32), *pieces])
    audio = kitchen(speech, rng, [])
    emb = _features.embed_clip(to_int16(audio))
    windows = [emb[i - WINDOW : i] for i in range(WINDOW, len(emb) + 1, 2)]
    return {"split": voice.split(speaker), "neg": windows, "audio": to_int16(audio) if voice.split(speaker) == "prueba" else None}


def plan(voices: list[Voice], count: int, rng: np.random.Generator) -> list[tuple[Voice, int, int]]:
    """Reparte entre voces: la mitad a las de español (pocas pero importan) y la otra a las de muchos hablantes."""
    spanish = [v for v in voices if v.language == "es"]
    others = [v for v in voices if v.language != "es"]
    tasks = []
    for i in range(count):
        group = spanish if (i % 2 == 0 and spanish) or not others else others
        voice = group[int(rng.integers(len(group)))]
        tasks.append((voice, int(rng.integers(voice.speakers)), int(rng.integers(2**31))))
    return sorted(tasks, key=lambda task: task[0].name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--voces", type=Path, required=True)
    parser.add_argument("--modelos", type=Path, required=True)
    parser.add_argument("--salida", type=Path, required=True)
    parser.add_argument("--positivos", type=int, default=24000)
    parser.add_argument("--negativos", type=int, default=8000)
    parser.add_argument("--procesos", type=int, default=max(1, mp.cpu_count() - 2))
    parser.add_argument("--semilla", type=int, default=7)
    args = parser.parse_args()

    voices = find_voices(args.voces)
    print("Voces:", ", ".join(f"{v.name} ({v.speakers})" for v in voices))
    rng = np.random.default_rng(args.semilla)
    args.salida.mkdir(parents=True, exist_ok=True)
    out: dict[str, list] = {}
    test_audio: dict[str, list] = {"pos": [], "neg": []}
    started = time.time()
    with mp.Pool(args.procesos, initializer=_init, initargs=(str(args.modelos),)) as pool:
        for kind, task, tasks in (
            ("pos", positive_task, plan(voices, args.positivos, rng)),
            ("neg", negative_task, plan(voices, args.negativos, rng)),
        ):
            for n, result in enumerate(pool.imap_unordered(task, tasks, chunksize=8), 1):
                split = result["split"]
                for key in ("pos", "parcial", "neg"):
                    if result.get(key):
                        out.setdefault(f"{key}_{split}", []).extend(w.astype(np.float16) for w in result[key])
                if result["audio"] is not None and len(test_audio[kind]) < 1500:
                    test_audio[kind].append(result["audio"])
                if n % 1000 == 0:
                    print(f"  {kind}: {n}/{len(tasks)} ({time.time() - started:.0f} s)", flush=True)
    for key, windows in out.items():
        array = np.stack(windows).astype(np.float16)
        np.save(args.salida / f"{key}.npy", array)
        print(f"{key}: {array.shape}")
    np.savez_compressed(args.salida / "audio_prueba.npz", **{
        f"{kind}_{i}": a for kind, clips in test_audio.items() for i, a in enumerate(clips)
    })
    print(f"Listo en {time.time() - started:.0f} s → {args.salida}")


if __name__ == "__main__":
    main()
