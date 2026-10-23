#!/usr/bin/env bash
# VOXA — Fase 0: diagnóstico del equipo.
# Solo lee información; no instala ni cambia nada.
# Uso: bash scripts/fase0/diagnostico.sh

set -uo pipefail  # sin -e: un chequeo fallido no debe abortar el resto

SALIDA_DIR="$HOME/voxa-fase0"
FECHA="$(date +%Y-%m-%d_%H%M)"
INFORME="$SALIDA_DIR/informe-$FECHA.md"
mkdir -p "$SALIDA_DIR"

RESUMEN=()   # filas de la tabla: "estado|chequeo|detalle"

tiene() { command -v "$1" >/dev/null 2>&1; }

marca() {  # marca <✅|⚠️|❌> <chequeo> <detalle>
  RESUMEN+=("$1|$2|$3")
}

seccion() {  # seccion <título>  (lee el contenido de stdin)
  {
    echo
    echo "## $1"
    echo
    echo '```text'
    cat
    echo '```'
  } >>"$INFORME"
}

ejecutar() {  # ejecutar <comando...>: salida o aviso si no existe / falla
  if ! tiene "$1"; then
    echo "(no instalado: $1)"
    return 0
  fi
  "$@" 2>&1 || echo "(el comando terminó con error: $*)"
}

echo "VOXA · diagnóstico de Fase 0"
echo "Generando informe en $INFORME ..."

{
  echo "# VOXA — Informe de diagnóstico (Fase 0)"
  echo
  echo "- Fecha: $(date '+%Y-%m-%d %H:%M')"
  echo "- Equipo: $(hostname 2>/dev/null || echo desconocido)"
} >"$INFORME"

# ---------- Sistema ----------
ARCH="$(uname -m)"
if [[ "$ARCH" == "x86_64" ]]; then
  marca "✅" "Arquitectura" "$ARCH"
else
  marca "❌" "Arquitectura" "$ARCH (el plan asume x86_64)"
fi

MINT_INFO=""
[[ -r /etc/linuxmint/info ]] && MINT_INFO="$(cat /etc/linuxmint/info)"
{
  echo "uname -a: $(uname -a)"
  echo
  cat /etc/os-release 2>/dev/null || echo "(sin /etc/os-release)"
  echo
  [[ -n "$MINT_INFO" ]] && { echo "/etc/linuxmint/info:"; echo "$MINT_INFO"; echo; }
  echo "Escritorio (XDG_CURRENT_DESKTOP): ${XDG_CURRENT_DESKTOP:-desconocido}"
  echo "Sesión (XDG_SESSION_TYPE): ${XDG_SESSION_TYPE:-desconocida}"
  echo
  echo "glibc: $(ldd --version 2>/dev/null | head -n1 || echo desconocida)"
} | seccion "Sistema operativo"

SESION="${XDG_SESSION_TYPE:-desconocida}"
case "$SESION" in
  x11) marca "✅" "Sesión gráfica" "X11" ;;
  wayland) marca "⚠️" "Sesión gráfica" "Wayland (algunas herramientas de ventanas no funcionan igual)" ;;
  *) marca "⚠️" "Sesión gráfica" "$SESION (correr el script desde la sesión gráfica, no por SSH)" ;;
esac

# Spotifast nativo (AppImage, .tar.gz) necesita glibc >= 2.39 (Mint 22+).
GLIBC_VER="$(ldd --version 2>/dev/null | head -n1 | grep -iE 'glibc|gnu libc' | grep -oE '[0-9]+\.[0-9]+$' || true)"
if [[ -n "$GLIBC_VER" ]]; then
  if [[ "$(printf '%s\n2.39\n' "$GLIBC_VER" | sort -V | head -n1)" == "2.39" ]]; then
    marca "✅" "glibc" "$GLIBC_VER (Spotifast nativo funciona)"
  else
    marca "⚠️" "glibc" "$GLIBC_VER < 2.39: Spotifast solo como Flatpak (o actualizar a Mint 22)"
  fi
fi

# ---------- CPU y memoria ----------
ejecutar lscpu | seccion "CPU (lscpu)"

