#!/usr/bin/env bash
# Arma el paquete .deb (doble clic en Linux Mint, Ubuntu o Raspberry Pi OS) a partir del paquete
# del release (scripts/empaquetar.sh) y la rueda de Python de VOXA. Lo usa release.yml; a mano:
#
#   bash scripts/empaquetar-deb.sh x86_64 dist/voxa-linux-x86_64.tar.gz dist/rueda/voxa-*.whl dist
set -euo pipefail

if [ $# -ne 4 ]; then
  echo "Uso: bash scripts/empaquetar-deb.sh ARQUITECTURA PAQUETE.tar.gz RUEDA.whl CARPETA_DE_SALIDA" >&2
  exit 2
fi
arch="$1" paquete="$2" rueda="$3" salida="$4"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "$arch" in
  x86_64) deb_arch=amd64 ;;
  aarch64) deb_arch=arm64 ;;
  *) echo "Arquitectura desconocida: $arch" >&2; exit 2 ;;
esac
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
raiz="$tmp/raiz"
fuente="$REPO/packaging/deb"

mkdir -p "$raiz/opt/voxa/wheels"
tar -xzf "$paquete" -C "$raiz/opt/voxa"
mv "$raiz/opt/voxa/voxa" "$raiz/opt/voxa/app"
version="$(cat "$raiz/opt/voxa/app/VERSION")"
case "$(basename "$rueda")" in
  "voxa-$version-"*.whl) ;;
  *) echo "La rueda $(basename "$rueda") no es la de VOXA $version" >&2; exit 1 ;;
esac
install -m 644 "$rueda" "$raiz/opt/voxa/wheels/"
chmod 755 "$raiz/opt/voxa/app/packaging/deb/actualizar.sh"

install -D -m 755 "$fuente/voxa" "$raiz/usr/bin/voxa"
ln -s /opt/voxa/app/ui/bin/voxa-ui "$raiz/usr/bin/voxa-ui"
install -D -m 644 "$fuente/voxa.service" "$raiz/usr/lib/systemd/user/voxa.service"
install -D -m 644 "$fuente/voxa-ui.service" "$raiz/usr/lib/systemd/user/voxa-ui.service"
for unidad in voxa-actualizar.service voxa-actualizar.timer voxa-ytdlp.service voxa-ytdlp.timer; do
  install -D -m 644 "$fuente/$unidad" "$raiz/usr/lib/systemd/system/$unidad"
done
install -D -m 644 "$REPO/deploy/autostart/voxa-ui.desktop" "$raiz/etc/xdg/autostart/voxa-ui.desktop"
install -D -m 644 "$fuente/50-voxa.rules" "$raiz/usr/share/polkit-1/rules.d/50-voxa.rules"

mkdir -p "$raiz/DEBIAN"
for script in postinst prerm postrm; do
  install -m 755 "$fuente/$script" "$raiz/DEBIAN/$script"
done
tamano="$(du -sk "$raiz" | cut -f1)"
cat >"$raiz/DEBIAN/control" <<EOF
Package: voxa
Version: $version
Architecture: $deb_arch
Maintainer: luis314159 <luis314159@users.noreply.github.com>
Installed-Size: $tamano
Depends: python3 (>= 3.10), python3-venv, ca-certificates, curl, playerctl, libportaudio2, mpv, wireplumber, pipewire-bin | pipewire, libxkbcommon-x11-0, libgl1, libegl1, libwayland-client0, libxcursor1, libxrandr2, libxi6
Section: sound
Priority: optional
Homepage: https://github.com/luis314159/voxa
Description: VOXA, asistente de voz familiar para la cocina
 Música, temporizadores, recetas, lista del súper, calendario y avisos entre
 cuartos, en español y con «Hey Voxa». Se configura desde el celular; la
 primera vez baja sola sus modelos de voz.
EOF

mkdir -p "$salida"
destino="$salida/voxa_${version}_${deb_arch}.deb"
dpkg-deb --root-owner-group --build "$raiz" "$destino" >/dev/null
echo "$destino (VOXA $version, $deb_arch)"
