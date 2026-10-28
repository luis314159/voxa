#!/usr/bin/env bash
# Instala VOXA en la PC de la cocina (Linux Mint 22). Se puede correr varias veces:
# lo que ya está hecho se respeta (la configuración del usuario nunca se sobrescribe).
#
#   bash scripts/install.sh               # todo
#   bash scripts/install.sh --simular     # muestra qué haría, sin cambiar nada
#
# Opciones: --sin-apt  --sin-modelos  --sin-pantalla  --sin-fondos  --sin-video  --sin-servicios
#           --sin-ajustes-escritorio  --cancelar-eco (experimental: oír «Hey Voxa» con música fuerte)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/voxa"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
BIN="$HOME/.local/bin"
VOSK_MODEL="vosk-model-small-es-0.42"
# Modelos base de «Hey Voxa» (openWakeWord v0.5.1), con su huella para no instalar algo alterado.
WAKE_URL="https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
WAKE_MODELS=(
  "melspectrogram.onnx ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f"
  "embedding_model.onnx 70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f"
)
PIPER_VOICE="es_MX-claude-high"
# Los paquetes de los releases traen la pantalla ya compilada (scripts/empaquetar.sh): sin Rust.
UI_LISTA="$REPO/ui/bin/voxa-ui"

SIMULAR=0 APT=1 MODELOS=1 PANTALLA=1 FONDOS=1 VIDEO=1 SERVICIOS=1 ESCRITORIO=1 ECO=0
for arg in "$@"; do
  case "$arg" in
    --simular) SIMULAR=1 ;;
    --sin-apt) APT=0 ;;
    --sin-modelos) MODELOS=0 ;;
    --sin-pantalla) PANTALLA=0 ;;
    --sin-fondos) FONDOS=0 ;;
    --sin-video) VIDEO=0 ;;
    --cancelar-eco) ECO=1 ;;
    --sin-servicios) SERVICIOS=0 ;;
    --sin-ajustes-escritorio) ESCRITORIO=0 ;;
    -h|--help|--ayuda) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
aviso() { printf '\033[1;33m  ⚠ %s\033[0m\n' "$*"; }
listo() { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
# Ejecuta un comando, o solo lo muestra con --simular.
run() {
  if [ "$SIMULAR" = 1 ]; then printf '  $ %s\n' "$*"; else "$@"; fi
}
tiene() { command -v "$1" >/dev/null 2>&1; }
# Copia un archivo solo si cambió (y lo dice).
instalar_archivo() {
  local origen="$1" destino="$2"
  if [ -f "$destino" ] && cmp -s "$origen" "$destino"; then return 0; fi
  run mkdir -p "$(dirname "$destino")"
  run cp "$origen" "$destino"
  listo "$destino"
}

# --- 0. Comprobaciones ---------------------------------------------------------
paso "Comprobando el sistema"
if [ "$(id -u)" = 0 ]; then
  echo "Corre este script como tu usuario normal, no con sudo (pedirá la contraseña cuando haga falta)." >&2
  exit 1
fi
if [ -r /etc/os-release ]; then
  . /etc/os-release
  listo "${PRETTY_NAME:-Linux}"
  case "${ID:-}:${ID_LIKE:-}" in
    *ubuntu*|*debian*|linuxmint*) ;;
    *) aviso "Pensado para Linux Mint / Ubuntu; en otra distribución instala los paquetes a mano." ; APT=0 ;;
  esac
fi