FLAGS="$(grep -m1 '^flags' /proc/cpuinfo 2>/dev/null || true)"
NUCLEOS="$(nproc 2>/dev/null || echo '?')"
MODELO="$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | tr -s ' ' | sed 's/^ *//; s/ *$//' || true)"
if grep -qw avx2 <<<"$FLAGS"; then
  marca "✅" "CPU" "${MODELO:-desconocida}, $NUCLEOS hilos, AVX2"
elif grep -qw avx <<<"$FLAGS"; then
  marca "⚠️" "CPU" "${MODELO:-desconocida}, $NUCLEOS hilos, AVX sin AVX2 (faster-whisper/onnxruntime más lentos)"
else
  marca "❌" "CPU" "${MODELO:-desconocida}, $NUCLEOS hilos, sin AVX (puede impedir onnxruntime/faster-whisper)"
fi

ejecutar free -h | seccion "Memoria (free -h)"

MEM_KB="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
MEM_GB="$(awk -v kb="$MEM_KB" 'BEGIN { printf "%.1f", kb / 1024 / 1024 }')"
# Un equipo de 4 GB reporta ~3.6–3.8 GB utilizables.
if (( MEM_KB >= 3500000 )); then
  marca "✅" "RAM" "$MEM_GB GB"
elif (( MEM_KB >= 1700000 )); then
  marca "⚠️" "RAM" "$MEM_GB GB (usar el perfil ligero del plan)"
else
  marca "❌" "RAM" "$MEM_GB GB (insuficiente para el plan)"
fi

LIBRE_KB="$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)"
LIBRE_GB="$(awk -v kb="${LIBRE_KB:-0}" 'BEGIN { printf "%.1f", kb / 1024 / 1024 }')"
ejecutar df -h "$HOME" | seccion "Disco (df -h \$HOME)"
if (( ${LIBRE_KB:-0} >= 5242880 )); then
  marca "✅" "Disco libre" "$LIBRE_GB GB"
else
  marca "⚠️" "Disco libre" "$LIBRE_GB GB (los modelos de voz necesitan ~2–5 GB)"
fi

# ---------- Audio ----------
PACTL_INFO="$(ejecutar pactl info)"
echo "$PACTL_INFO" | seccion "Servidor de audio (pactl info)"
if grep -q "PipeWire" <<<"$PACTL_INFO"; then
  marca "✅" "Servidor de audio" "PipeWire"
elif grep -q "PulseAudio" <<<"$PACTL_INFO"; then
  marca "⚠️" "Servidor de audio" "PulseAudio (el plan asume PipeWire; Mint 22 lo trae)"
else
  marca "❌" "Servidor de audio" "no se pudo consultar (¿falta pactl / pulseaudio-utils?)"
fi

{
  for paquete in pipewire wireplumber pipewire-pulse libspa-0.2-bluetooth; do
    version="$(dpkg-query -W -f='${Version}' "$paquete" 2>/dev/null || true)"
    echo "$paquete: ${version:-(no instalado o no es Debian/Ubuntu)}"
  done
  tiene pipewire && echo "pipewire --version: $(pipewire --version 2>/dev/null | tr '\n' ' ')"
} | seccion "Versiones de PipeWire / WirePlumber"

ejecutar wpctl status | seccion "wpctl status"
{
  echo "Salida predeterminada (sink): $(pactl get-default-sink 2>/dev/null || echo '?')"
  echo "Entrada predeterminada (source): $(pactl get-default-source 2>/dev/null || echo '?')"
} | seccion "Dispositivos predeterminados"

ARECORD="$(ejecutar arecord -l)"
echo "$ARECORD" | seccion "Micrófonos (arecord -l)"
ejecutar aplay -l | seccion "Salidas (aplay -l)"
if grep -q "^card" <<<"$ARECORD"; then
  marca "✅" "Micrófono" "hay al menos una tarjeta de captura"
else
  marca "❌" "Micrófono" "no se detectó tarjeta de captura"
fi

