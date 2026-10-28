"""Mise à jour de l'application depuis les releases GitHub.

Seule la version Windows « dossier » (EpiKodi.exe + _internal) se met à jour :
c'est elle que publie la CD. Un exécutable unique peut traîner n'importe où,
dans Téléchargements par exemple : y recopier un dossier en miroir effacerait
les fichiers voisins.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from core.config import APP_NAME, APP_VERSION, DATA_DIR
from core.services.archives import extract

logger = logging.getLogger(__name__)

RELEASES_URL = "https://api.github.com/repos/Ratichet/kodi/releases/latest"
ASSET_SUFFIX = "-windows.zip"
UPDATE_DIR = DATA_DIR / "update"
EXE_NAME = f"{APP_NAME}.exe"


class UpdateError(Exception):
    """Message destiné à l'utilisateur."""


class UpdateCancelled(Exception):
    pass


@dataclass
class Release:
    version: str
    url: str
    size: int


def _parse(version: str) -> tuple[int, ...]:
    return tuple(int(number) for number in re.findall(r"\d+", version))


def install_dir() -> Path | None:
    """Dossier de l'application s'il peut être mis à jour, sinon None."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    folder = Path(sys.executable).resolve().parent
    return folder if (folder / "_internal").is_dir() else None


def check(timeout: float = 10) -> Release | None:
    """Dernière release si elle est plus récente que l'application, sinon None."""
    response = requests.get(
        RELEASES_URL,
        timeout=timeout,
        headers={"Accept": "application/vnd.github+json"},
    )
    if response.status_code == 404:
        return None  # aucune release publiée
    response.raise_for_status()
    data = response.json()

    tag = data.get("tag_name") or ""
    if _parse(tag) <= _parse(APP_VERSION):
        return None
    asset = next(
        (a for a in data.get("assets", []) if a["name"].endswith(ASSET_SUFFIX)), None
    )
    if asset is None:
        logger.warning(f"Release {tag} has no {ASSET_SUFFIX} asset")
        return None
    return Release(tag.lstrip("v"), asset["browser_download_url"], asset.get("size", 0))


def download(
    release: Release,
    progress: Callable[[int, int], None] = None,
    cancelled: Callable[[], bool] = None,
) -> Path:
    """Télécharge et décompresse la release ; renvoie le dossier prêt à installer."""
    shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    archive = UPDATE_DIR / "update.zip"

    with requests.get(release.url, stream=True, timeout=30) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or release.size or 0)
        received = 0
        with open(archive, "wb") as f:
            for chunk in response.iter_content(1 << 20):
                if cancelled and cancelled():
                    raise UpdateCancelled()
                f.write(chunk)
                received += len(chunk)
                if progress:
                    progress(received, total)

    # extract() écarte les entrées qui chercheraient à sortir du dossier.
    extract(archive, UPDATE_DIR)
    archive.unlink()

    staging = UPDATE_DIR / APP_NAME
    if not (staging / EXE_NAME).is_file():
        raise UpdateError("L'archive de mise à jour ne contient pas l'application.")
    return staging


def write_install_script(staging: Path, target: Path, pid: int) -> Path:
    """Script qui attend la fin du processus `pid`, recopie puis relance.

    Les fichiers d'une application en cours d'exécution sont verrouillés : la
    copie ne peut se faire qu'une fois celle-ci fermée.
    """

    def quoted(path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    source, log, exe = quoted(staging), quoted(UPDATE_DIR / "install.log"), quoted(target / EXE_NAME)
    script = UPDATE_DIR / "install.ps1"
    script.write_text(
        f"""Wait-Process -Id {pid} -ErrorAction SilentlyContinue
# /MIR : les fichiers disparus de la nouvelle version partent aussi.
robocopy {source} {quoted(target)} /MIR /R:10 /W:1 /NP > {log}
# robocopy : un code inférieur à 8 signifie que la copie a réussi.
if ($LASTEXITCODE -lt 8) {{ Remove-Item -Recurse -Force {source} }}
Start-Process -FilePath {exe}
""",
        # Avec BOM : sans lui, Windows PowerShell lit le script en ANSI et casse
        # un chemin accentué.
        encoding="utf-8-sig",
    )
    return script


def install_and_restart(staging: Path) -> None:
    """Lance l'installation ; l'appelant doit quitter l'application juste après."""
    target = install_dir()
    if target is None:
        raise UpdateError("Cette installation ne peut pas se mettre à jour seule.")

    script = write_install_script(staging, target, os.getpid())
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    logger.info(f"Installing update from {staging} into {target}")
