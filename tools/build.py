"""Construit l'exécutable EpiKodi.

Une seule recette, utilisée en local comme par la CI : sans ça, les options
PyInstaller vivent en double dans le workflow et finissent par diverger.

    python tools/build.py              # exécutable unique (comme la release)
    python tools/build.py --onedir     # dossier : démarrage bien plus rapide
    python tools/build.py --clean      # repart de zéro
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Une console Windows en cp1252 ne sait pas écrire « ✓ » : le build allait au
# bout puis mourait sur son propre message final, en rendant un code non nul.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, OSError):  # flux redirigé ou déjà fermé
        pass

ROOT = Path(__file__).resolve().parent.parent
NAME = "EpiKodi"
ENTRY = ROOT / "main.py"
ICON = ROOT / "assets" / "icon.ico"

# guessit lit ses règles depuis des fichiers de données, et babelfish enregistre
# ses convertisseurs par points d'entrée : PyInstaller ne voit ni les uns ni les
# autres par analyse statique.
COLLECT_ALL = ("babelfish", "guessit")
HIDDEN_IMPORTS = (
    "vlc",
    "PySide6.QtSvg",
    "babelfish.converters.alpha2",
    "babelfish.converters.alpha3b",
    "babelfish.converters.alpha3t",
    "babelfish.converters.name",
    "babelfish.converters.opensubtitles",
)

WINDOWS_VLC_DIRS = (
    Path(r"C:\Program Files\VideoLAN\VLC"),
    Path(r"C:\Program Files (x86)\VideoLAN\VLC"),
)


def _fail(message: str) -> int:
    print(f"\n✗ {message}", file=sys.stderr)
    return 1


def _find_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        return False
    return True


def _find_vlc() -> Path | None:
    """Dossier VLC à embarquer.

    Sur Windows l'exécutable doit tout emporter : la machine d'arrivée n'a pas
    forcément VLC. Ailleurs on s'appuie sur le paquet système, comme la CI Linux.
    """
    if sys.platform != "win32":
        return None

    bundled = ROOT / "vlc_libs"
    if (bundled / "libvlc.dll").is_file():
        return bundled
    for candidate in WINDOWS_VLC_DIRS:
        if (candidate / "libvlc.dll").is_file():
            return candidate
    return None


def _ensure_icon() -> Path | None:
    if sys.platform != "win32":
        return None  # --icon attend un .icns sur macOS, rien sous Linux
    if not ICON.is_file():
        print("· icône absente, génération…")
        sys.path.insert(0, str(ROOT))
        from tools.make_icon import main as make_icon

        make_icon()
    return ICON


def build(onedir: bool, clean: bool) -> int:
    if not _find_pyinstaller():
        return _fail(
            "PyInstaller n'est pas installé dans cet environnement.\n"
            "  pip install pyinstaller"
        )

    if clean:
        for directory in (ROOT / "build", ROOT / "dist"):
            shutil.rmtree(directory, ignore_errors=True)
        print("· build/ et dist/ effacés")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--name",
        NAME,
        "--onedir" if onedir else "--onefile",
        "--windowed",
    ]

    icon = _ensure_icon()
    if icon:
        command += ["--icon", str(icon)]

    # --icon ne grave l'image que dans l'exécutable, pour l'explorateur. Qt lit le
    # fichier au lancement pour l'icône de fenêtre : il doit être dans le paquet.
    assets = ROOT / "assets"
    if assets.is_dir():
        command += ["--add-data", f"{assets}{os.pathsep}assets"]

    vlc_dir = _find_vlc()
    if vlc_dir:
        # os.pathsep : « ; » sous Windows, « : » ailleurs.
        command += ["--add-data", f"{vlc_dir}{os.pathsep}vlc_libs"]
        print(f"· VLC embarqué depuis {vlc_dir}")
    elif sys.platform == "win32":
        print(
            "· aucun VLC trouvé : l'exécutable exigera une installation de VLC "
            "sur la machine d'arrivée"
        )

    for package in COLLECT_ALL:
        command += ["--collect-all", package]
    for module in HIDDEN_IMPORTS:
        command += ["--hidden-import", module]

    command.append(str(ENTRY))

    print(f"· {' '.join(command[2:6])} …\n")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return _fail(f"PyInstaller a échoué (code {result.returncode})")

    produced = _produced_path(onedir)
    if produced is None or not produced.exists():
        return _fail("build terminé mais l'exécutable est introuvable")

    size = _tree_size(produced) / 2**20
    print(f"\n✓ {produced}  ({size:.0f} Mio)")
    if not onedir:
        print(
            "  L'exécutable unique déballe VLC dans un dossier temporaire à chaque "
            "lancement.\n  --onedir démarre nettement plus vite si tu distribues un "
            "dossier ou un installeur."
        )
    return 0


def _produced_path(onedir: bool) -> Path | None:
    suffix = ".exe" if sys.platform == "win32" else ""
    if onedir:
        return ROOT / "dist" / NAME
    return ROOT / "dist" / f"{NAME}{suffix}"


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="produit un dossier au lieu d'un exécutable unique",
    )
    parser.add_argument(
        "--clean", action="store_true", help="efface build/ et dist/ avant de bâtir"
    )
    args = parser.parse_args()
    return build(onedir=args.onedir, clean=args.clean)


if __name__ == "__main__":
    raise SystemExit(main())