# --- 1. Paquetes del sistema --------------------------------------------------
if [ "$APT" = 1 ]; then
  paso "Paquetes del sistema (pide tu contraseña)"
  paquetes=(pipx python3-venv playerctl libportaudio2 pipewire-bin wireplumber unzip curl)
  if [ "$PANTALLA" = 1 ] && [ -x "$UI_LISTA" ]; then
    # La pantalla ya compilada solo necesita las bibliotecas de X11/Wayland y OpenGL.
    paquetes+=(libxkbcommon-x11-0 libwayland-client0 libgl1 libegl1 libxcursor1 libxrandr2 libxi6)
  elif [ "$PANTALLA" = 1 ]; then
    # Para compilar la pantalla (egui sobre X11/Wayland con OpenGL).
    paquetes+=(build-essential pkg-config libxkbcommon-dev libwayland-dev libgl1-mesa-dev libxcursor-dev libxrandr-dev libxi-dev)
  fi
  if [ "$VIDEO" = 1 ]; then
    paquetes+=(mpv)
  fi
  run sudo apt-get update -qq
  run sudo apt-get install -y "${paquetes[@]}"
fi

# --- 2. Núcleo (Python) -------------------------------------------------------
paso "Instalando VOXA (núcleo)"
run pipx install --force "${REPO}[audio,ia]"
run pipx ensurepath
VENV_PY="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null || echo "$HOME/.local/share/pipx/venvs")/voxa/bin/python"

if [ ! -f "$CONFIG/voxa/config.toml" ]; then
  instalar_archivo "$REPO/config/default.toml" "$CONFIG/voxa/config.toml"
  aviso "Spotify, el clima y lo demás se configuran desde el celular: escanea el código de la pantalla (Ajustes)"
else
  listo "Se conserva tu configuración: $CONFIG/voxa/config.toml"
fi

# --- 3. Modelos de voz ----------------------------------------------------------
if [ "$MODELOS" = 1 ]; then
  paso "Modelos de voz (la primera vez descarga ~300 MB)"
  if [ -d "$DATA/models/$VOSK_MODEL" ]; then
    listo "Vosk: $VOSK_MODEL"
  else
    if [ "$SIMULAR" = 1 ]; then tmp=/tmp/voxa-descarga; else tmp="$(mktemp -d)"; fi
    run curl -fL --retry 3 -o "$tmp/vosk.zip" "https://alphacephei.com/vosk/models/$VOSK_MODEL.zip"
    run mkdir -p "$DATA/models"
    run unzip -q "$tmp/vosk.zip" -d "$DATA/models"
    run rm -rf "$tmp"
  fi
  if [ -f "$DATA/models/piper/$PIPER_VOICE.onnx" ]; then
    listo "Piper: $PIPER_VOICE"
  else
    run "$VENV_PY" -m piper.download_voices "$PIPER_VOICE" --download-dir "$DATA/models/piper"
  fi
  for entrada in "${WAKE_MODELS[@]}"; do
    read -r archivo huella <<<"$entrada"
    destino="$DATA/models/wakeword/$archivo"
    if [ -f "$destino" ] && [ "$(sha256sum "$destino" | cut -d' ' -f1)" = "$huella" ]; then
      listo "«Hey Voxa»: $archivo"
      continue
    fi
    run mkdir -p "$DATA/models/wakeword"
    run curl -fL --retry 3 -o "$destino.parcial" "$WAKE_URL/$archivo"
    if [ "$SIMULAR" = 0 ] && [ "$(sha256sum "$destino.parcial" | cut -d' ' -f1)" != "$huella" ]; then
      rm -f "$destino.parcial"
      aviso "La huella de $archivo no coincide: no se instaló («Hey Voxa» no estará disponible)."
      continue
    fi
    run mv "$destino.parcial" "$destino"
  done
  # faster-whisper descarga su modelo la primera vez que se usa; mejor ahora que en la primera orden.
  modelo_whisper="$(sed -n 's/^whisper_model *= *"\(.*\)"/\1/p' "$CONFIG/voxa/config.toml" 2>/dev/null | head -1 || true)"
  run "$VENV_PY" -c "from faster_whisper import WhisperModel; WhisperModel('${modelo_whisper:-base}', compute_type='int8')"
fi

