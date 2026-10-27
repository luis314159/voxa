#!/bin/sh
# Instala la versión más reciente del paquete de VOXA (lo corre voxa-actualizar.service, como root).
# Revisa la huella del .deb contra SHA256SUMS del release antes de instalarlo.
set -eu

REPO="${VOXA_REPO:-luis314159/voxa}"
BASE="https://github.com/$REPO/releases/latest/download"
arch="$(dpkg --print-architecture)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL --retry 3 -o "$tmp/SHA256SUMS" "$BASE/SHA256SUMS"
deb="$(grep -o "voxa_[0-9][0-9.]*_${arch}\.deb" "$tmp/SHA256SUMS" | head -1 || true)"
if [ -z "$deb" ]; then
  echo "El release más reciente no trae paquete para $arch."
  exit 0
fi
nueva="$(echo "$deb" | sed "s/^voxa_\(.*\)_${arch}\.deb\$/\1/")"
actual="$(dpkg-query -W -f='${Version}' voxa 2>/dev/null || echo 0)"
if ! dpkg --compare-versions "$nueva" gt "$actual"; then
  echo "VOXA $actual ya es la más reciente."
  exit 0
fi
echo "Actualizando VOXA $actual → $nueva…"
curl -fL --retry 3 -o "$tmp/$deb" "$BASE/$deb"
if ! (cd "$tmp" && grep "  $deb\$" SHA256SUMS | sha256sum -c --status -); then
  echo "La huella de $deb no coincide con SHA256SUMS: no se instaló." >&2
  exit 1
fi
chmod 644 "$tmp/$deb"
chmod 755 "$tmp"
DEBIAN_FRONTEND=noninteractive apt-get install -y "$tmp/$deb"
