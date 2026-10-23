#!/usr/bin/env bash
# VOXA — Fase 0: grabaciones de prueba con el micrófono de la PC.
# Uso: bash scripts/fase0/grabar_pruebas.sh [todo|ruido|wake|frases]
# Variables opcionales: SEG_WAKE (3), SEG_FRASE (6), SEG_RUIDO (10)

set -uo pipefail

SECCION="${1:-todo}"
SEG_WAKE="${SEG_WAKE:-3}"
SEG_FRASE="${SEG_FRASE:-6}"
SEG_RUIDO="${SEG_RUIDO:-10}"

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRASES="$AQUI/frases_stt.txt"
AUDIO_DIR="$HOME/voxa-fase0/audio"

tiene() { command -v "$1" >/dev/null 2>&1; }

if tiene pw-record; then
  GRABADOR="pw-record"
elif tiene arecord; then
  GRABADOR="arecord"
else
  echo "No encontré pw-record ni arecord. Instala pipewire-bin o alsa-utils." >&2
  exit 1
fi

grabar() {  # grabar <segundos> <archivo.wav>  → 16 kHz, mono, 16 bits
  local seg="$1" archivo="$2"
  if [[ "$GRABADOR" == "pw-record" ]]; then
    # pw-record graba hasta recibir una señal; SIGINT cierra el WAV correctamente.
    timeout --signal=INT "$seg" pw-record --rate 16000 --channels 1 --format s16 "$archivo" 2>/dev/null
  else
    arecord -q -f S16_LE -r 16000 -c 1 -d "$seg" "$archivo"
  fi
  # timeout devuelve 124 al cortar la grabación; eso es lo esperado.
  if [[ ! -s "$archivo" ]] || (( $(stat -c %s "$archivo") <= 44 )); then
    echo "   ⚠️  La grabación quedó vacía: revisa el micrófono predeterminado (wpctl status)."
    return 1
  fi
  return 0
}

cuenta() {  # cuenta regresiva corta antes de grabar
  printf '   3… '; sleep 1; printf '2… '; sleep 1; printf '1… '; sleep 1; echo "🎙️  ¡habla!"
}

# Lee de la terminal, no de stdin: en grabar_frases stdin es el archivo de frases.
pausa() { read -r -p "$1" _ </dev/tty; }

# ---------- Consentimiento ----------
cat <<EOF

VOXA · grabaciones de prueba (Fase 0)
=====================================
Se grabará audio del micrófono SOLO mientras este script lo indique.
Los archivos se guardan en:  $AUDIO_DIR
No se envían a ningún lado. Sirven para medir el micrófono, el wake word y el STT.
Pide permiso a cada persona que grabe su voz.
Para borrar todo cuando terminen:  rm -r ~/voxa-fase0/audio

Grabador: $GRABADOR · 16 kHz mono
EOF
read -r -p "¿Continuar? [s/N] " RESP
[[ "$RESP" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }

mkdir -p "$AUDIO_DIR"
echo "Micrófono predeterminado: $(pactl get-default-source 2>/dev/null || echo 'desconocido')"

# ---------- Ruido de fondo ----------
grabar_ruido() {
  echo
  echo "== Ruido de fondo =="
  pausa "Deja la cocina en condiciones normales, SIN música, y pulsa Enter (se graban $SEG_RUIDO s en silencio)… "
  grabar "$SEG_RUIDO" "$AUDIO_DIR/ruido_silencio.wav" && echo "   ✅ ruido_silencio.wav"
  pausa "Ahora pon música en la bocina Bluetooth a volumen normal (~60 %) y pulsa Enter… "
  grabar "$SEG_RUIDO" "$AUDIO_DIR/ruido_musica.wav" && echo "   ✅ ruido_musica.wav"
}

# ---------- «Hey Voxa» ----------
grabar_wake() {
  local condicion distancia i archivo
  echo
  echo "== «Hey Voxa» =="
  echo "Se graba 5 veces a 1, 2 y 3 metros del equipo; primero sin música y luego con música."
  for condicion in silencio musica; do
    if [[ "$condicion" == "silencio" ]]; then
      pausa "Apaga la música y pulsa Enter… "
    else
      pausa "Pon música en la bocina Bluetooth (~60 %) y pulsa Enter… "
    fi
    for distancia in 1 2 3; do
      pausa "Colócate a ${distancia} m del equipo y pulsa Enter… "
      for i in 1 2 3 4 5; do
        archivo="$AUDIO_DIR/wake_${condicion}_${distancia}m_$(printf '%02d' "$i").wav"
        echo " [$condicion · ${distancia} m · $i/5] Di «Hey Voxa» con voz normal."
        cuenta
        grabar "$SEG_WAKE" "$archivo" && echo "   ✅ $(basename "$archivo")"
        sleep 1
      done
    done
  done
}

# ---------- Frases para STT ----------
grabar_frases() {
  local idx=0 frase base resp
  if [[ ! -r "$FRASES" ]]; then
    echo "No encontré $FRASES" >&2
    return 1
  fi
  echo
  echo "== Frases para el benchmark de STT =="
  echo "Apaga la música. Habla a ~2 m, como lo harías normalmente en la cocina."
  echo "Cada grabación dura $SEG_FRASE s. Después puedes repetirla."
  while IFS= read -r frase || [[ -n "$frase" ]]; do
    [[ -z "${frase// /}" ]] && continue
    idx=$((idx + 1))
    base="$AUDIO_DIR/frase_$(printf '%02d' "$idx")"
    printf '%s\n' "$frase" >"$base.txt"
    while true; do
      echo
      echo " Frase $idx: «$frase»"
      pausa "   Pulsa Enter y dila… "
      grabar "$SEG_FRASE" "$base.wav" && echo "   ✅ $(basename "$base").wav"
      read -r -p "   Enter = siguiente · r = repetir: " resp </dev/tty
      [[ "$resp" == "r" || "$resp" == "R" ]] || break
    done
  done <"$FRASES"
}

case "$SECCION" in
  todo) grabar_ruido; grabar_wake; grabar_frases ;;
  ruido) grabar_ruido ;;
  wake) grabar_wake ;;
  frases) grabar_frases ;;
  *) echo "Sección desconocida: $SECCION (usa todo, ruido, wake o frases)" >&2; exit 2 ;;
esac

echo
echo "Listo. Archivos en $AUDIO_DIR ($(find "$AUDIO_DIR" -name '*.wav' | wc -l) WAV)."
echo "Siguiente paso: python3 scripts/fase0/bench_stt.py"
echo "Recuerda: los audios NO se comparten. Para borrarlos: rm -r ~/voxa-fase0/audio"
