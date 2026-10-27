"""Ajustes que se cambian desde la app (el celular): ``ajustes.json`` junto a ``config.toml``.

Van encima de ``config.toml`` (lo último que se eligió en la app gana) y solo se aceptan las
opciones de ``EDITABLE``, con su tipo. Las llaves y tokens no van aquí: cada uno en su archivo 600.
Después de guardar, VOXA se reinicia sola para usar lo nuevo.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from voxa.departure import parse_time
from voxa.services.process import CommandRunner, run_command

log = logging.getLogger(__name__)

SETTINGS_FILE = "ajustes.json"

# Sección → opción → tipo, o la tupla de valores permitidos.
EDITABLE: dict[str, dict[str, Any]] = {
    "spotify": {"client_id": str, "device_name": str},
    "music": {"provider": ("auto", "spotify", "youtube")},
    "weather": {"latitude": float, "longitude": float, "place": str},
    "ai": {
        "enabled": bool, "provider": ("claude", "openai", "azure", "compatible"), "model": str, "endpoint": str,
        "web_search": bool, "monthly_budget_usd": float, "daily_questions": int, "context": str,
    },
    "telegram": {"enabled": bool},
    "calendar": {"enabled": bool, "remind_minutes": int},
    "video": {"enabled": bool},
    "update": {"check": bool, "automatic": bool},
    "web": {"enabled": bool},
    "voice": {"whisper_model": ("tiny", "base", "small"), "language": ("es", "en"), "bilingual": bool},
    "routine": {"departure": "time", "departure_days": "days", "checklist": str, "morning_music": str},
    "house": {"room": str, "main": str},
    "medicine": {"enabled": bool, "ask_every_minutes": int, "tries": int, "notify_telegram": bool, "notify_house": bool},
    "quiet": {"enabled": bool, "start": "time", "end": "time", "level": float},
    "kids": {
        "enabled": bool, "children": "names", "everyone": bool, "clean_music": bool, "max_volume": int,
        "video_from": "time", "video_until": "time",
    },
}
_TEXT_LIMIT = 300


class SettingsError(ValueError):
    pass


def settings_path(config_file: Path) -> Path:
    return config_file.with_name(SETTINGS_FILE)


def load_settings(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("No pude leer %s: %s", path, exc)
        return {}
    return {s: v for s, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def validate(section: str, values: dict[str, Any]) -> dict[str, Any]:
    """Los valores con su tipo correcto; ``SettingsError`` si algo no se puede cambiar desde la app."""
    allowed = EDITABLE.get(section)
    if allowed is None:
        raise SettingsError(f"«{section}» no se cambia desde la app")
    clean: dict[str, Any] = {}
    for key, value in values.items():
        kind = allowed.get(key)
        if kind is None:
            raise SettingsError(f"«{section}.{key}» no se cambia desde la app")
        if kind == "time":
            if not isinstance(value, str) or (value.strip() and parse_time(value) is None):
                raise SettingsError(f"«{section}.{key}» debe ser una hora como 07:30")
            clean[key] = value.strip()
            continue
        if kind == "names":
            if not isinstance(value, list) or not all(isinstance(n, str) and 0 < len(n.strip()) <= 40 for n in value):
                raise SettingsError(f"«{section}.{key}» deben ser nombres cortos")
            clean[key] = sorted({n.strip() for n in value})
            continue
        if kind == "days":
            if not isinstance(value, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in value):
                raise SettingsError(f"«{section}.{key}» deben ser días de 0 (lunes) a 6 (domingo)")
            clean[key] = sorted(set(value))
            continue
        if isinstance(kind, tuple):
            if value not in kind:
                raise SettingsError(f"«{section}.{key}» debe ser uno de: {', '.join(kind)}")
        elif kind is bool:
            if not isinstance(value, bool):
                raise SettingsError(f"«{section}.{key}» debe ser sí o no")
        elif kind is float or kind is int:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SettingsError(f"«{section}.{key}» debe ser un número")
            value = kind(value)
            if value < 0 and section != "weather":
                raise SettingsError(f"«{section}.{key}» no puede ser negativo")
        else:
            if not isinstance(value, str) or len(value) > _TEXT_LIMIT:
                raise SettingsError(f"«{section}.{key}» debe ser un texto corto")
            value = value.strip()
        clean[key] = value
    if section == "weather":
        if not -90 <= clean.get("latitude", 0) <= 90 or not -180 <= clean.get("longitude", 0) <= 180:
            raise SettingsError("coordenadas fuera de rango")
    if section == "medicine" and (not 1 <= clean.get("ask_every_minutes", 5) <= 60 or not 1 <= clean.get("tries", 3) <= 10):
        raise SettingsError("pregunta cada 1 a 60 minutos, de 1 a 10 veces")
    if section == "quiet" and not 0.05 <= clean.get("level", 0.35) <= 1:
        raise SettingsError("el volumen de noche va de 0.05 a 1")
    if section == "kids" and clean.get("max_volume", 0) > 100:
        raise SettingsError("el volumen máximo va de 0 a 100")
    return clean


def save_settings(path: Path, section: str, values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Guarda (y mezcla) los valores de una sección; devuelve todos los ajustes."""
    clean = validate(section, values)
    settings = load_settings(path)
    settings[section] = {**settings.get(section, {}), **clean}
    write_private(path, json.dumps(settings, ensure_ascii=False, indent=2))
    return settings


def write_private(path: Path, text: str) -> None:
    """Escribe solo legible por el usuario (600), de un jalón (archivo temporal y reemplazo)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def read_secret(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def save_secret(path: Path, value: str) -> None:
    write_private(path, value.strip() + "\n")


def under_systemd() -> bool:
    return bool(os.environ.get("INVOCATION_ID"))


async def restart_soon(run: CommandRunner = run_command) -> bool:
    """Reinicia el servicio en 2 s (desde una unidad aparte, para que el reinicio no se corte a sí mismo)."""
    systemd_run = shutil.which("systemd-run")
    if not under_systemd() or systemd_run is None:
        return False
    result = await run([systemd_run, "--user", "--collect", "--on-active=2", "--unit=voxa-reinicio",
                        "systemctl", "--user", "restart", "voxa.service"])
    if result.returncode != 0:
        log.warning("No pude programar el reinicio: %s", result.stderr.strip())
        return False
    return True
