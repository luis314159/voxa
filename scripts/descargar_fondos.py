"""Descarga los fondos de pantalla de ``assets/fondos/catalogo.json``.

Son fotos de Wikimedia Commons en dominio público o CC0: se pueden usar sin pedir permiso.
Antes de bajar cada una se revisa que su licencia lo sea.

    python scripts/descargar_fondos.py                  # a ~/.local/share/voxa/fondos
    python scripts/descargar_fondos.py --tema mexico    # solo un tema: mexico | mundo | naturaleza
    python scripts/descargar_fondos.py --destino CARPETA

En esa carpeta también puedes poner tus propias fotos (.jpg o .png): la pantalla las mezcla.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "assets" / "fondos" / "catalogo.json"
FREE_LICENSES = ("cc0", "public domain", "dominio público", "pd")
MAX_BYTES = 15 * 1024 * 1024
# Wikimedia pide identificar a quien descarga: https://meta.wikimedia.org/wiki/User-Agent_policy
USER_AGENT = "VOXA-fondos/0.1 (asistente de voz familiar; uso personal)"


def default_folder() -> Path:
    """La misma carpeta que usa voxa-ui por defecto."""
    if os.environ.get("XDG_DATA_HOME"):
        base = Path(os.environ["XDG_DATA_HOME"])
    elif os.environ.get("HOME"):
        base = Path(os.environ["HOME"]) / ".local" / "share"
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "voxa" / "fondos"


def is_free(license_name: str) -> bool:
    name = license_name.strip().lower()
    return any(name == free or name.startswith(free + " ") for free in FREE_LICENSES)


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("el archivo es demasiado grande")
    if not (data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG")):
        raise ValueError("no es una imagen JPEG/PNG")
    partial = target.with_suffix(target.suffix + ".parcial")
    partial.write_bytes(data)
    partial.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--destino", type=Path, default=default_folder())
    parser.add_argument("--tema", choices=["mexico", "mundo", "naturaleza"])
    args = parser.parse_args()

    entries = json.loads(CATALOG.read_text(encoding="utf-8"))
    if args.tema:
        entries = [e for e in entries if e.get("tema") == args.tema]
    args.destino.mkdir(parents=True, exist_ok=True)

    kept, failed = [], 0
    for entry in entries:
        name = Path(entry["archivo"]).name  # nunca fuera de la carpeta destino
        if not is_free(entry.get("licencia", "")):
            print(f"  omitida {name}: licencia «{entry.get('licencia')}» no es libre")
            continue
        target = args.destino / name
        if target.exists():
            kept.append(entry)
            continue
        try:
            download(entry["url_1920"], target)
        except (OSError, ValueError) as exc:
            print(f"  ✗ {name}: {exc}")
            failed += 1
            continue
        print(f"  ✓ {entry.get('lugar', name)}")
        kept.append(entry)
        time.sleep(0.5)  # sin prisa: Commons es un servicio gratuito

    # El catálogo junto a las fotos le dice a la pantalla el nombre de cada lugar.
    catalog = args.destino / "catalogo.json"
    previous = json.loads(catalog.read_text(encoding="utf-8")) if catalog.exists() else []
    merged = {e["archivo"]: e for e in [*previous, *kept]}
    catalog.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(kept)} fondos en {args.destino}" + (f" · {failed} fallaron" if failed else ""))
    return 1 if failed and not kept else 0


if __name__ == "__main__":
    sys.exit(main())
