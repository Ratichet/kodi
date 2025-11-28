import logging
from datetime import datetime
from typing import Optional, List, Callable, Dict
from sqlalchemy.orm import Session
from sqlalchemy import or_

from core.database import SessionLocal
from core.models import Media, MediaDirectory
from core.services.scanner import MediaScanner, MediaIndexer, ParsedMedia, MediaWatcher

logger = logging.getLogger(__name__)


def _get_tmdb_enricher():
    from core.services.tmdb_service import MediaMetadataEnricher
    return MediaMetadataEnricher()


class MediaService:
    
    def __init__(self, db: Session = None):
        self._db = db
        self._owns_session = db is None
        self.indexer = MediaIndexer()
        self.watcher = MediaWatcher()
    
    @property
    def db(self) -> Session:
        if self._db is None:
            self._db = SessionLocal()
        return self._db
    
    def close(self):
        try:
            if hasattr(self, 'watcher'):
                self.watcher.stop()
        except Exception:
            pass
            
        if self._owns_session and self._db:
            self._db.close()
            self._db = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def get_all_media(self, media_type: str = None, limit: int = None) -> List[Media]:
        query = self.db.query(Media)
        if media_type:
            query = query.filter(Media.media_type == media_type)
        query = query.order_by(Media.title)
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def get_movies(self, limit: int = None) -> List[Media]:
        return self.get_all_media(media_type="movie", limit=limit)
    
    def get_episodes(self, limit: int = None) -> List[Media]:
        return self.get_all_media(media_type="episode", limit=limit)
    
    def get_recently_added(self, limit: int = 20) -> List[Media]:
        return (
            self.db.query(Media)
            .order_by(Media.created_at.desc())
            .limit(limit)
            .all()
        )
    
    def get_recently_watched(self, limit: int = 20) -> List[Media]:
        return (
            self.db.query(Media)
            .filter(Media.last_played.isnot(None))
            .order_by(Media.last_played.desc())
            .limit(limit)
            .all()
        )
    
    def get_in_progress(self, limit: int = 20) -> List[Media]:
        #get media in progress
        return (
            self.db.query(Media)
            .filter(Media.resume_position > 0)
            .filter(Media.is_watched == False)
            .order_by(Media.last_played.desc())
            .limit(limit)
            .all()
        )
    
    def get_media_by_id(self, media_id: int) -> Optional[Media]:
        #get media by id
        return self.db.query(Media).filter(Media.id == media_id).first()
    
    def get_media_by_path(self, file_path: str) -> Optional[Media]:
        #get media by path
        return self.db.query(Media).filter(Media.file_path == file_path).first()
    
    def search_media(self, query: str, limit: int = 50) -> List[Media]:
        #search media by title
        search_term = f"%{query}%"
        return (
            self.db.query(Media)
            .filter(
                or_(
                    Media.title.ilike(search_term),
                    Media.series_name.ilike(search_term),
                )
            )
            .order_by(Media.title)
            .limit(limit)
            .all()
        )
    
    def filter_media(
        self,
        media_type: str = None,
        year: int = None,
        genre: str = None,
        is_watched: bool = None,
    ) -> List[Media]:
        #filter
        query = self.db.query(Media)
        
        if media_type:
            query = query.filter(Media.media_type == media_type)
        if year:
            query = query.filter(Media.year == year)
        if genre:
            query = query.filter(Media.genres.ilike(f"%{genre}%"))
        if is_watched is not None:
            query = query.filter(Media.is_watched == is_watched)
        
        return query.order_by(Media.title).all()

    def update_progress(self, media_id: int, position_ms: int, duration_ms: int = None):
        # update resume position"
        media = self.get_media_by_id(media_id)
        if not media:
            logger.warning(f"Media not found: {media_id}")
            return
        
        media.resume_position = position_ms
        media.last_played = datetime.now()
        
        if duration_ms:
            media.duration_sec = duration_ms // 1000
            # mark as watched if near the end (>90%)
            if position_ms >= duration_ms * 0.9:
                media.is_watched = True
                media.watch_count += 1
                media.resume_position = 0
        
        self.db.commit()
        logger.debug(f"Updated progress for '{media.title}': {position_ms}ms")
    
    def mark_as_watched(self, media_id: int):
        media = self.get_media_by_id(media_id)
        if media:
            media.is_watched = True
            media.watch_count += 1
            media.resume_position = 0
            media.last_played = datetime.now()
            self.db.commit()
    
    def add_media_directory(self, path: str, recursive: bool = True) -> MediaDirectory:
        existing = self.db.query(MediaDirectory).filter(MediaDirectory.path == path).first()
        if existing:
            existing.is_active = True
            self.db.commit()
            return existing
        
        directory = MediaDirectory(path=path, recursive=recursive)
        self.db.add(directory)
        self.db.commit()
        self.db.refresh(directory)

        if self.watcher.is_running():
            self.watcher.watch(path, recursive=recursive)
            
        return directory
    
    def get_media_directories(self, active_only: bool = True) -> List[MediaDirectory]:
        query = self.db.query(MediaDirectory)
        if active_only:
            query = query.filter(MediaDirectory.is_active == True)
        return query.all()
    
    def remove_media_directory(self, directory_id: int) -> bool:
        directory = self.db.query(MediaDirectory).filter(MediaDirectory.id == directory_id).first()
        if directory:
            if self.watcher.is_running():
                self.watcher.unwatch(directory.path)
            self.db.delete(directory)
            self.db.commit()
            return True
        return False
    
    def scan_all_directories(self) -> List[Media]:
        #scan all directories set
        self.cleanup_library()
        directories = self.get_media_directories(active_only=True)
        all_media = []
        for directory in directories:
            media = self.indexer.index_directory(directory.path, directory.recursive)
            all_media.extend(media)
            directory.last_scanned = datetime.now()
            self.db.commit()
        return all_media
    
    def get_stats(self) -> dict:
        #get library stats
        return {
            "total_media": self.db.query(Media).count(),
            "movies": self.db.query(Media).filter(Media.media_type == "movie").count(),
            "episodes": self.db.query(Media).filter(Media.media_type == "episode").count(),
            "watched": self.db.query(Media).filter(Media.is_watched == True).count(),
            "in_progress": self.db.query(Media).filter(
                Media.resume_position > 0,
                Media.is_watched == False
            ).count(),
            "with_metadata": self.db.query(Media).filter(Media.tmdb_id.isnot(None)).count(),
        }
    
    def cleanup_library(self) -> int:
        #remove media who dont exist anymore
        import os
        all_media = self.db.query(Media).all()
        removed_count = 0
        
        for media in all_media:
            if not os.path.exists(media.file_path):
                logger.info(f"Files removed :{media.file_path}")
                self.db.delete(media)
                removed_count += 1
        
        if removed_count > 0:
            self.db.commit()
            logger.info(f"cleaned {removed_count} entries removed from library.")
            
        return removed_count
    
    #TMDB enrichment
    def enrich_all_media(self, limit: int = None, progress_callback: Callable = None) -> dict:
        query = self.db.query(Media).filter(Media.tmdb_id.is_(None))
        if limit: query = query.limit(limit)
        
        media_list = query.all()
        total = len(media_list)
        stats = {"success": 0, "failed": 0}
        enricher = _get_tmdb_enricher()
        
        for i, media in enumerate(media_list, 1):
            if progress_callback: progress_callback(i, total, media.title or media.file_path)
            if enricher.enrich_media(media):
                stats["success"] += 1
            else:
                stats["failed"] += 1
        return stats

    def download_all_posters(self) -> dict:
        enricher = _get_tmdb_enricher()
        return enricher.download_all_posters()

    def reset_database(self) -> bool:
        try:
            from core.database import Base, engine
            self.close()
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            logger.info("Database reset successfully.")
            return True
        except Exception as e:
            logger.error(f"error resetting database:{e}")
            return False