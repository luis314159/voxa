"""El primer arranque: VOXA baja sola lo que necesita, con la huella de cada archivo.

Así el paquete ``.deb`` (doble clic) no tiene que bajar nada y nadie abre la terminal: la primera
vez que corre el servicio, la pantalla dice «Preparando VOXA…» y el avance. Se baja:

- los modelos de voz (Vosk, la voz de Piper, la base de «Hey Voxa», Whisper);
- los fondos de pantalla (dominio público);
- Spotifast (la AppImage, verificada con la huella que publica GitHub), con arranque oculto.

También deja la bocina Bluetooth en alta calidad (WirePlumber) y que el escritorio no se bloquee.
Lo que ya está se respeta; también se puede correr a mano: ``voxa preparar``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from voxa.config import Config

log = logging.getLogger(__name__)

PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_MX/claude/high"
WAKE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip"
VOSK_SHA256 = "09b239888f633ef2f0b4e09736e3d9936acfd810bc65d53fad45261762c6511f"
SPOTIFAST_RELEASE = "https://api.github.com/repos/crmne/spotifast/releases/latest"
SPOTIFAST_GLIBC = (2, 39)

Progress = Callable[[str], None]


class PrepareError(Exception):
    pass


@dataclass(frozen=True)
class Download:
    name: str
    url: str
    sha256: str
    target: Path


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "voxa"


def app_dir() -> Path | None:
    """La carpeta con ``deploy/`` y ``scripts/`` (el paquete .deb la pone en VOXA_APP_DIR)."""
    for candidate in (os.environ.get("VOXA_APP_DIR"), Path(__file__).resolve().parents[2]):
        if candidate and (Path(candidate) / "deploy").is_dir():
            return Path(candidate)
    return None


def model_downloads(config: Config) -> list[Download]:
    piper = Path(config.voice.piper_voice).expanduser()
    wake = Path(config.wake.feature_dir).expanduser()
    return [
        Download("la voz de VOXA", f"{PIPER}/es_MX-claude-high.onnx",
                 "3ef40a71ea63852cd8ab7e6fa7d2ecdcfa67a0b47c9c48e3f10e02ee02083ea0", piper),
        Download("la voz de VOXA (ajustes)", f"{PIPER}/es_MX-claude-high.onnx.json",
                 "1afc81f703c0e4cb3b4d7c0dca096b8b54a98806807f0170cf5eb5557723c12d", piper.with_name(piper.name + ".json")),
        Download("«Hey Voxa» (1 de 2)", f"{WAKE}/melspectrogram.onnx",
                 "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f", wake / "melspectrogram.onnx"),
        Download("«Hey Voxa» (2 de 2)", f"{WAKE}/embedding_model.onnx",
                 "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f", wake / "embedding_model.onnx"),
    ]


def missing(config: Config) -> list[str]:
    """Lo que falta para que VOXA oiga y hable (vacío: lista)."""
    out = [d.name for d in model_downloads(config) if not d.target.exists()]
    if not Path(config.voice.vosk_model).expanduser().is_dir():
        out.insert(0, "el reconocimiento de voz")
    return out


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, target: Path, expected: str, progress: Progress, label: str) -> None:
    """Baja a un archivo temporal, revisa la huella y solo entonces lo pone en su lugar."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".parcial")
    request = urllib.request.Request(url, headers={"User-Agent": "VOXA"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:  # noqa: S310 - URLs fijas
        total = int(response.headers.get("Content-Length") or 0)
        done, shown = 0, -10
        while block := response.read(1 << 16):
            out.write(block)
            done += len(block)
            if total and (percent := done * 100 // total) >= shown + 10:
                shown = percent
                progress(f"Bajando {label}… {percent} %")
    if sha256(partial) != expected:
        partial.unlink(missing_ok=True)
        raise PrepareError(f"la huella de {label} no coincide: no se usó")
    partial.replace(target)


def prepare_models(config: Config, progress: Progress, *, whisper: bool = True) -> None:
    vosk = Path(config.voice.vosk_model).expanduser()
    if not vosk.is_dir():
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "vosk.zip"
            fetch(VOSK_URL, archive, VOSK_SHA256, progress, "el reconocimiento de voz")
            progress("Instalando el reconocimiento de voz…")
            vosk.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as zf:
                root = vosk.parent.resolve()
                for member in zf.namelist():  # nada fuera de la carpeta de modelos
                    if not (root / member).resolve().is_relative_to(root):
                        raise PrepareError("el modelo de voz trae rutas raras: no se usó")
                zf.extractall(vosk.parent)
    for item in model_downloads(config):
        if not item.target.exists():
            fetch(item.url, item.target, item.sha256, progress, item.name)
    if not whisper:
        return
    progress("Preparando el reconocimiento preciso (Whisper)…")
    try:
        from faster_whisper import WhisperModel

        WhisperModel(config.voice.whisper_model, compute_type="int8")
    except Exception as exc:  # noqa: BLE001 - se baja solo la primera vez que se use
        log.warning("Whisper se bajará en la primera orden: %s", exc)


# --- Spotifast --------------------------------------------------------------------------------
def glibc() -> tuple[int, int]:
    try:
        version = os.confstr("CS_GNU_LIBC_VERSION") or ""
        major, minor = version.split()[-1].split(".")[:2]
        return int(major), int(minor)
    except (ValueError, OSError, AttributeError, IndexError):
        return (0, 0)


def spotifast_asset(release: dict, machine: str) -> tuple[str, str, str] | None:
    """(nombre, url, sha256) de la AppImage de esta arquitectura en el release de Spotifast."""
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine.lower())
    for asset in release.get("assets", []):
        name, digest = asset.get("name", ""), asset.get("digest") or ""
        if arch and name.endswith(f"-{arch}.AppImage") and digest.startswith("sha256:"):
            return name, asset["browser_download_url"], digest.removeprefix("sha256:")
    return None


def prepare_spotifast(progress: Progress) -> str:
    if shutil.which("spotifast"):
        return "ya estaba"
    if sys.platform != "linux" or glibc() < SPOTIFAST_GLIBC:
        return "omitido (pide Linux Mint 22 / Ubuntu 24.04 o más nuevo)"
    request = urllib.request.Request(SPOTIFAST_RELEASE, headers={"User-Agent": "VOXA", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - URL fija de GitHub
        release = json.load(response)
    asset = spotifast_asset(release, platform.machine())
    if asset is None:
        return "omitido (no hay versión para esta PC)"
    _, url, digest = asset
    folder = data_dir() / "spotifast"
    image = folder / "spotifast.AppImage"
    fetch(url, image, digest, progress, "Spotifast")
    image.chmod(0o755)
    home = Path.home()
    launcher = home / ".local/bin/spotifast"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    # Sin FUSE (Ubuntu 24.04 ya no lo trae): la AppImage se extrae y corre.
    launcher.write_text(f'#!/bin/sh\nAPPIMAGE_EXTRACT_AND_RUN=1 exec "{image}" "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    autostart = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "autostart/spotifast-voxa.desktop"
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text(
        "[Desktop Entry]\nType=Application\nName=Spotifast (VOXA)\n"
        f"Exec={launcher} --start-hidden\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n",
        encoding="utf-8",
    )
    return f"instalado ({release.get('tag_name', '')})"


# --- el escritorio y el audio de esta PC -----------------------------------------------------
def prepare_desktop() -> None:
    """La cocina no se bloquea ni se duerme (Cinnamon), una vez."""
    marker = data_dir() / "escritorio-listo"
    if marker.exists() or not shutil.which("gsettings"):
        return
    schemas = subprocess.run(["gsettings", "list-schemas"], capture_output=True, text=True, check=False).stdout
    if "org.cinnamon.desktop.session" not in schemas.split():
        return
    for args in (["org.cinnamon.desktop.session", "idle-delay", "0"],
                 ["org.cinnamon.desktop.screensaver", "lock-enabled", "false"],
                 ["org.cinnamon.settings-daemon.plugins.power", "sleep-display-ac", "0"],
                 ["org.cinnamon.settings-daemon.plugins.power", "sleep-inactive-ac-timeout", "0"]):
        subprocess.run(["gsettings", "set", *args], check=False)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def prepare_audio(app: Path | None) -> None:
    """La bocina Bluetooth en alta calidad y sin dormirse (la configuración de WirePlumber de VOXA)."""
    if app is None or not shutil.which("wireplumber"):
        return
    version = subprocess.run(["wireplumber", "--version"], capture_output=True, text=True, check=False).stdout
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    files = {
        app / "deploy/wireplumber/0.5/wireplumber.conf.d/51-voxa.conf": config_home / "wireplumber/wireplumber.conf.d/51-voxa.conf",
    }
    if "0.4." in version:
        files = {
            app / "deploy/wireplumber/0.4/bluetooth.lua.d/51-voxa-bluetooth.lua": config_home / "wireplumber/bluetooth.lua.d/51-voxa-bluetooth.lua",
            app / "deploy/wireplumber/0.4/main.lua.d/51-voxa-sin-suspension.lua": config_home / "wireplumber/main.lua.d/51-voxa-sin-suspension.lua",
        }
    changed = False
    for source, target in files.items():
        if source.exists() and (not target.exists() or target.read_bytes() != source.read_bytes()):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            changed = True
    if changed:
        subprocess.run(["systemctl", "--user", "restart", "wireplumber.service"], check=False)


def prepare_backgrounds(app: Path | None, progress: Progress) -> None:
    folder = data_dir() / "fondos"
    script = app / "scripts/descargar_fondos.py" if app else None
    if script is None or not script.exists() or (folder.is_dir() and any(folder.iterdir())):
        return
    progress("Bajando fondos de pantalla…")
    subprocess.run([sys.executable, str(script), "--destino", str(folder)], check=False, capture_output=True)


def prepare(config: Config, progress: Progress = lambda text: None) -> list[str]:
    """Todo lo del primer arranque; devuelve lo que no se pudo (para decirlo, sin detenerse)."""
    problems = []
    progress("Preparando VOXA…")
    try:
        prepare_models(config, progress)
    except (OSError, PrepareError, zipfile.BadZipFile) as exc:
        problems.append(f"modelos de voz: {exc}")
    app = app_dir()
    for name, step in (("audio", lambda: prepare_audio(app)), ("escritorio", prepare_desktop),
                       ("fondos", lambda: prepare_backgrounds(app, progress))):
        try:
            step()
        except (OSError, subprocess.SubprocessError) as exc:
            problems.append(f"{name}: {exc}")
    if config.music.provider != "youtube":
        progress("Instalando Spotifast…")
        try:
            log.info("Spotifast: %s", prepare_spotifast(progress))
        except (OSError, PrepareError, ValueError) as exc:
            problems.append(f"Spotifast: {exc}")
    progress("Listo.")
    return problems


async def prepare_async(config: Config, progress: Progress) -> list[str]:
    loop = asyncio.get_running_loop()

    def report(text: str) -> None:
        loop.call_soon_threadsafe(progress, text)

    return await asyncio.to_thread(prepare, config, report)
