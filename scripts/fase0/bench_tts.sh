#!/usr/bin/env bash
# VOXA — Fase 0: tiempo de síntesis de voz con Piper.
# Uso: bash scripts/fase0/bench_tts.sh /ruta/a/voz-es_MX.onnx

set -uo pipefail

MODELO="${1:-}"
SALIDA_DIR="$HOME/voxa-fase0/tts"

instrucciones() {
  cat <<'EOF'
Para instalar Piper:
  1. pipx install piper-tts          (si falta pipx: sudo apt install pipx && pipx ensurepath)
  2. Abre el catálogo oficial de voces de Piper:
       https://huggingface.co/rhasspy/piper-voices
     Entra a es → es_MX y elige una voz. Descarga DOS archivos de la misma voz:
       <voz>.onnx  y  <voz>.onnx.json   (en la misma carpeta, p. ej. ~/voxa-fase0/voces/)
     Si hay varias voces es_MX, prueba al menos dos y escoge la que le guste a la familia.
  3. Vuelve a correr:
       bash scripts/fase0/bench_tts.sh ~/voxa-fase0/voces/<voz>.onnx
EOF
}

if ! command -v piper >/dev/null 2>&1; then
  echo "Piper no está instalado."
  echo
  instrucciones
  exit 1
fi
if [[ -z "$MODELO" || ! -f "$MODELO" ]]; then
  echo "Indica la ruta al archivo .onnx de una voz en español."
  echo
  instrucciones
  exit 1
fi
if [[ ! -f "$MODELO.json" ]]; then
  echo "⚠️  Falta $MODELO.json junto al modelo (descárgalo del mismo lugar)."
  exit 1
fi

mkdir -p "$SALIDA_DIR"
FRASES=(
  "Listo."
  "Diez minutos para el arroz."
  "Poniendo Persiana americana, de Soda Stereo. Para pausar, di: Hey Voxa, pausa."
)

# Las versiones de Piper difieren en el nombre de la opción de salida; se prueban ambas.
sintetizar() {  # sintetizar <texto> <salida.wav>
  printf '%s\n' "$1" | piper --model "$MODELO" --output_file "$2" >/dev/null 2>&1 && return 0
  printf '%s\n' "$1" | piper -m "$MODELO" -f "$2" >/dev/null 2>&1
}

duracion() {  # segundos de audio de un WAV
  python3 - "$1" <<'PY'
import sys, wave
with wave.open(sys.argv[1], "rb") as w:
    print(f"{w.getnframes() / w.getframerate():.2f}")
PY
}

echo "Voz: $(basename "$MODELO")"
echo
printf '%-6s %-10s %-10s %-6s  %s\n' "Frase" "Síntesis" "Audio" "RTF" "Texto"
i=0
for frase in "${FRASES[@]}"; do
  i=$((i + 1))
  wav="$SALIDA_DIR/frase_$i.wav"
  inicio=$(date +%s%N)
  if ! sintetizar "$frase" "$wav"; then
    echo "❌ Piper falló. Revisa 'piper --help' y anota la versión instalada."
    exit 1
  fi
  fin=$(date +%s%N)
  sint=$(awk -v a="$inicio" -v b="$fin" 'BEGIN { printf "%.2f", (b - a) / 1e9 }')
  aud=$(duracion "$wav")
  rtf=$(awk -v s="$sint" -v a="$aud" 'BEGIN { printf "%.2f", (a > 0 ? s / a : 0) }')
  printf '%-6s %-10s %-10s %-6s  %s\n' "$i" "${sint} s" "${aud} s" "$rtf" "$frase"
done

echo
echo "Cada medición incluye cargar el modelo; VOXA lo mantendrá cargado, así que en uso real será más rápido."
echo "Objetivo: síntesis < 0.5 s para frases cortas (las frecuentes se guardarán en caché)."
echo "Escucha los WAV en $SALIDA_DIR (p. ej. con: pw-play $SALIDA_DIR/frase_3.wav)"
