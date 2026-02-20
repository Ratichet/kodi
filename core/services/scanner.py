import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileDeletedEvent,
    FileMovedEvent,
)
import guessit

from core.config import SUPPORTED_VIDEO_EXTENSIONS, SUPPORTED_AUDIO_EXTENSIONS
from core.database import SessionLocal
from core.models import Media

logger = logging.getLogger(__name__)

# Config scanner
MIN_VIDEO_SIZE_MB = 50  # skip tiny video files (samples, etc.)
MIN_AUDIO_SIZE_KB = 100  # skip audio files < 100 KB (jingles / corrupt)
IGNORED_KEYWORDS = ["sample", "trailer", "featurette", "extra", "scene"]


@dataclass
class ParsedMedia:
    """Parsed media info extracted from filename (and optionally audio tags)."""

    file_path: str
    title: str
    year: Optional[int] = None
    media_type: str = "movie"  # movie | episode | music
    # series info
    series: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: Optional[str] = None
    # audio-specific
    artist: Optional[str] = None
    album: Optional[str] = None
    track_number: Optional[int] = None
    # quality / source
    quality: Optional[str] = None
    source: Optional[str] = None

    def get_search_title(self) -> str:
        """Return a clean title suitable for TMDb search."""
        if self.media_type == "episode" and self.series:
            return self.series
        return self.title


# ── Audio tag reader (uses mutagen when available) ────────────────────────────


def _read_audio_tags(file_path: str) -> Dict[str, Any]:
    try:
        import mutagen

        audio = mutagen.File(file_path, easy=True)
        if not audio:
            return {}
        tags: Dict[str, Any] = {}

        def _first(key):
            v = audio.get(key)
            return v[0] if v else None

        tags["title"] = _first("title")
        tags["artist"] = _first("artist") or _first("albumartist")
        tags["album"] = _first("album")
        tags["year"] = _first("date") or _first("year")
        tracknumber = _first("tracknumber")
        if tracknumber:
            try:
                tags["track_number"] = int(str(tracknumber).split("/")[0])
            except (ValueError, AttributeError):
                pass
        return tags
    except ImportError:
        logger.debug(
            "mutagen not installed – falling back to filename parsing for audio metadata."
        )
        return {}
    except Exception as e:
        logger.debug(f"Could not read audio tags for {file_path}: {e}")
        return {}


# ── Parsers ───────────────────────────────────────────────────────────────────


class MediaParser:
    @staticmethod
    def parse(file_path: str) -> Optional["ParsedMedia"]:
        try:
            path = Path(file_path)
            ext = path.suffix.lower()

            if ext in SUPPORTED_AUDIO_EXTENSIONS:
                return MediaParser._parse_audio(file_path)

            filename = path.name
            guess = guessit.guessit(filename)
            media_type = guess.get("type", "movie")

            return ParsedMedia(
                file_path=file_path,
                title=guess.get("title", path.stem),
                year=guess.get("year"),
                media_type=media_type,
                series=guess.get("title") if media_type == "episode" else None,
                season=guess.get("season"),
                episode=guess.get("episode"),
                episode_title=guess.get("episode_title"),
                quality=guess.get("screen_size"),
                source=guess.get("source"),
            )
        except Exception as e:
            logger.error(f"Failed to parse '{file_path}': {e}")
            return None

    @staticmethod
    def _parse_audio(file_path: str) -> "ParsedMedia":
        path = Path(file_path)
        tags = _read_audio_tags(file_path)

        year = None
        raw_year = tags.get("year")
        if raw_year:
            try:
                year = int(str(raw_year)[:4])
            except (ValueError, TypeError):
                pass

        title = tags.get("title")
        if not title:
            stem = path.stem
            import re

            stem = re.sub(r"^\d{1,3}[\s.\-_]+", "", stem).strip()
            title = stem or path.name

        return ParsedMedia(
            file_path=file_path,
            title=title,
            year=year,
            media_type="music",
            artist=tags.get("artist"),
            album=tags.get("album"),
            track_number=tags.get("track_number"),
        )


# ── Scanner ───────────────────────────────────────────────────────────────────


class MediaScanner:
    """Scan directories and find valid media files."""

    def __init__(
        self,
        min_video_size_mb: float = MIN_VIDEO_SIZE_MB,
        min_audio_size_kb: float = MIN_AUDIO_SIZE_KB,
    ):
        self.supported_extensions = (
            SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS
        )
        self.parser = MediaParser()
        self.min_video_size_mb = min_video_size_mb
        self.min_audio_size_kb = min_audio_size_kb

    def is_media_file(self, path) -> bool:
        """Quick check by extension only (used in tests / watcher)."""
        return Path(path).suffix.lower() in self.supported_extensions

    def is_valid_media_file(self, path: Path) -> bool:
        """Full validation: extension, hidden files, keywords, size."""
        ext = path.suffix.lower()

        if ext not in self.supported_extensions:
            return False

        if path.name.startswith("."):
            return False

        name_lower = path.name.lower()
        if any(kw in name_lower for kw in IGNORED_KEYWORDS):
            logger.debug(f"Skipping ignored keyword: {path.name}")
            return False

        # size check — skipped entirely when threshold is 0 (tests / manual play)
        try:
            size = path.stat().st_size
            if ext in SUPPORTED_AUDIO_EXTENSIONS:
                if self.min_audio_size_kb > 0 and size < self.min_audio_size_kb * 1024:
                    logger.debug(
                        f"Skipping tiny audio file ({size / 1024:.0f} KB): {path.name}"
                    )
                    return False
            else:
                if self.min_video_size_mb > 0:
                    size_mb = size / (1024 * 1024)
                    if size_mb < self.min_video_size_mb:
                        logger.debug(
                            f"Skipping small video file ({size_mb:.1f} MB): {path.name}"
                        )
                        return False
        except OSError:
            return False

        return True

    def scan_directory(
        self, directory: str, recursive: bool = True
    ) -> List[ParsedMedia]:
        results = []
        dir_path = Path(directory)

        if not dir_path.exists():
            logger.warning(f"Directory does not exist: {dir_path}")
            return results

        logger.info(f"Scanning directory: {dir_path}")
        files = dir_path.rglob("*") if recursive else dir_path.glob("*")

        for file_path in files:
            if file_path.is_file() and self.is_valid_media_file(file_path):
                parsed = self.parser.parse(str(file_path))
                if parsed:
                    results.append(parsed)

        logger.info(f"Found {len(results)} valid media files in {dir_path}")
        return results

    def scan_directories(
        self, directories: List[str], recursive: bool = True
    ) -> List[ParsedMedia]:
        all_results = []
        for directory in directories:
            all_results.extend(self.scan_directory(directory, recursive))
        return all_results


