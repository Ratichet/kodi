"""Décompression des archives téléchargées.

Seul le format ZIP est traité, avec la bibliothèque standard : RAR et 7z
demanderaient un exécutable externe, que l'application ne peut pas garantir.
"""

import logging
import shutil
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


class ArchiveError(Exception):
    """Message destiné à l'utilisateur, affiché sur la ligne du téléchargement."""


def is_archive(path) -> bool:
    return Path(path).suffix.lower() == ".zip"


def extract(archive_path, destination=None) -> list[str]:
    """Extrait une archive et renvoie les fichiers écrits.

    L'archive n'est pas supprimée ici : c'est à l'appelant d'en décider, une fois
    l'extraction réussie. Une entrée déjà présente sur le disque est laissée
    tranquille plutôt qu'écrasée.
    """
    archive = Path(archive_path)
    destination = Path(destination) if destination else archive.parent
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
