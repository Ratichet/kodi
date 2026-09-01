"""Localisation des bibliothèques VLC avant tout `import vlc`.

python-vlc résout libvlc au moment de l'import : le chemin doit donc être posé
avant. Ce module centralise cette préparation, qui existait auparavant en trois
copies (main.py, ui/widgets/video_widget.py) et manquait dans ui/views/music_view.py,
où l'import de `vlc` ne fonctionnait que grâce à l'ordre des imports.
"""

import logging
import os
import platform
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_done = False


def ensure_vlc_path() -> None:
    """Ajoute les bibliothèques VLC embarquées au chemin de recherche (idempotent)."""
    global _done
    if _done:
        return
    _done = True

    for vlc_dir in _candidate_dirs():
        if not vlc_dir.is_dir():
            continue

        os.environ["PYTHON_VLC_MODULE_PATH"] = str(vlc_dir)

        libvlc = vlc_dir / ("libvlc.dll" if platform.system() == "Windows" else "libvlc.so")
        if libvlc.is_file():
            os.environ["PYTHON_VLC_LIB_PATH"] = str(libvlc)

        if platform.system() == "Windows":
            os.environ["PATH"] = str(vlc_dir) + os.pathsep + os.environ.get("PATH", "")
            # Depuis Python 3.8, PATH ne suffit plus pour les DLL dépendantes.
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(vlc_dir))
                except OSError as e:
                    logger.debug(f"add_dll_directory failed for {vlc_dir}: {e}")
        else:
            os.environ["LD_LIBRARY_PATH"] = (
                str(vlc_dir) + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")
            )

        logger.debug(f"Using bundled VLC libraries from {vlc_dir}")
        return

    logger.debug("No bundled VLC libraries found, relying on the system install.")


def _candidate_dirs():
    """Emplacements possibles de vlc_libs, du plus spécifique au plus général."""
    # Exécutable PyInstaller : les données sont extraites dans _MEIPASS.
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        yield Path(bundle_dir) / "vlc_libs"

    from core.config import BASE_DIR

    yield BASE_DIR / "vlc_libs"