# ---------- Bluetooth ----------
if tiene bluetoothctl; then
  ejecutar bluetoothctl show | seccion "Bluetooth: adaptador"
  # BlueZ recientes: "devices Paired"; antiguos: "paired-devices".
  EMPAREJADOS="$(bluetoothctl devices Paired 2>/dev/null || true)"
  [[ -z "$EMPAREJADOS" ]] && EMPAREJADOS="$(bluetoothctl paired-devices 2>/dev/null || true)"
  BT_CONECTADA=""; BT_CONFIABLE=""
  {
    if [[ -z "$EMPAREJADOS" ]]; then
      echo "(sin dispositivos emparejados)"
    else
      while read -r _ mac nombre; do
        [[ -z "${mac:-}" ]] && continue
        info="$(bluetoothctl info "$mac" 2>/dev/null || true)"
        conectado="$(awk -F': ' '/Connected:/ {print $2; exit}' <<<"$info")"
        confiable="$(awk -F': ' '/Trusted:/ {print $2; exit}' <<<"$info")"
        icono="$(awk -F': ' '/Icon:/ {print $2; exit}' <<<"$info")"
        echo "$mac  $nombre  | conectado: ${conectado:-?} | confiable: ${confiable:-?} | tipo: ${icono:-?}"
        if [[ "$icono" == audio-* || "$icono" == "" ]]; then
          [[ "$conectado" == "yes" ]] && BT_CONECTADA="$nombre"
          [[ "$confiable" == "yes" ]] && BT_CONFIABLE="$nombre"
        fi
      done <<<"$EMPAREJADOS"
    fi
  } >"$SALIDA_DIR/.bt.tmp"
  # El while corre en este mismo shell (redirección, no tubería), así que las variables sobreviven.
  seccion "Bluetooth: dispositivos emparejados" <"$SALIDA_DIR/.bt.tmp"
  rm -f "$SALIDA_DIR/.bt.tmp"

  if [[ -n "$BT_CONECTADA" ]]; then
    marca "✅" "Bocina Bluetooth conectada" "$BT_CONECTADA"
  else
    marca "⚠️" "Bocina Bluetooth conectada" "ninguna conectada ahora (enciéndela y vuelve a correr el script)"
  fi
  if [[ -n "$BT_CONFIABLE" ]]; then
    marca "✅" "Bocina marcada como confiable" "$BT_CONFIABLE"
  else
    marca "⚠️" "Bocina marcada como confiable" "falta 'bluetoothctl trust <MAC>' (ver la guía)"
  fi
else
  echo "(bluetoothctl no instalado)" | seccion "Bluetooth"
  marca "❌" "Bluetooth" "bluetoothctl no disponible"
fi

# Perfil activo de la tarjeta bluez: a2dp = calidad buena; hfp/hsp/headset = mala.
PERFILES="$(pactl list cards 2>/dev/null | awk '
  /^[ \t]*Name: / { nombre = $2 }
  /Active Profile:/ { if (nombre ~ /bluez/) print nombre " -> " $3 }' || true)"
echo "${PERFILES:-(no hay tarjetas Bluetooth activas en el servidor de audio)}" | seccion "Bluetooth: perfil de audio activo"
if [[ -z "$PERFILES" ]]; then
  marca "⚠️" "Perfil A2DP" "sin tarjeta Bluetooth activa en el servidor de audio"
elif grep -qiE "headset|hfp|hsp" <<<"$PERFILES"; then
  marca "❌" "Perfil A2DP" "la bocina está en perfil de auricular (HFP/HSP): audio de baja calidad"
elif grep -qi "a2dp" <<<"$PERFILES"; then
  marca "✅" "Perfil A2DP" "$(head -n1 <<<"$PERFILES")"
else
  marca "⚠️" "Perfil A2DP" "perfil no reconocido: $(head -n1 <<<"$PERFILES")"
fi

# ---------- Herramientas ----------
{
  for herramienta in playerctl mpv yt-dlp ffmpeg python3 pipx pw-record arecord flatpak piper; do
    if tiene "$herramienta"; then
      case "$herramienta" in
        python3) version="$(python3 --version 2>&1)" ;;
        mpv) version="$(mpv --version 2>/dev/null | head -n1)" ;;
        ffmpeg) version="$(ffmpeg -version 2>/dev/null | head -n1)" ;;
        yt-dlp|playerctl|pipx) version="$("$herramienta" --version 2>/dev/null | head -n1)" ;;
        *) version="instalado" ;;
      esac
      echo "✅ $herramienta: $version"
    else
      echo "—  $herramienta: no instalado"
    fi
  done
} | seccion "Herramientas"

for herramienta in playerctl mpv yt-dlp ffmpeg pipx; do
  if tiene "$herramienta"; then
    marca "✅" "$herramienta" "instalado"
  else
    marca "⚠️" "$herramienta" "no instalado (se instalará en fases siguientes)"
  fi