# ── Indexer ───────────────────────────────────────────────────────────────────


class MediaIndexer:
    def __init__(self, scanner: "MediaScanner" = None):
        self.scanner = scanner or MediaScanner()

    def index_media(self, parsed: ParsedMedia, db=None) -> Optional[Media]:
        local_session = db is None
        if local_session:
            db = SessionLocal()

        try:
            media = db.query(Media).filter(Media.file_path == parsed.file_path).first()
            if not media:
                media = Media(file_path=parsed.file_path)
                db.add(media)

            media.title = parsed.title
            media.year = parsed.year
            media.media_type = parsed.media_type
            media.series_name = parsed.series
            media.season_number = parsed.season
            media.episode_number = parsed.episode
            media.episode_title = parsed.episode_title

            if parsed.media_type == "music":
                if parsed.artist:
                    media.artist = parsed.artist
                if parsed.album:
                    media.album = parsed.album
                if parsed.track_number:
                    media.track_number = parsed.track_number

            if local_session:
                db.commit()
                db.refresh(media)
            return media
        except Exception as e:
            if local_session:
                db.rollback()
            logger.error(f"Failed to index {parsed.file_path}: {e}")
            return None
        finally:
            if local_session:
                db.close()

    def index_directory(self, directory: str, recursive: bool = True) -> List[Media]:
        """Scan and index a directory using a SINGLE session."""
        parsed_list = self.scanner.scan_directory(directory, recursive)
        indexed = []

        db = SessionLocal()
        try:
            for parsed in parsed_list:
                media = self.index_media(parsed, db=db)
                if media:
                    indexed.append(media)
            db.commit()
        finally:
            db.close()
        return indexed

    def remove_media(self, file_path: str) -> bool:
        db = SessionLocal()
        try:
            media = db.query(Media).filter(Media.file_path == file_path).first()
            if media:
                db.delete(media)
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()


# ── File system watcher ───────────────────────────────────────────────────────


class MediaWatcherHandler(FileSystemEventHandler):
    def __init__(self, indexer: MediaIndexer):
        super().__init__()
        self.indexer = indexer
        self.scanner = indexer.scanner

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        if self.scanner.is_media_file(event.src_path):
            logger.info(f"New media file detected: {event.src_path}")
            parsed = self.scanner.parser.parse(event.src_path)
            if parsed:
                self.indexer.index_media(parsed)

    def on_deleted(self, event: FileDeletedEvent):
        if event.is_directory:
            return
        if self.scanner.is_media_file(event.src_path):
            logger.info(f"Media file deleted: {event.src_path}")
            self.indexer.remove_media(event.src_path)

    def on_moved(self, event: FileMovedEvent):
        if event.is_directory:
            return
        if self.scanner.is_media_file(event.src_path):
            self.indexer.remove_media(event.src_path)
        if self.scanner.is_media_file(event.dest_path):
            parsed = self.scanner.parser.parse(event.dest_path)
            if parsed:
                self.indexer.index_media(parsed)


class MediaWatcher:
    def __init__(self):
        self.indexer = MediaIndexer()
        self.observer = Observer()
        self.handler = MediaWatcherHandler(self.indexer)
        self._watched_paths: Dict[str, Any] = {}

    def watch(self, directory: str, recursive: bool = True):
        if directory in self._watched_paths:
            return
        if not os.path.exists(directory):
            logger.error(f"Directory does not exist: {directory}")
            return
        watch = self.observer.schedule(self.handler, directory, recursive=recursive)
        self._watched_paths[directory] = watch
        logger.info(f"Started watching: {directory}")

    def unwatch(self, directory: str):
        if directory in self._watched_paths:
            self.observer.unschedule(self._watched_paths[directory])
            del self._watched_paths[directory]

    def start(self):
        self.observer.start()
        logger.info("Media watcher started")

    def stop(self):
        self.observer.stop()
        self.observer.join()
        logger.info("Media watcher stopped")

    def is_running(self) -> bool:
        return self.observer.is_alive()


# ── Convenience ───────────────────────────────────────────────────────────────


def scan_and_index(directories: List[str], recursive: bool = True) -> List[Media]:
    indexer = MediaIndexer()
    all_media = []
    for directory in directories:
        all_media.extend(indexer.index_directory(directory, recursive))
    return all_media
