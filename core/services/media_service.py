import logging
from datetime import datetime
from typing import Optional, List, Callable
from sqlalchemy.orm import Session
from sqlalchemy import or_

from core.database import SessionLocal
from core.models import Media, MediaDirectory, Playlist, PlaylistItem
from core.services.scanner import MediaIndexer, MediaWatcher

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
            if hasattr(self, "watcher"):
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

    def get_music(self, limit: int = None) -> List[Media]:
        query = (
            self.db.query(Media)
            .filter(Media.media_type == "music")
            .order_by(
                Media.artist.nullslast(),
                Media.album.nullslast(),
                Media.track_number.nullslast(),
                Media.title,
            )
        )
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_music_artists(self) -> List[str]:
        rows = (
            self.db.query(Media.artist)
            .filter(Media.media_type == "music")
            .filter(Media.artist.isnot(None))
            .distinct()
            .order_by(Media.artist)
            .all()
        )
        return [r[0] for r in rows]

    def get_music_albums(self, artist: str = None) -> List[str]:
        query = (
            self.db.query(Media.album)
            .filter(Media.media_type == "music")
            .filter(Media.album.isnot(None))
        )
        if artist:
            query = query.filter(Media.artist == artist)
        rows = query.distinct().order_by(Media.album).all()
        return [r[0] for r in rows]

    def get_recently_added(self, limit: int = 20) -> List[Media]:
        return self.db.query(Media).order_by(Media.created_at.desc()).limit(limit).all()

    def get_recently_watched(self, limit: int = 20) -> List[Media]:
        return (
            self.db.query(Media)
            .filter(Media.last_played.isnot(None))
            .order_by(Media.last_played.desc())
            .limit(limit)
            .all()
        )

    def get_in_progress(self, limit: int = 20) -> List[Media]:
        return (
            self.db.query(Media)
            .filter(Media.resume_position > 0)
            .filter(Media.is_watched == False)
            .order_by(Media.last_played.desc())
            .limit(limit)
            .all()
        )

    def get_media_by_id(self, media_id: int) -> Optional[Media]:
        return self.db.query(Media).filter(Media.id == media_id).first()

    def get_media_by_path(self, file_path: str) -> Optional[Media]:
        return self.db.query(Media).filter(Media.file_path == file_path).first()

    def search_media(self, query: str, limit: int = 50) -> List[Media]:
        search_term = f"%{query}%"
        return (
            self.db.query(Media)
            .filter(
                or_(
                    Media.title.ilike(search_term),
                    Media.series_name.ilike(search_term),
                    Media.artist.ilike(search_term),
                    Media.album.ilike(search_term),
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
        media = self.get_media_by_id(media_id)
        if not media:
            return
        media.resume_position = position_ms
        media.last_played = datetime.now()
        if duration_ms:
            media.duration_sec = duration_ms // 1000
            if position_ms >= duration_ms * 0.9:
                media.is_watched = True
                media.watch_count += 1
                media.resume_position = 0
        self.db.commit()

    def mark_as_watched(self, media_id: int):
        media = self.get_media_by_id(media_id)
        if media:
            media.is_watched = True
            media.watch_count += 1
            media.resume_position = 0
            media.last_played = datetime.now()
            self.db.commit()

    def add_media_directory(self, path: str, recursive: bool = True) -> MediaDirectory:
        existing = (
            self.db.query(MediaDirectory).filter(MediaDirectory.path == path).first()
        )
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
        directory = (
            self.db.query(MediaDirectory)
            .filter(MediaDirectory.id == directory_id)
            .first()
        )
        if directory:
            if self.watcher.is_running():
                self.watcher.unwatch(directory.path)
            self.db.delete(directory)
            self.db.commit()
            return True
        return False

    def scan_all_directories(self) -> List[Media]:
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
        music_count = self.db.query(Media).filter(Media.media_type == "music").count()
        return {
            "total_media": self.db.query(Media).count(),
            "movies": self.db.query(Media).filter(Media.media_type == "movie").count(),
            "episodes": self.db.query(Media)
            .filter(Media.media_type == "episode")
            .count(),
            "music": music_count,
            "watched": self.db.query(Media).filter(Media.is_watched == True).count(),
            "in_progress": self.db.query(Media)
            .filter(Media.resume_position > 0, Media.is_watched == False)
            .count(),
            "with_metadata": self.db.query(Media)
            .filter(Media.tmdb_id.isnot(None))
            .count(),
        }

    def cleanup_library(self) -> int:
        import os

        all_media = self.db.query(Media).all()
        removed_count = 0
        for media in all_media:
            if not os.path.exists(media.file_path):
                logger.info(f"File removed: {media.file_path}")
                self.db.delete(media)
                removed_count += 1
        if removed_count > 0:
            self.db.commit()
        return removed_count

    def enrich_all_media(
        self, limit: int = None, progress_callback: Callable = None
    ) -> dict:
        query = self.db.query(Media).filter(
            Media.tmdb_id.is_(None),
            Media.media_type != "music",
        )
        if limit:
            query = query.limit(limit)
        media_list = query.all()
        total = len(media_list)
        stats = {"success": 0, "failed": 0}
        enricher = _get_tmdb_enricher()
        for i, media in enumerate(media_list, 1):
            if progress_callback:
                progress_callback(i, total, media.title or media.file_path)
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
            logger.error(f"Error resetting database: {e}")
            return False

    def get_playlists(self) -> List[Playlist]:
        return self.db.query(Playlist).order_by(Playlist.name).all()

    def get_playlist(self, playlist_id: int) -> Optional[Playlist]:
        return self.db.query(Playlist).filter(Playlist.id == playlist_id).first()

    def create_playlist(self, name: str, description: str = "") -> Playlist:
        pl = Playlist(name=name, description=description)
        self.db.add(pl)
        self.db.commit()
        self.db.refresh(pl)
        logger.info(f"Playlist created: '{name}' (id={pl.id})")
        return pl

    def rename_playlist(self, playlist_id: int, new_name: str) -> bool:
        pl = self.get_playlist(playlist_id)
        if not pl:
            return False
        pl.name = new_name
        self.db.commit()
        return True

    def delete_playlist(self, playlist_id: int) -> bool:
        pl = self.get_playlist(playlist_id)
        if not pl:
            return False
        self.db.delete(pl)
        self.db.commit()
        logger.info(f"Playlist deleted: id={playlist_id}")
        return True

    def add_to_playlist(
        self, playlist_id: int, media_id: int
    ) -> Optional[PlaylistItem]:
        """Append a media to a playlist (avoids duplicates)."""
        pl = self.get_playlist(playlist_id)
        if not pl:
            return None
        # duplicate check
        existing = (
            self.db.query(PlaylistItem)
            .filter(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.media_id == media_id,
            )
            .first()
        )
        if existing:
            return existing
        next_pos = len(pl.items)
        item = PlaylistItem(
            playlist_id=playlist_id, media_id=media_id, position=next_pos
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def remove_from_playlist(self, playlist_id: int, media_id: int) -> bool:
        item = (
            self.db.query(PlaylistItem)
            .filter(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.media_id == media_id,
            )
            .first()
        )
        if not item:
            return False
        self.db.delete(item)
        remaining = (
            self.db.query(PlaylistItem)
            .filter(PlaylistItem.playlist_id == playlist_id)
            .order_by(PlaylistItem.position)
            .all()
        )
        for i, r in enumerate(remaining):
            r.position = i
        self.db.commit()
        return True

    def reorder_playlist(self, playlist_id: int, ordered_media_ids: List[int]) -> bool:
        items = (
            self.db.query(PlaylistItem)
            .filter(PlaylistItem.playlist_id == playlist_id)
            .all()
        )
        item_map = {i.media_id: i for i in items}
        for pos, mid in enumerate(ordered_media_ids):
            if mid in item_map:
                item_map[mid].position = pos
        self.db.commit()
        return True

    def get_playlist_tracks(self, playlist_id: int) -> List[Media]:
        items = (
            self.db.query(PlaylistItem)
            .filter(PlaylistItem.playlist_id == playlist_id)
            .order_by(PlaylistItem.position)
            .all()
        )
        return [item.media for item in items if item.media]
