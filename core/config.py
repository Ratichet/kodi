import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

DB_NAME = "epikodi.db"
DB_PATH = f"sqlite:///{BASE_DIR}/{DB_NAME}"

# config tmdb
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
TMDB_LANGUAGE = os.getenv("TMDB_LANGUAGE", "fr-FR")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

if not TMDB_API_KEY:
    import logging

    logging.getLogger(__name__).warning(
        "TMDB_API_KEY not set! Create a .env file from .env.example. "
        "Metadata enrichment will not work."
    )

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

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".aac",
    ".ogg",
    ".wma",
    ".m4a",
    ".opus",
}

SUPPORTED_SUBTITLE_EXTENSIONS = {".srt", ".sub", ".ass", ".ssa", ".vtt"}

DEFAULT_MEDIA_DIRECTORIES = [
    str(Path.home() / "Videos"),
    str(Path.home() / "Movies"),
    str(Path.home() / "Vidéos"),
    str(Path.home() / "Films"),
]


def get_existing_media_directories() -> list:
    return [d for d in DEFAULT_MEDIA_DIRECTORIES if Path(d).exists()]