# --- 4. Pantalla (Rust) -----------------------------------------------------------
if [ "$PANTALLA" = 1 ]; then
  paso "Pantalla de cocina (voxa-ui)"
  if ! tiene cargo && [ -x "$HOME/.cargo/bin/cargo" ]; then PATH="$HOME/.cargo/bin:$PATH"; fi
  if [ -x "$UI_LISTA" ]; then
    run mkdir -p "$BIN"
    run install -m 755 "$UI_LISTA" "$BIN/voxa-ui"
    listo "$BIN/voxa-ui (ya compilada)"
  elif tiene cargo; then
    run cargo build --release --locked --manifest-path "$REPO/ui/Cargo.toml"
    run mkdir -p "$BIN"
    run install -m 755 "$REPO/ui/target/release/voxa-ui" "$BIN/voxa-ui"
    listo "$BIN/voxa-ui"
  else
    aviso "Falta Rust para compilar la pantalla. Instálalo con:"
    aviso "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    aviso "y vuelve a correr este script (lo ya instalado se respeta)."
  fi
fi

if [ "$FONDOS" = 1 ]; then
  paso "Fondos de pantalla (dominio público / CC0)"
  run "$VENV_PY" "$REPO/scripts/descargar_fondos.py" --destino "$DATA/fondos" || aviso "No se pudieron bajar los fondos; la pantalla usará el fondo liso."
fi

# --- 5. Videos: yt-dlp (de pipx: el de apt envejece rápido) y deno, que YouTube ya exige ----
if [ "$VIDEO" = 1 ]; then
  paso "Videos de YouTube (yt-dlp + deno + mpv)"
  instalados="$(pipx list --short 2>/dev/null || true)"
  for app in "yt-dlp[default]" deno; do
    nombre="${app%%\[*}"
    if printf '%s\n' "$instalados" | grep -q "^$nombre "; then
      listo "$nombre (se actualiza solo cada semana)"
    else
      run pipx install "$app"
    fi
  done
  tiene mpv || [ "$SIMULAR" = 1 ] || aviso "Falta mpv: sudo apt install mpv"
fi

# --- 6. Audio: bocina Bluetooth en A2DP y sin suspensión --------------------------
paso "Audio (WirePlumber)"
version_wp="$(wireplumber --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1 || true)"
case "$version_wp" in
  0.4)
    instalar_archivo "$REPO/deploy/wireplumber/0.4/bluetooth.lua.d/51-voxa-bluetooth.lua" "$CONFIG/wireplumber/bluetooth.lua.d/51-voxa-bluetooth.lua"
    instalar_archivo "$REPO/deploy/wireplumber/0.4/main.lua.d/51-voxa-sin-suspension.lua" "$CONFIG/wireplumber/main.lua.d/51-voxa-sin-suspension.lua"
    ;;
  "")
    aviso "No encontré WirePlumber; la bocina Bluetooth podría cambiar de perfil o dormirse." ;;
  *)
    instalar_archivo "$REPO/deploy/wireplumber/0.5/wireplumber.conf.d/51-voxa.conf" "$CONFIG/wireplumber/wireplumber.conf.d/51-voxa.conf" ;;
esac
[ -n "$version_wp" ] && run systemctl --user restart wireplumber.service

if [ "$ECO" = 1 ]; then
  paso "Cancelación de eco (micrófono sin la música de la bocina)"
  instalar_archivo "$REPO/deploy/pipewire/pipewire.conf.d/60-voxa-eco.conf" "$CONFIG/pipewire/pipewire.conf.d/60-voxa-eco.conf"
  run systemctl --user restart pipewire.service wireplumber.service
  if [ "$SIMULAR" = 1 ]; then
    printf '  $ wpctl set-default <id de voxa_mic_sin_eco>\n'
  else
    sleep 2
    id_eco="$(pw-dump 2>/dev/null | python3 -c '
