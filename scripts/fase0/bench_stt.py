#!/usr/bin/env python3
"""VOXA — Fase 0: benchmark de reconocimiento de voz (STT) en español.

Compara Vosk y faster-whisper sobre las frases grabadas con grabar_pruebas.sh
(frase_NN.wav + frase_NN.txt). Cada motor corre en un proceso aparte para
medir su RAM pico sin mezclarla con la de los demás.

Instalación de los motores (en un entorno virtual o con pipx/uv):
    pip install vosk            # + modelo español: https://alphacephei.com/vosk/models
    pip install faster-whisper  # descarga los modelos la primera vez

Uso:
    python3 scripts/fase0/bench_stt.py --vosk-model ~/modelos/vosk-model-small-es-0.42
    python3 scripts/fase0/bench_stt.py --whisper-sizes tiny,base
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import unicodedata
import wave
from pathlib import Path

FASE0_DIR = Path.home() / "voxa-fase0"

# ---------- Normalización y WER ----------

_UNIDADES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
             "diez", "once", "doce", "trece", "catorce", "quince", "dieciseis", "diecisiete",
             "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidos", "veintitres",
             "veinticuatro", "veinticinco", "veintiseis", "veintisiete", "veintiocho", "veintinueve"]
_DECENAS = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta",
            8: "ochenta", 9: "noventa"}


def numero_a_palabras(n: int) -> str:
    """0–100 en palabras (sin acentos), suficiente para temporizadores y volumen."""
    if n < 30:
        return _UNIDADES[n]
    if n == 100:
        return "cien"
    decena, unidad = divmod(n, 10)
    return _DECENAS[decena] + ("" if unidad == 0 else f" y {_UNIDADES[unidad]}")


def normalizar(texto: str) -> list[str]:
    """Minúsculas, sin acentos ni puntuación, y números escritos como palabras.

    Así «10 minutos» y «diez minutos» cuentan igual: el STT no se castiga por el formato.
    """
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    palabras: list[str] = []
    for token in texto.split():
        if token.isdigit() and int(token) <= 100:
            palabras.extend(numero_a_palabras(int(token)).split())
        else:
            palabras.append(token)
    return palabras


def distancia_edicion(ref: list[str], hip: list[str]) -> int:
    previa = list(range(len(hip) + 1))
    for i, r in enumerate(ref, 1):
        actual = [i]
        for j, h in enumerate(hip, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (r != h)))
        previa = actual
    return previa[-1]


# ---------- Motores (se ejecutan en un proceso hijo) ----------

def duracion_wav(ruta: Path) -> float:
    with wave.open(str(ruta), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def ram_pico_mb() -> float | None:
    try:
        import resource  # solo existe en Unix
    except ImportError:
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KB


def correr_vosk(modelo: str, audios: list[Path]) -> dict:
    from vosk import KaldiRecognizer, Model, SetLogLevel

    SetLogLevel(-1)
    t0 = time.perf_counter()
    model = Model(modelo)
    carga = time.perf_counter() - t0
    resultados = []
    for ruta in audios:
        t0 = time.perf_counter()
        with wave.open(str(ruta), "rb") as w:
            rec = KaldiRecognizer(model, w.getframerate())
            while True:
                datos = w.readframes(4000)
                if not datos:
                    break
                rec.AcceptWaveform(datos)
        texto = json.loads(rec.FinalResult()).get("text", "")
        resultados.append({"audio": ruta.name, "texto": texto, "segundos": time.perf_counter() - t0})
    return {"carga": carga, "resultados": resultados}


def correr_whisper(tamano: str, audios: list[Path], beam: int) -> dict:
    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    model = WhisperModel(tamano, device="cpu", compute_type="int8")
    carga = time.perf_counter() - t0
    resultados = []
    for ruta in audios:
        t0 = time.perf_counter()
        segmentos, _ = model.transcribe(str(ruta), language="es", beam_size=beam)
        texto = " ".join(s.text.strip() for s in segmentos)  # el generador transcribe al iterar
        resultados.append({"audio": ruta.name, "texto": texto, "segundos": time.perf_counter() - t0})
    return {"carga": carga, "resultados": resultados}


def modo_hijo(args: argparse.Namespace) -> None:
    audios = [Path(p) for p in json.loads(args.hijo_audios)]
    if args.hijo == "vosk":
        salida = correr_vosk(args.vosk_model, audios)
    else:
        salida = correr_whisper(args.hijo.split(":", 1)[1], audios, args.beam)
    salida["ram_mb"] = ram_pico_mb()
    print(json.dumps(salida))


# ---------- Orquestación ----------

def motor_disponible(modulo: str) -> bool:
    try:
        __import__(modulo)
        return True
    except ImportError:
        return False


def ejecutar_motor(nombre: str, audios: list[Path], args: argparse.Namespace) -> dict | None:
    cmd = [sys.executable, __file__, "--hijo", nombre, "--hijo-audios", json.dumps([str(a) for a in audios]),
           "--beam", str(args.beam)]
    if args.vosk_model:
        cmd += ["--vosk-model", args.vosk_model]
    print(f"→ {nombre} …", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  ❌ {nombre} falló:\n{proc.stderr.strip()[-1500:]}")
        return None
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark de STT en español para VOXA (Fase 0).")
    parser.add_argument("--audio-dir", default=str(FASE0_DIR / "audio"),
                        help="carpeta con frase_NN.wav y frase_NN.txt (por defecto ~/voxa-fase0/audio)")
    parser.add_argument("--vosk-model", default=None,
                        help="carpeta del modelo Vosk en español (p. ej. vosk-model-small-es-*)")
    parser.add_argument("--whisper-sizes", default="tiny,base,small",
                        help="tamaños de faster-whisper separados por coma (por defecto tiny,base,small)")
    parser.add_argument("--beam", type=int, default=5, help="beam size de whisper (1 = más rápido)")
    parser.add_argument("--salida", default=str(FASE0_DIR / "bench_stt.md"))
    parser.add_argument("--hijo", help=argparse.SUPPRESS)
    parser.add_argument("--hijo-audios", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.hijo:
        modo_hijo(args)
        return

    audio_dir = Path(args.audio_dir).expanduser()
    pares = sorted((wav, wav.with_suffix(".txt")) for wav in audio_dir.glob("frase_*.wav")
                   if wav.with_suffix(".txt").exists())
    if not pares:
        sys.exit(f"No hay frases en {audio_dir}. Graba primero: bash scripts/fase0/grabar_pruebas.sh frases")
    audios = [wav for wav, _ in pares]
    referencias = {wav.name: txt.read_text(encoding="utf-8").strip() for wav, txt in pares}
    duracion_total = sum(duracion_wav(w) for w in audios)
    print(f"{len(audios)} frases · {duracion_total:.1f} s de audio\n")

    motores: list[str] = []
    if args.vosk_model:
        if motor_disponible("vosk"):
            motores.append("vosk")
        else:
            print("⚠️  Vosk no está instalado: pip install vosk")
    else:
        print("ℹ️  Sin --vosk-model: se omite Vosk. Descarga el modelo español pequeño de "
              "https://alphacephei.com/vosk/models y pasa su carpeta.")
    if motor_disponible("faster_whisper"):
        motores += [f"whisper:{t.strip()}" for t in args.whisper_sizes.split(",") if t.strip()]
    else:
        print("⚠️  faster-whisper no está instalado: pip install faster-whisper")
    if not motores:
        sys.exit("No hay motores disponibles.")

    filas, detalles = [], []
    for motor in motores:
        salida = ejecutar_motor(motor, audios, args)
        if salida is None:
            continue
        errores = palabras = 0
        tiempo = 0.0
        for r in salida["resultados"]:
            ref, hip = normalizar(referencias[r["audio"]]), normalizar(r["texto"])
            errores += distancia_edicion(ref, hip)
            palabras += len(ref)
            tiempo += r["segundos"]
            detalles.append((motor, r["audio"], referencias[r["audio"]], r["texto"], r["segundos"]))
        filas.append({
            "motor": motor,
            "wer": errores / max(palabras, 1),
            "carga": salida["carga"],
            "tiempo": tiempo,
            "medio": tiempo / len(salida["resultados"]),
            "rtf": tiempo / duracion_total,
            "ram": salida.get("ram_mb"),
        })

    encabezado = "| Motor | WER | Carga (s) | Total (s) | Por frase (s) | RTF | RAM pico (MB) |"
    separador = "|---|---|---|---|---|---|---|"
    lineas = [encabezado, separador]
    for f in sorted(filas, key=lambda f: f["wer"]):
        ram = f"{f['ram']:.0f}" if f["ram"] is not None else "—"
        lineas.append(f"| {f['motor']} | {f['wer']:.1%} | {f['carga']:.1f} | {f['tiempo']:.1f} | "
                      f"{f['medio']:.2f} | {f['rtf']:.2f} | {ram} |")
    tabla = "\n".join(lineas)
    print("\n" + tabla)
    print("\nWER: menor es mejor (objetivo ≤ 10 % en comandos). RTF < 1 = más rápido que tiempo real.")

    md = [
        "# VOXA — Benchmark de STT (Fase 0)",
        "",
        f"- Fecha: {time.strftime('%Y-%m-%d %H:%M')}",
        f"- Frases: {len(audios)} · audio total: {duracion_total:.1f} s · beam whisper: {args.beam}",
        "",
        tabla,
        "",
        "WER normaliza mayúsculas, acentos, puntuación y números (10 = diez).",
        "",
        "## Detalle por frase",
        "",
        "| Motor | Audio | Referencia | Transcripción | s |",
        "|---|---|---|---|---|",
    ]
    for motor, audio, ref, hip, seg in detalles:
        hip_md = hip.replace("|", "/") or "∅"
        md.append(f"| {motor} | {audio} | {ref} | {hip_md} | {seg:.2f} |")
    salida_md = Path(args.salida).expanduser()
    salida_md.parent.mkdir(parents=True, exist_ok=True)
    salida_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nInforme: {salida_md}")


if __name__ == "__main__":
    main()
