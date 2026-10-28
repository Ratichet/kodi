import json
import logging
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "EpiKodi"
# Doit valoir le tag de la release sans son « v » : la CD refuse de publier
# sinon, et la mise à jour automatique compare cette valeur au dernier tag.
APP_VERSION = "1.1.0"

logger = logging.getLogger(__name__)


def _resource_dir() -> Path:
    """Fichiers livrés avec l'application : vlc_libs, assets…

    PyInstaller les extrait dans _MEIPASS (dossier temporaire en mode --onefile,
    sous-dossier `_internal` en mode --onedir).
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    return Path(__file__).resolve().parent.parent


def _default_data_dir() -> Path:
    """Dossier inscriptible pour la base, les réglages et le cache d'images.

    Une application installée vit dans Program Files, en lecture seule : écrire à
    côté de l'exécutable y échouerait. On suit donc la convention de chaque système.
    En développement, tout reste dans le dépôt.
    """
    if not getattr(sys, "frozen", False):
        return RESOURCE_DIR

    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(root) / APP_NAME


RESOURCE_DIR = _resource_dir()
# Conservé : le bootstrap VLC et les tests s'y réfèrent.
BASE_DIR = RESOURCE_DIR

ASSETS_DIR = RESOURCE_DIR / "assets"
ICON_FILE = ASSETS_DIR / "icon.ico"

DATA_DIR = Path(os.environ.get("EPIKODI_DATA_DIR") or _default_data_dir())
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError as e:  # pragma: no cover - dépend des droits du système
    logger.error(f"Could not create the data directory {DATA_DIR}: {e}")

CACHE_DIR = DATA_DIR / "cache"

DB_NAME = "epikodi.db"

# EPIKODI_DB_PATH permet de dériver la base ailleurs (les tests l'utilisent pour
# ne jamais toucher la bibliothèque réelle).
DB_PATH = os.environ.get("EPIKODI_DB_PATH") or f"sqlite:///{DATA_DIR}/{DB_NAME}"

SETTINGS_FILE = DATA_DIR / "settings.json"


def migrate_legacy_data() -> bool:
    """Récupère les données d'une version portable installée à côté de l'exe.

    Les premières versions gelées écrivaient dans le dossier de l'exécutable. Sans
    cette reprise, une mise à jour vers la version installée repartirait sur une
    bibliothèque vide.
    """
    if not getattr(sys, "frozen", False):
        return False

    legacy_dir = Path(sys.executable).resolve().parent
    if legacy_dir == DATA_DIR or not (legacy_dir / DB_NAME).is_file():
        return False
    if (DATA_DIR / DB_NAME).exists():
        return False  # la nouvelle base a déjà servi, on n'écrase rien

    moved = []
    for name in (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm", "settings.json"):
        source = legacy_dir / name
        if source.is_file():
            try:
                shutil.copy2(source, DATA_DIR / name)
                moved.append(name)
            except OSError as e:
                logger.error(f"Could not migrate {name}: {e}")

    legacy_cache = legacy_dir / "cache"
    if legacy_cache.is_dir() and not CACHE_DIR.exists():
        try:
            shutil.copytree(legacy_cache, CACHE_DIR)
            moved.append("cache")
        except OSError as e:
            logger.error(f"Could not migrate the image cache: {e}")

    if moved:
        logger.info(f"Migrated from the portable layout to {DATA_DIR}: {', '.join(moved)}")
    return bool(moved)

# config tmdb
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

_DEFAULTS = {
    "tmdb_api_key": "",
    "tmdb_language": "fr-FR",
    "audio_language": "",
    "subtitle_language": "",
    # Vide : le service prend le premier dossier surveillé, pour que ce qui arrive
    # rejoigne la bibliothèque tout seul.
    "download_dir": "",
    "onefichier_api_key": "",
}

logger = logging.getLogger(__name__)


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupted settings.json, using defaults.")
    return {}


def _save_settings(settings: dict) -> bool:
    try:
        SETTINGS_FILE.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return True
    except OSError as e:
        logger.error(f"Could not write {SETTINGS_FILE}: {e}")
        return False


def get_setting(key: str) -> str:
    settings = _load_settings()
    return settings.get(key, _DEFAULTS.get(key, ""))


def set_setting(key: str, value: str) -> bool:
    settings = _load_settings()
    settings[key] = value
    return _save_settings(settings)


def get_tmdb_api_key() -> str:
    return get_setting("tmdb_api_key")


def get_tmdb_language() -> str:
    return get_setting("tmdb_language")


def get_audio_language() -> str:
    """Langues audio préférées, au format attendu par VLC : « eng,en,english ».

    Les conteneurs étiquettent leurs pistes tantôt en ISO 639-2, tantôt en clair :
    on stocke toutes les variantes d'une même langue, VLC retient la première qui
    correspond. Vide (par défaut) : la première piste du fichier est gardée.
    """
    return get_setting("audio_language")


def get_onefichier_api_key() -> str:
    """Clé API 1fichier, nécessaire pour transformer un lien de page en fichier.

    Elle reste dans settings.json, qui n'est pas versionné. L'API demande un compte
    payant : sans clé, un lien 1fichier est refusé avec un message explicite.
    """
    return get_setting("onefichier_api_key")


def get_subtitle_language() -> str:
    """Langues de sous-titres préférées, même format que `get_audio_language()`.

    Vide (par défaut) : aucune piste intégrée n'est activée, VLC laisse l'image nue.
    """
    return get_setting("subtitle_language")

# files extensions supported by EpiKodi
SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ts",
    ".m2ts",
    ".vob",
}

SUPPORTED_SUBTITLE_EXTENSIONS = {".srt", ".sub", ".ass", ".ssa", ".vtt"}

# Suffixes de langue portés par les fichiers de sous-titres : code ISO 639-1,
# 639-2 ou nom en clair — « Film.fr.srt », « Film.fre.srt », « Film.french.srt ».
SUBTITLE_LANGUAGE_SUFFIXES = [
    "fr", "fre", "fra", "french",
    "en", "eng", "english",
    "es", "spa", "spanish",
    "de", "ger", "deu", "german",
    "it", "ita", "italian",
    "pt", "por", "portuguese",
    "ja", "jpn", "japanese",
    "zh", "chi", "zho", "chinese",
]

DEFAULT_MEDIA_DIRECTORIES = [
    str(Path.home() / "Videos"),
    str(Path.home() / "Movies"),
    str(Path.home() / "Vidéos"),
    str(Path.home() / "Films"),
]


def get_existing_media_directories() -> list:
    return [d for d in DEFAULT_MEDIA_DIRECTORIES if Path(d).exists()]
