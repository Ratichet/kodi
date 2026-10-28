"""Décompression des archives téléchargées.

Le ZIP passe par la bibliothèque standard. Le RAR passe par bsdtar, livré avec
Windows 10 et 11 (`tar.exe` de System32) : aucun outil à installer. Le 7z n'est
pas traité.
"""

import locale
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


class ArchiveError(Exception):
    """Message destiné à l'utilisateur, affiché sur la ligne du téléchargement."""


def is_archive(path) -> bool:
    return Path(path).suffix.lower() in (".zip", ".rar")


def extract(archive_path, destination=None) -> list[str]:
    """Extrait une archive et renvoie les fichiers écrits.

    L'archive n'est pas supprimée ici : c'est à l'appelant d'en décider, une fois
    l'extraction réussie. Une entrée déjà présente sur le disque est laissée
    tranquille plutôt qu'écrasée.
    """
    archive = Path(archive_path)
    destination = Path(destination) if destination else archive.parent
    if archive.suffix.lower() == ".rar":
        return _extract_rar(archive, destination)
    written = []

    try:
        with zipfile.ZipFile(archive) as bundle:
            members = [member for member in bundle.infolist() if not member.is_dir()]
            _check_room(members, destination)

            for member in members:
                target = _safe_target(member, destination)
                if target is None:
                    logger.warning(
                        f"{archive.name}: entry escaping the destination, skipped "
                        f"({member.filename})"
                    )
                    continue
                if target.exists():
                    logger.info(f"{archive.name}: {target.name} already there, kept")
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, open(target, "wb") as f:
                    shutil.copyfileobj(source, f)
                written.append(str(target))
    except zipfile.BadZipFile as e:
        raise ArchiveError(f"Archive illisible : {e}") from e
    except OSError as e:
        raise ArchiveError(f"Extraction impossible : {e}") from e

    logger.info(f"Extracted {len(written)} file(s) from {archive.name}")
    return written


def _bsdtar() -> str | None:
    # Le tar de Git Bash, souvent avant celui de Windows dans le PATH, est un GNU
    # tar : il ne lit pas le RAR.
    if sys.platform == "win32":
        windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        system_tar = windows / "System32" / "tar.exe"
        if system_tar.is_file():
            return str(system_tar)
    return shutil.which("bsdtar")


def _extract_rar(archive: Path, destination: Path) -> list[str]:
    """bsdtar refuse seul les entrées « .. » ou absolues ; -k garde l'existant.

    Une entrée refusée fait échouer l'extraction : l'archive est alors conservée
    et le message affiché, même si les autres fichiers sont déjà en place.
    """
    # ponytail: pas de contrôle d'espace libre, bsdtar n'annonce les tailles qu'en
    # texte formaté ; un disque plein se solde par une erreur d'extraction.
    tar = _bsdtar()
    if tar is None:
        raise ArchiveError("Archive RAR non prise en charge : bsdtar introuvable.")

    # Sans ce drapeau, l'exécutable gelé (sans console) ferait clignoter une fenêtre.
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def run(*args):
        return subprocess.run(
            [tar, *args, "-f", str(archive)],
            cwd=destination,
            capture_output=True,
            creationflags=no_window,
        )

    listing = run("-t")
    if listing.returncode != 0:
        raise ArchiveError(f"Archive illisible : {_last_line(listing.stderr)}")
    targets = [
        destination / name
        for name in _decode(listing.stdout).splitlines()
        if name and not name.endswith("/")
    ]
    already_there = {target for target in targets if target.exists()}

    result = run("-x", "-k")
    if result.returncode != 0:
        raise ArchiveError(f"Extraction impossible : {_last_line(result.stderr)}")

    written = [str(t) for t in targets if t not in already_there and t.exists()]
    logger.info(f"Extracted {len(written)} file(s) from {archive.name}")
    return written


def _decode(output: bytes) -> str:
    # bsdtar écrit dans la page de code ANSI sous Windows (cp1252 : « Amélie »).
    return output.decode(locale.getpreferredencoding(False), "replace")


def _last_line(stderr: bytes) -> str:
    lines = _decode(stderr).strip().splitlines()
    # La dernière ligne de bsdtar est souvent « Error exit delayed… » : la cause
    # est juste avant.
    useful = [line for line in lines if "Error exit delayed" not in line]
    return (useful or lines or ["erreur inconnue"])[-1]


def _safe_target(member, destination: Path):
    """Chemin de sortie, ou None si l'entrée cherche à sortir du dossier.

    Une archive peut contenir « ../../ailleurs » ou un chemin absolu : sans cette
    vérification, l'extraction écrirait n'importe où sur le disque.
    """
    try:
        candidate = (destination / member.filename).resolve()
    except (OSError, ValueError):
        return None

    root = destination.resolve()
    return candidate if root in candidate.parents else None


def _check_room(members, destination: Path) -> None:
    """Une extraction à court d'espace laisse des fichiers tronqués derrière elle."""
    needed = sum(member.file_size for member in members)
    try:
        free = shutil.disk_usage(destination).free
    except OSError:
        return  # dossier illisible : l'extraction échouera avec un vrai message

    if needed > free:
        raise ArchiveError(
            f"Espace insuffisant : {needed // 2**20} Mio à extraire, "
            f"{free // 2**20} Mio libres."
        )
