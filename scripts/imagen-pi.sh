#!/usr/bin/env bash
# La imagen de Raspberry Pi con VOXA ya instalada: Raspberry Pi OS (64 bits, con escritorio) + el .deb.
# Se graba con Raspberry Pi Imager, que configura el wifi, el usuario y el nombre antes de grabar
# (os_list_voxa.json). Al arrancar, VOXA baja sus modelos y se configura desde el celular.
#
# Corre como root en Linux arm64 (en GitHub: ubuntu-24.04-arm), sin emular:
#   sudo bash scripts/imagen-pi.sh dist/voxa_X.Y.Z_arm64.deb dist [URL de la imagen publicada]
set -euo pipefail

# Raspberry Pi OS que se usa de base, con su huella (la de su .sha256 publicado).
BASE_URL="https://downloads.raspberrypi.com/raspios_arm64/images/raspios_arm64-2026-10-06"
BASE_IMG="2026-10-06-raspios-trixie-arm64.img.xz"
BASE_SHA256="976766570bee2aaf3047dd78649cfe82abb8fe9687b7f15030cd533ba4e9f7a9"
EXTRA_MB=2560        # para VOXA y su Python (la Pi agranda la partición a toda la tarjeta al arrancar)
MAX_BYTES=2000000000 # GitHub no acepta archivos de más de 2 GiB en un release

deb="$(realpath "$1")"
salida="$(realpath -m "$2")"
version="$(dpkg-deb -f "$deb" Version)"
nombre="voxa-raspberrypi-${version}.img"
url="${3:-https://github.com/luis314159/voxa/releases/download/v${version}/${nombre}.xz}"
trabajo="$(mktemp -d)"
raiz="$trabajo/raiz"
disco=""

limpiar() {
  umount -R "$raiz" 2>/dev/null || true
  [ -n "$disco" ] && losetup -d "$disco" 2>/dev/null || true
  rm -rf "$trabajo"
}
trap limpiar EXIT

echo "== Raspberry Pi OS ($BASE_IMG)"
curl -fL --retry 3 -o "$trabajo/base.img.xz" "$BASE_URL/$BASE_IMG"
echo "$BASE_SHA256  $trabajo/base.img.xz" | sha256sum -c -
xz -dc "$trabajo/base.img.xz" > "$trabajo/$nombre"
rm "$trabajo/base.img.xz"

echo "== Más espacio para VOXA"
truncate -s +"${EXTRA_MB}M" "$trabajo/$nombre"
parted -s "$trabajo/$nombre" resizepart 2 100%
disco="$(losetup -fP --show "$trabajo/$nombre")"
e2fsck -fy "${disco}p2" || [ $? -le 1 ]  # 1 = corrigió algo, está bien
resize2fs "${disco}p2"

echo "== VOXA adentro"
mkdir -p "$raiz"
mount "${disco}p2" "$raiz"
mount "${disco}p1" "$raiz/boot/firmware"
for d in dev dev/pts proc sys; do mount --bind "/$d" "$raiz/$d"; done
# Sin /run del equipo que arma la imagen: el postinst no debe tocar su systemd.
mv "$raiz/etc/resolv.conf" "$trabajo/resolv.conf.pi" 2>/dev/null || true
cp /etc/resolv.conf "$raiz/etc/resolv.conf"
cp "$deb" "$raiz/tmp/voxa.deb"
chroot "$raiz" /bin/bash -euo pipefail <<'DENTRO'
export DEBIAN_FRONTEND=noninteractive VOXA_SIN_ARRANQUE=1
apt-get update
apt-get install -y --no-install-recommends /tmp/voxa.deb
# Lo que el postinst solo hace con systemd corriendo:
systemctl enable voxa-actualizar.timer voxa-ytdlp.timer
if [ -e /usr/lib/systemd/system/voxa-actualizar.path ]; then systemctl enable voxa-actualizar.path; fi
install -d -m 1733 /var/lib/voxa/actualizar
test -x /opt/voxa/venv/bin/voxa && /opt/voxa/venv/bin/voxa --version
# Se llama «voxa» en la red (voxa.local); Raspberry Pi Imager lo puede cambiar.
echo voxa > /etc/hostname
sed -i 's/^127\.0\.1\.1.*/127.0.1.1\tvoxa/' /etc/hosts
apt-get clean
rm -rf /tmp/voxa.deb /var/lib/apt/lists/*
DENTRO
rm "$raiz/etc/resolv.conf"
mv "$trabajo/resolv.conf.pi" "$raiz/etc/resolv.conf" 2>/dev/null || true
sync
umount -R "$raiz"
zerofree "${disco}p2"  # el espacio libre en ceros: comprime mejor
losetup -d "$disco"
disco=""

echo "== Comprimir"
extract_size="$(stat -c %s "$trabajo/$nombre")"
extract_sha256="$(sha256sum "$trabajo/$nombre" | cut -d' ' -f1)"
mkdir -p "$salida"
xz -T0 -6 -c "$trabajo/$nombre" > "$salida/${nombre}.xz"
download_size="$(stat -c %s "$salida/${nombre}.xz")"
download_sha256="$(sha256sum "$salida/${nombre}.xz" | cut -d' ' -f1)"
echo "Imagen: $(numfmt --to=iec "$download_size") comprimida, $(numfmt --to=iec "$extract_size") grabada"
if [ "$download_size" -gt "$MAX_BYTES" ]; then
  echo "La imagen pasa de 2 GB: GitHub no la acepta en el release" >&2
  exit 1
fi

# El ícono que muestra Raspberry Pi Imager (PNG, junto a la imagen en el release).
repo="$(cd "$(dirname "$0")/.." && pwd)"
rsvg-convert -w 64 -h 64 "$repo/assets/brand/voxa_icon.svg" -o "$salida/voxa-icono.png"

# Para Raspberry Pi Imager: «Contenido» → la dirección de este archivo. Con init_format, Imager deja
# configurar wifi, usuario, nombre y SSH antes de grabar (cloud-init de Raspberry Pi OS).
cat > "$salida/os_list_voxa.json" <<JSON
{
  "os_list": [
    {
      "name": "VOXA ${version} (Raspberry Pi OS, 64 bits)",
      "description": "Asistente de voz familiar, ya instalado. Al arrancar se configura desde el celular.",
      "url": "${url}",
      "icon": "${url%/*}/voxa-icono.png",
      "website": "https://github.com/luis314159/voxa",
      "release_date": "$(date -u +%Y-%m-%d)",
      "extract_size": ${extract_size},
      "extract_sha256": "${extract_sha256}",
      "image_download_size": ${download_size},
      "image_download_sha256": "${download_sha256}",
      "init_format": "cloudinit-rpi",
      "devices": ["pi5-64bit", "pi4-64bit"]
    }
  ]
}
JSON
echo "Lista: $salida/${nombre}.xz y $salida/os_list_voxa.json"
