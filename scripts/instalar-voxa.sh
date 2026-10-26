#!/usr/bin/env bash
# Instala o actualiza VOXA desde los releases de GitHub: sin git y sin compilar nada.
#
#   curl -fLO https://github.com/luis314159/voxa/releases/latest/download/instalar-voxa.sh
#   bash instalar-voxa.sh                     # la versión más reciente
#   bash instalar-voxa.sh --version 0.1.0     # una versión en particular (p. ej. para regresar)
#
# Las demás opciones pasan al instalador (--sin-video, --cancelar-eco…; ver scripts/install.sh)
# y se recuerdan para las actualizaciones (voxa actualizar).
set -euo pipefail

GITHUB_REPO="${VOXA_REPO:-luis314159/voxa}"
RELEASES="${VOXA_RELEASES:-https://github.com/$GITHUB_REPO/releases}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/voxa"
OPCIONES="${XDG_CONFIG_HOME:-$HOME/.config}/voxa/opciones-instalacion"

version="" pasar=()
while [ $# -gt 0 ]; do
  case "$1" in
    --version)
      [ $# -ge 2 ] || { echo "Falta el número después de --version" >&2; exit 2; }
      version="${2#v}"
      shift 2
      ;;
    -h|--help|--ayuda) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) pasar+=("$1"); shift ;;
  esac
done
if [ "${#pasar[@]}" -eq 0 ] && [ -r "$OPCIONES" ]; then
  read -r -a pasar <"$OPCIONES"  # las mismas opciones que la primera vez
fi

case "$(uname -m)" in
  x86_64|amd64) arch=x86_64 ;;
  aarch64|arm64) arch=aarch64 ;;
  *) echo "VOXA no tiene paquete para esta arquitectura ($(uname -m)); instala desde el código: scripts/install.sh" >&2; exit 1 ;;
esac
if [ -n "$version" ]; then url="$RELEASES/download/v$version"; else url="$RELEASES/latest/download"; fi
paquete="voxa-linux-$arch.tar.gz"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
printf '\033[1;36m▸ Descargando VOXA %s (%s)\033[0m\n' "${version:-más reciente}" "$arch"
curl -fL --retry 3 -o "$tmp/$paquete" "$url/$paquete"
curl -fsSL --retry 3 -o "$tmp/SHA256SUMS" "$url/SHA256SUMS"
# La huella publicada junto al release: el paquete llegó completo y sin cambios.
if ! (cd "$tmp" && grep "  $paquete\$" SHA256SUMS | sha256sum -c --status -); then
  echo "La huella de $paquete no coincide con SHA256SUMS: no se instaló nada." >&2
  exit 1
fi
tar -xzf "$tmp/$paquete" -C "$tmp"
instalada="$(cat "$tmp/voxa/VERSION")"

# Cada versión en su carpeta; «actual» apunta a la instalada. Se guardan las dos más recientes.
destino="$DATA/app/$instalada"
mkdir -p "$DATA/app"
rm -rf "$destino"
mv "$tmp/voxa" "$destino"
ln -sfn "$destino" "$DATA/app/actual"
mapfile -t viejas < <(find "$DATA/app" -mindepth 1 -maxdepth 1 -type d ! -name "$instalada" -printf '%T@ %p\n' | sort -rn | tail -n +2 | cut -d' ' -f2-)
for vieja in "${viejas[@]}"; do rm -rf "$vieja"; done

recordar=()
for opcion in "${pasar[@]}"; do [ "$opcion" = --simular ] || recordar+=("$opcion"); done
if [ "${#recordar[@]}" -gt 0 ]; then
  mkdir -p "$(dirname "$OPCIONES")"
  printf '%s\n' "${recordar[*]}" >"$OPCIONES"
fi
bash "$destino/scripts/install.sh" "${pasar[@]}"
printf '\n\033[32m✓ VOXA %s instalada (%s)\033[0m\n' "$instalada" "$destino"