done

if tiene python3 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  marca "✅" "Python" "$(python3 --version 2>&1)"
else
  marca "❌" "Python" "falta Python 3.10 o superior"
fi

# ---------- Spotifast ----------
SPOTIFAST=()
if tiene spotifast; then
  SPOTIFAST=(spotifast)
  FORMA="nativo ($(command -v spotifast))"
elif tiene flatpak && flatpak list --app 2>/dev/null | grep -qi "rocks.spotifast.Spotifast"; then
  SPOTIFAST=(flatpak run rocks.spotifast.Spotifast)
  FORMA="Flatpak (rocks.spotifast.Spotifast)"
fi

if (( ${#SPOTIFAST[@]} > 0 )); then
  marca "✅" "Spotifast instalado" "$FORMA"
  {
    echo "Forma de instalación: $FORMA"
    echo
    echo "\$ spotifast now-playing --raw"
    "${SPOTIFAST[@]}" now-playing --raw 2>&1 || echo "(sin respuesta: ¿Spotifast está abierto?)"
    echo
    echo "\$ spotifast devices --raw"
    "${SPOTIFAST[@]}" devices --raw 2>&1 || echo "(sin respuesta: ¿Spotifast está abierto?)"
  } | seccion "Spotifast"
  if "${SPOTIFAST[@]}" now-playing --raw >/dev/null 2>&1; then
    marca "✅" "CLI de Spotifast" "responde"
  else
    marca "⚠️" "CLI de Spotifast" "no responde (abre Spotifast y vuelve a correr el script)"
  fi
else
  echo "(Spotifast no encontrado)" | seccion "Spotifast"
  marca "❌" "Spotifast instalado" "no encontrado (ver la guía)"
fi

PLAYERS="$(playerctl --list-all 2>/dev/null || true)"
echo "${PLAYERS:-(ningún reproductor MPRIS activo)}" | seccion "Reproductores MPRIS (playerctl --list-all)"
if grep -qi spotifast <<<"$PLAYERS"; then
  marca "✅" "Spotifast por MPRIS" "visible para playerctl"
elif tiene playerctl; then
  marca "⚠️" "Spotifast por MPRIS" "no visible (¿Spotifast abierto y con reproducción activada?)"
else
  marca "⚠️" "Spotifast por MPRIS" "falta playerctl para comprobarlo"
fi

# ---------- Bandeja del sistema (Spotifast en modo bandeja) ----------
BANDEJA=""
if tiene busctl; then
  BANDEJA="$(busctl --user list 2>/dev/null | grep -i -m1 'StatusNotifierWatcher' | awk '{print $1}' || true)"
fi
echo "${BANDEJA:-(no se encontró un StatusNotifierWatcher en el bus de sesión)}" | seccion "Bandeja del sistema"
if [[ -n "$BANDEJA" ]]; then
  marca "✅" "Bandeja del sistema" "$BANDEJA"
else
  marca "⚠️" "Bandeja del sistema" "no detectada automáticamente; comprobar a mano que Spotifast aparece en el panel"
fi

# ---------- Resumen al inicio del informe ----------
TABLA="$SALIDA_DIR/.tabla.tmp"
{
  echo
  echo "## Resumen"
  echo
  echo "| Estado | Chequeo | Detalle |"
  echo "|---|---|---|"
  for fila in "${RESUMEN[@]}"; do
    IFS='|' read -r estado chequeo detalle <<<"$fila"
    echo "| $estado | $chequeo | ${detalle//|//} |"
  done
  echo
  echo "✅ listo · ⚠️ revisar · ❌ bloquea el plan"
} >"$TABLA"
# Insertar el resumen después del encabezado (las primeras 4 líneas).
{ head -n 4 "$INFORME"; cat "$TABLA"; tail -n +5 "$INFORME"; } >"$INFORME.tmp" && mv "$INFORME.tmp" "$INFORME"
rm -f "$TABLA"

echo
cat <<EOF
Resumen:
$(for fila in "${RESUMEN[@]}"; do IFS='|' read -r e c d <<<"$fila"; printf '  %s %s: %s\n' "$e" "$c" "$d"; done)

Informe completo: $INFORME
EOF
