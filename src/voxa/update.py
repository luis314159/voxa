"""``voxa actualizar``: busca una versión más nueva en los releases de GitHub y la instala.

La instalación la hace ``instalar-voxa.sh`` del propio release (baja el paquete, revisa su huella
y corre el instalador con las mismas opciones de la primera vez). Aquí solo se compara la versión
y se baja ese script.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

import voxa
from voxa.services.http import Http, HttpError

log = logging.getLogger(__name__)

GITHUB_REPO = "luis314159/voxa"
CHECK_EVERY = 6 * 3600
# Actualización automática (opcional): de madrugada, cuando nadie usa la cocina.
NIGHT_HOURS = range(3, 5)
LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES = f"https://github.com/{GITHUB_REPO}/releases"


def version_key(text: str) -> tuple[int, ...]:
    """«v0.10.2» → (0, 10, 2), para comparar como números y no como texto."""
    return tuple(int(n) for n in re.findall(r"\d+", text.split("-")[0])[:3])


class NoReleases(Exception):
    """El repositorio todavía no publica releases."""


async def latest_version(http: Http) -> str | None:
    """La versión del release más reciente («0.2.0»), o ``None`` si no se pudo consultar."""
    try:
        response = await http.request("GET", LATEST_API, headers={"Accept": "application/vnd.github+json"})
    except HttpError:
        return None
    if response.status == 404:
        raise NoReleases(GITHUB_REPO)
    if response.status != 200 or not isinstance(response.data, dict):
        return None
    tag = str(response.data.get("tag_name") or "")
    return tag.removeprefix("v") or None


def is_newer(candidate: str, current: str = voxa.__version__) -> bool:
    return version_key(candidate) > version_key(current)


def installer_url(version: str | None) -> str:
    which = f"download/v{version.removeprefix('v')}" if version else "latest/download"
    return f"{RELEASES}/{which}/instalar-voxa.sh"


def run_installer(version: str | None) -> int:
    """Baja ``instalar-voxa.sh`` de ese release y lo corre (pide la contraseña si hace falta apt)."""
    import urllib.request

    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "instalar-voxa.sh"
        with urllib.request.urlopen(installer_url(version), timeout=30) as response:  # noqa: S310 - URL fija de GitHub
            script.write_bytes(response.read())
        args = ["bash", str(script)]
        if version:
            args += ["--version", version]
        return subprocess.run(args, check=False).returncode


DEB_VENV = Path("/opt/voxa/venv")
DEB_UNIT = "voxa-actualizar.service"


def from_package() -> bool:
    """VOXA vino del paquete .deb: las actualizaciones las instala el sistema (voxa-actualizar)."""
    import sys

    return Path(sys.prefix).resolve() == DEB_VENV


def launch_package_update(version: str | None = None, folder: Path | None = None, *, wait: bool = False) -> bool:
    """Arranca la actualización del paquete (systemd, como root; polkit deja hacerlo sin contraseña)."""
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return False
    args = [systemctl, "start", DEB_UNIT] if wait else [systemctl, "start", "--no-block", DEB_UNIT]
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("No pude arrancar la actualización del paquete: %s", result.stderr.strip())
        return False
    return True


def launch_unattended(version: str, folder: Path) -> bool:
    """Instala esa versión sin preguntar nada (sin apt ni contraseña), en una unidad aparte de systemd.

    Va aparte para que el reinicio de VOXA al final de la instalación no corte al instalador.
    """
    import urllib.request

    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        log.warning("Sin systemd-run: la actualización automática solo funciona en la PC de la cocina")
        return False
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "instalar-voxa.sh"
    try:
        with urllib.request.urlopen(installer_url(version), timeout=30) as response:  # noqa: S310 - URL fija de GitHub
            script.write_bytes(response.read())
    except OSError as exc:
        log.warning("No pude bajar el instalador de la %s: %s", version, exc)
        return False
    args = [systemd_run, "--user", "--collect", "--unit=voxa-actualizacion", "bash", str(script),
            "--version", version, "--desatendida"]
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("No se pudo lanzar la actualización: %s", result.stderr.strip())
        return False
    log.info("Actualizando a la %s (journalctl --user -u voxa-actualizacion)", version)
    return True


class Updater:
    """Revisa cada tantas horas si hay versión nueva y, si así se configuró, se actualiza de madrugada."""

    def __init__(
        self,
        http: Http,
        folder: Path,
        *,
        automatic: bool = False,
        current: str = voxa.__version__,
        launch: Callable[[str, Path], bool] | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._http = http
        self._folder = folder
        self.automatic = automatic
        self.current = current
        self._launch = launch or (launch_package_update if from_package() else launch_unattended)
        self._now = now
        self.available: str | None = None
        """La versión nueva que hay (``None`` si ya es la más reciente o no se sabe)."""
        self.installing = False
        self.on_change: Callable[[], None] | None = None

    async def check(self) -> str | None:
        try:
            latest = await latest_version(self._http)
        except NoReleases:
            latest = None
        available = latest if latest and is_newer(latest, self.current) else None
        if available != self.available:
            self.available = available
            if available:
                log.info("Hay una versión nueva de VOXA: %s (tienes la %s)", available, self.current)
            if self.on_change:
                self.on_change()
        return available

    def install(self) -> bool:
        if not self.available or self.installing:
            return False
        self.installing = self._launch(self.available, self._folder)
        return self.installing

    async def run(self, idle: Callable[[], bool], every: float = CHECK_EVERY, nap: float = 600) -> None:
        """Revisa al arrancar y cada ``every`` segundos; la automática espera la madrugada y la cocina quieta."""
        last_check = float("-inf")
        loop = asyncio.get_running_loop()
        while True:
            if loop.time() - last_check >= every:
                last_check = loop.time()
                await self.check()
            if self.automatic and self.available and self._now().hour in NIGHT_HOURS and idle():
                self.install()
            await asyncio.sleep(nap)
