import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileDeletedEvent, FileMovedEvent
import guessit

from core.config import SUPPORTED_VIDEO_EXTENSIONS, SUPPORTED_AUDIO_EXTENSIONS
from core.database import SessionLocal
from core.models import Media

logger = logging.getLogger(__name__)

# Config scanner
MIN_VIDEO_SIZE_MB = 50 #ignore 50mb< videos
IGNORED_KEYWORDS = ["sample", "trailer", "featurette", "extra", "scene"]

@dataclass
class ParsedMedia:
    #parsed media info from filename wih guessit
    file_path: str
    title: str
    year: Optional[int] = None
    media_type: str = "movie"  # movie, episode
    #series info
    series: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: Optional[str] = None
    #useless info (for now)
    quality: Optional[str] = None
    source: Optional[str] = None
    
    def get_search_title(self) -> str:
        #get clean title for tmdb search
        if self.media_type == "episode" and self.series:
            return self.series
        return self.title


class MediaParser:
    #use guessit to parse media file names
    @staticmethod
    def parse(file_path: str) -> Optional[ParsedMedia]:
        try:
            filename = os.path.basename(file_path)
            guess = guessit.guessit(filename)
            
            media_type = guess.get("type", "movie")
            
            parsed = ParsedMedia(
                file_path=file_path,
                title=guess.get("title", Path(file_path).stem),
                year=guess.get("year"),
                media_type=media_type,
                series=guess.get("title") if media_type == "episode" else None,
                season=guess.get("season"),
                episode=guess.get("episode"),
                episode_title=guess.get("episode_title"),
                quality=guess.get("screen_size"),
                source=guess.get("source"),
            )
            return parsed
        except Exception as e:
            logger.error(f"Failed to parse '{file_path}': {e}")
            return None


class MediaScanner:
    #scan directories for find media
    def __init__(self):
        self.supported_extensions = SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS
        self.parser = MediaParser()
    
    def is_valid_media_file(self, path: Path) -> bool:
        # extension
        if path.suffix.lower() not in self.supported_extensions:
            return False
            
        # hidden files
        if path.name.startswith('.'):
            return False

        # ignored keywords
        name_lower = path.name.lower()
        if any(keyword in name_lower for keyword in IGNORED_KEYWORDS):
            logger.debug(f"Skipping ignored keyword: {path.name}")
            return False
            
        # skip lite files (probably not real media)
        try:
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb < MIN_VIDEO_SIZE_MB:
                logger.debug(f"Skipping small file ({size_mb:.1f} MB): {path.name}")
                return False
        except OSError:
            return False
            
        return True
    
    def scan_directory(self, directory: str, recursive: bool = True) -> List[ParsedMedia]:
        results = []
        dir_path = Path(directory)
        
        if not dir_path.exists():
            logger.warning(f"Directory does not exist: {dir_path}")
            return results
        
        logger.info(f"Scanning directory: {dir_path}")
        
        if recursive:
            files = dir_path.rglob("*")
        else:
            files = dir_path.glob("*")
        
        for file_path in files:
            if file_path.is_file() and self.is_valid_media_file(file_path):
                parsed = self.parser.parse(str(file_path))
                if parsed:
                    results.append(parsed)
        
        logger.info(f"Found {len(results)} valid media files in {dir_path}")
        return results
    
    def scan_directories(self, directories: List[str], recursive: bool = True) -> List[ParsedMedia]:
        all_results = []
        for directory in directories:
            results = self.scan_directory(directory, recursive)
            all_results.extend(results)
        return all_results

class MediaIndexer:
    def __init__(self):
        self.scanner = MediaScanner()
    
    def index_media(self, parsed: ParsedMedia, db=None) -> Optional[Media]:
        # On utilise la session passée en paramètre ou on en crée une nouvelle
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

            if local_session:
                db.commit()
                db.refresh(media)
            return media
        except Exception as e:
            if local_session: db.rollback()
            logger.error(f"Failed to index {parsed.file_path}: {e}")
            return None
        finally:
            if local_session: db.close()

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


class MediaWatcherHandler(FileSystemEventHandler):
    """Handles file system events for media files."""
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
        
        # handle source deletion
        if self.scanner.is_media_file(event.src_path):
            self.indexer.remove_media(event.src_path)
        
        if self.scanner.is_media_file(event.dest_path):
            parsed = self.scanner.parser.parse(event.dest_path)
            if parsed:
                self.indexer.index_media(parsed)


class MediaWatcher:
    #watch directories for changes and update index
    
    def __init__(self):
        self.indexer = MediaIndexer()
        self.observer = Observer()
        self.handler = MediaWatcherHandler(self.indexer)
        self._watched_paths: Dict[str, Any] = {}
    
    def watch(self, directory: str, recursive: bool = True):
        """
        Start watching a directory for changes.
        
        Args:
            directory: Path to watch
            recursive: Whether to watch subdirectories
        """
        if directory in self._watched_paths:
            logger.warning(f"Already watching: {directory}")
            return
        
        if not os.path.exists(directory):
            logger.error(f"Directory does not exist: {directory}")
            return
        
        watch = self.observer.schedule(self.handler, directory, recursive=recursive)
        self._watched_paths[directory] = watch
        logger.info(f"Started watching: {directory}")
    
    def unwatch(self, directory: str):
        """Stop watching a directory."""
        if directory in self._watched_paths:
            self.observer.unschedule(self._watched_paths[directory])
            del self._watched_paths[directory]
            logger.info(f"Stopped watching: {directory}")
    
    def start(self):
        """Start the file system observer."""
        self.observer.start()
        logger.info("Media watcher started")
    
    def stop(self):
        """Stop the file system observer."""
        self.observer.stop()
        self.observer.join()
        logger.info("Media watcher stopped")
    
    def is_running(self) -> bool:
        """Check if the observer is running."""
        return self.observer.is_alive()


# Convenience function for quick scanning
def scan_and_index(directories: List[str], recursive: bool = True) -> List[Media]:
    """
    Convenience function to scan and index media from directories.
    
    Args:
        directories: List of directory paths to scan
        recursive: Whether to scan subdirectories
        
    Returns:
        List of indexed Media objects
    """
    indexer = MediaIndexer()
    all_media = []
    
    for directory in directories:
        media = indexer.index_directory(directory, recursive)
        all_media.extend(media)
    
    return all_media