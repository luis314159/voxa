"""Spotifast con el mismo Client ID que VOXA: la familia crea una sola app de Spotify.

Spotifast guarda sus ajustes en ``~/.config/spotifast/settings.json`` (``web_client_id`` y
``device_name``); VOXA los escribe para que no haya que copiarlos dos veces y para que cada cuarto
aparezca en Spotify con su nombre («VOXA Sala»). Spotifast los lee al arrancar.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

REDIRECT = "http://127.0.0.1:8989/login"
"""La dirección de regreso de Spotifast: va en la app de Spotify junto con la de VOXA."""


def settings_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "spotifast" / "settings.json"


def configure(client_id: str, device_name: str, path: Path | None = None) -> bool:
    """Pone el Client ID y el nombre del dispositivo en Spotifast; True si cambió algo."""
    path = path or settings_file()
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except FileNotFoundError:
        current = {}
    except (OSError, ValueError) as exc:
        log.warning("No pude leer los ajustes de Spotifast (%s): no los toco", exc)
        return False
    wanted = {"web_client_id": client_id, "device_name": device_name}
    if all(current.get(k) == v for k, v in wanted.items()):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".voxa")
    tmp.write_text(json.dumps({**current, **wanted}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    log.info("Spotifast configurado: Client ID y «%s»", device_name)
    return True
