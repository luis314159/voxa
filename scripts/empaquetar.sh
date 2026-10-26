#!/usr/bin/env bash
# Arma el paquete de un release: el código de VOXA + la pantalla ya compilada para esa arquitectura.
# Lo usa .github/workflows/release.yml; a mano:
#
#   bash scripts/empaquetar.sh x86_64 ui/target/release/voxa-ui dist
set -euo pipefail

if [ $# -ne 3 ]; then
  echo "Uso: bash scripts/empaquetar.sh ARQUITECTURA BINARIO_DE_LA_PANTALLA CARPETA_DE_SALIDA" >&2
  exit 2
fi
arch="$1" binario="$2" salida="$3"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO/pyproject.toml" | head -1)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Solo lo que está en git (sin pruebas ni scripts de entrenamiento: ver export-ignore en .gitattributes).
git -C "$REPO" archive --format=tar --prefix=voxa/ HEAD | tar -x -C "$tmp"
install -D -m 755 "$binario" "$tmp/voxa/ui/bin/voxa-ui"
echo "$version" >"$tmp/voxa/VERSION"
mkdir -p "$salida"
tar -czf "$salida/voxa-linux-$arch.tar.gz" -C "$tmp" voxa
echo "$salida/voxa-linux-$arch.tar.gz (VOXA $version)"