import json, sys
for obj in json.load(sys.stdin):
    if (obj.get("info") or {}).get("props", {}).get("node.name") == "voxa_mic_sin_eco":
        print(obj["id"])
' || true)"
    if [ -n "$id_eco" ]; then
      wpctl set-default "$id_eco"
      listo "Micrófono predeterminado: VOXA: micrófono sin eco"
    else
      aviso "No apareció «VOXA: micrófono sin eco»; revisa: journalctl --user -u pipewire"
    fi
  fi
fi

# --- 7. Arranque automático --------------------------------------------------------
if [ "$SERVICIOS" = 1 ]; then
  paso "Arranque automático"
  instalar_archivo "$REPO/deploy/systemd/voxa.service" "$CONFIG/systemd/user/voxa.service"
  instalar_archivo "$REPO/deploy/systemd/voxa-ui.service" "$CONFIG/systemd/user/voxa-ui.service"
  instalar_archivo "$REPO/deploy/autostart/voxa-ui.desktop" "$CONFIG/autostart/voxa-ui.desktop"
  # En el menú: «VOXA» y «Ajustes de VOXA» (con la ruta completa: el menú no siempre ve ~/.local/bin).
  APPS="$HOME/.local/share/applications"
  instalar_archivo "$REPO/deploy/applications/voxa.desktop" "$APPS/voxa.desktop"
  ajustes_desktop="$(mktemp)"
  sed "s|^Exec=voxa |Exec=$BIN/voxa |" "$REPO/deploy/applications/voxa-ajustes.desktop" >"$ajustes_desktop"
  instalar_archivo "$ajustes_desktop" "$APPS/voxa-ajustes.desktop"
  rm -f "$ajustes_desktop"
  instalar_archivo "$REPO/assets/brand/voxa_icon.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/voxa.svg"
  if [ "$VIDEO" = 1 ]; then
    instalar_archivo "$REPO/deploy/systemd/voxa-ytdlp.service" "$CONFIG/systemd/user/voxa-ytdlp.service"
    instalar_archivo "$REPO/deploy/systemd/voxa-ytdlp.timer" "$CONFIG/systemd/user/voxa-ytdlp.timer"
  fi
  run systemctl --user daemon-reload
  if [ "$VIDEO" = 1 ]; then
    run systemctl --user enable --now voxa-ytdlp.timer
  fi
  run systemctl --user enable voxa.service
  run systemctl --user restart voxa.service
  if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && [ -x "$BIN/voxa-ui" ]; then
    run systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY
    run systemctl --user restart voxa-ui.service
  fi
fi

# --- 8. Escritorio: que la cocina no se bloquee ni se duerma -------------------------
if [ "$ESCRITORIO" = 1 ] && tiene gsettings && gsettings list-schemas 2>/dev/null | grep -q '^org.cinnamon.desktop.session$'; then
  paso "Escritorio Cinnamon: sin bloqueo ni suspensión"
  run gsettings set org.cinnamon.desktop.session idle-delay 0
  run gsettings set org.cinnamon.desktop.screensaver lock-enabled false
  run gsettings set org.cinnamon.settings-daemon.plugins.power sleep-display-ac 0
  run gsettings set org.cinnamon.settings-daemon.plugins.power sleep-inactive-ac-timeout 0
fi

paso "Listo"
cat <<EOF
  • Revisar todo:  voxa revisar   (qué falta y cómo arreglarlo)
  • Estado:        systemctl --user status voxa voxa-ui
  • Registro:      journalctl --user -u voxa -f
  • Probar a mano: voxa texto
  • Configurar:    escanea con el celular el código de la pantalla → Ajustes
                   (Spotify, clima, voz de la familia, calendario, Telegram, IA).
                   Si ya no está el código: «Hey Voxa, configura VOXA».
  • Falta a mano:  inicio de sesión automático (Menú → Ventana de inicio de sesión →
                   Usuarios → Inicio de sesión automático).
EOF
