"""``voxa actualizar``: busca una versión más nueva en los releases de GitHub y la instala.

La instalación la hace ``instalar-voxa.sh`` del propio release (baja el paquete, revisa su huella
y corre el instalador con las mismas opciones de la primera vez). Aquí solo se compara la versión
y se baja ese script.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import voxa
from voxa.services.http import Http, HttpError

GITHUB_REPO = "luis314159/voxa"
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
