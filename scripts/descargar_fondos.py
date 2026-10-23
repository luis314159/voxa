"""Descarga los fondos de pantalla de ``assets/fondos/catalogo.json``.

Son fotos de Wikimedia Commons en dominio público o CC0: se pueden usar sin pedir permiso.
Antes de bajar nada se consulta a Commons, en ese momento, la licencia de cada foto. Por
precaución se omiten las importadas de Unsplash que Commons aún no ha revisado a mano
(``--incluir-sin-revisar`` las agrega).

    python scripts/descargar_fondos.py                  # a ~/.local/share/voxa/fondos
    python scripts/descargar_fondos.py --tema mexico    # solo un tema: mexico | mundo | naturaleza
    python scripts/descargar_fondos.py --destino CARPETA

En esa carpeta también puedes poner tus propias fotos (.jpg o .png): la pantalla las mezcla.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "assets" / "fondos" / "catalogo.json"
FREE_LICENSES = ("cc0", "public domain", "dominio público", "pd")
MAX_BYTES = 15 * 1024 * 1024
# Wikimedia pide identificar a quien descarga: https://meta.wikimedia.org/wiki/User-Agent_policy
USER_AGENT = "VOXA-fondos/0.1 (asistente de voz familiar; uso personal)"
API = "https://commons.wikimedia.org/w/api.php"
UNREVIEWED = "Category:Images from Unsplash (review needed)"


def default_folder() -> Path:
    """La misma carpeta que usa voxa-ui por defecto."""
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif os.environ.get("XDG_DATA_HOME"):
        base = Path(os.environ["XDG_DATA_HOME"])
    elif os.environ.get("HOME"):
        base = Path(os.environ["HOME"]) / ".local" / "share"
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "voxa" / "fondos"


def is_free(license_name: str) -> bool:
    name = license_name.strip().lower()
    return any(name == free or name.startswith(free + " ") for free in FREE_LICENSES)


def _tls() -> ssl.SSLContext:
    """Con certifi si está instalado: el almacén de certificados de algunos Windows trae raíces vencidas."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


_TLS = _tls()


def fetch(url: str, limit: int = MAX_BYTES) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60, context=_TLS) as response:
        return response.read(limit + 1)


def current_status(titles: list[str]) -> dict[str, tuple[str, bool]]:
    """Licencia actual en Commons y si está pendiente de revisión, por título de archivo."""
    status: dict[str, tuple[str, bool]] = {}
    for start in range(0, len(titles), 40):
        params = {
            "action": "query", "format": "json", "formatversion": "2", "titles": "|".join(titles[start : start + 40]),
            "prop": "imageinfo|categories", "iiprop": "extmetadata", "iiextmetadatafilter": "LicenseShortName",
            "clcategories": UNREVIEWED, "cllimit": "max",
        }
        data = json.loads(fetch(f"{API}?{urllib.parse.urlencode(params)}"))
        renamed = {n["to"]: n["from"] for n in data["query"].get("normalized", [])}
        for page in data["query"]["pages"]:
            info = (page.get("imageinfo") or [{}])[0].get("extmetadata", {})
            license_name = info.get("LicenseShortName", {}).get("value", "")
            status[renamed.get(page["title"], page["title"])] = (license_name, bool(page.get("categories")))
    return status


def download(url: str, target: Path) -> None:
    data = fetch(url)
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
    parser.add_argument("--incluir-sin-revisar", action="store_true", help="incluye las fotos de Unsplash sin revisar")
    args = parser.parse_args()

    entries = json.loads(CATALOG.read_text(encoding="utf-8"))
    if args.tema:
        entries = [e for e in entries if e.get("tema") == args.tema]
    args.destino.mkdir(parents=True, exist_ok=True)
    try:
        status = current_status([e["titulo_commons"] for e in entries])
    except (OSError, ValueError, KeyError) as exc:
        print(f"No pude consultar las licencias en Commons ({exc}); no se descargó nada.")
        return 1

    kept, failed = [], 0
    for entry in entries:
        name = Path(entry["archivo"]).name  # nunca fuera de la carpeta destino
        license_name, unreviewed = status.get(entry["titulo_commons"], ("", False))
        if not is_free(license_name):
            print(f"  omitida {name}: licencia en Commons «{license_name or 'desconocida'}»")
            continue
        if unreviewed and not args.incluir_sin_revisar:
            print(f"  omitida {name}: Commons aún no revisa su licencia")
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
