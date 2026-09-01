import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.models import Media, MediaDirectory
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
        self._watcher = None

    @property
    def db(self) -> Session:
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    @property
    def watcher(self) -> MediaWatcher:
        # Créé à la demande : un MediaWatcher alloue un thread Observer, inutile
        # tant que personne ne surveille de dossier.
        if self._watcher is None:
            self._watcher = MediaWatcher()
        return self._watcher

    def close(self):
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except Exception as e:
                logger.warning(f"Could not stop media watcher: {e}")
            self._watcher = None
        if self._owns_session and self._db:
            self._db.close()
            self._db = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_all_media(self, media_type: str = None, limit: int = None) -> list[Media]:
        query = self.db.query(Media)
        if media_type:
            query = query.filter(Media.media_type == media_type)
        query = query.order_by(Media.title)
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_movies(self, limit: int = None) -> list[Media]:
        return self.get_all_media(media_type="movie", limit=limit)

    def get_episodes(self, limit: int = None) -> list[Media]:
        return self.get_all_media(media_type="episode", limit=limit)

    def get_series_episodes(self, series_name: str) -> list[Media]:
        """Tous les épisodes d'une série, triés par saison puis numéro."""
        return (
            self.db.query(Media)
            .filter(Media.media_type == "episode")
            .filter(Media.series_name == series_name)
            .order_by(
                Media.season_number.nullsfirst(),
                Media.episode_number.nullsfirst(),
            )
            .all()
        )

    def get_recently_added(self, limit: int = 20) -> list[Media]:
        return self.db.query(Media).order_by(Media.created_at.desc()).limit(limit).all()

    def get_recently_watched(self, limit: int = 20) -> list[Media]:
        return (
            self.db.query(Media)
            .filter(Media.last_played.isnot(None))
            .order_by(Media.last_played.desc())
            .limit(limit)
            .all()
        )

    def get_in_progress(self, limit: int = 20) -> list[Media]:
        return (
            self.db.query(Media)
            .filter(Media.resume_position > 0)
            .filter(Media.is_watched == False)
            .order_by(Media.last_played.desc())
            .limit(limit)
            .all()
        )

    def get_media_by_id(self, media_id: int) -> Media | None:
        return self.db.query(Media).filter(Media.id == media_id).first()

    def get_media_by_path(self, file_path: str) -> Media | None:
        return self.db.query(Media).filter(Media.file_path == file_path).first()

    def search_media(self, query: str, limit: int = 50) -> list[Media]:
        # Les motifs par début de mot ci-dessous ne supportent pas une espace
        # de tête : « % hanks% » ne rencontrerait jamais « Tom Hanks ».
        query = query.strip()
        search_term = f"%{query}%"
        return (
            self.db.query(Media)
            .filter(
                or_(
                    Media.title.ilike(search_term),
                    Media.series_name.ilike(search_term),
                    Media.episode_title.ilike(search_term),
                    # Les acteurs se cherchent par début de mot, comme dans les
                    # vues : « an » ne doit pas ramener toutes les Susan. Les noms
                    # sont séparés par « , », un début de nom suit donc un espace.
                    Media.actors.ilike(f"{query}%"),
                    Media.actors.ilike(f"% {query}%"),
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
    ) -> list[Media]:
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
            if position_ms >= duration_ms * 0.9 and not media.is_watched:
                media.is_watched = True
                media.watch_count = (media.watch_count or 0) + 1
                media.resume_position = 0
        self.db.commit()

    def mark_as_watched(self, media_id: int):
        media = self.get_media_by_id(media_id)
        if media:
            media.is_watched = True
            media.watch_count = (media.watch_count or 0) + 1
            media.resume_position = 0
            media.last_played = datetime.now()
            self.db.commit()

    def mark_as_unwatched(self, media_id: int):
        media = self.get_media_by_id(media_id)
        if media:
            media.is_watched = False
            media.watch_count = 0
            media.resume_position = 0
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
        if self._watcher is not None:
            self._watcher.watch(path, recursive=recursive)
            # Premier dossier ajouté après le démarrage : rien n'était surveillé.
            if not self._watcher.is_running():
                self._watcher.start()
        return directory

    def get_media_directories(self, active_only: bool = True) -> list[MediaDirectory]:
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
            if self._watcher is not None:
                self._watcher.unwatch(directory.path)
            self.db.delete(directory)
            self.db.commit()
            return True
        return False

    def start_watching(
        self, on_change: Callable = None, auto_enrich: bool = True
    ) -> bool:
        """Surveille en temps réel les dossiers actifs de la bibliothèque.

        `on_change` est appelé depuis le thread de surveillance après chaque
        modification effective ; il doit être sûr hors du thread appelant.
        Renvoie False s'il n'y a aucun dossier à surveiller.
        """
        watcher = self.watcher
        watcher.set_on_change(on_change)
        watcher.auto_enrich = auto_enrich
        for directory in self.get_media_directories(active_only=True):
            watcher.watch(directory.path, recursive=bool(directory.recursive))
        return watcher.start()

    def stop_watching(self):
        if self._watcher is not None:
            self._watcher.stop()

    def is_watching(self) -> bool:
        return self._watcher is not None and self._watcher.is_running()

    def scan_all_directories(self) -> list[Media]:
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
        return {
            "total_media": self.db.query(Media).count(),
            "movies": self.db.query(Media).filter(Media.media_type == "movie").count(),
            "episodes": self.db.query(Media)
            .filter(Media.media_type == "episode")
            .count(),
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
        # Session dédiée : cette méthode est appelée depuis un thread de travail,
        # une Session SQLAlchemy ne peut pas être partagée entre threads.
        db = SessionLocal()
        try:
            query = db.query(Media).filter(Media.tmdb_id.is_(None))
            if limit:
                query = query.limit(limit)
            media_list = query.all()
            total = len(media_list)
            stats = {"success": 0, "failed": 0}
            enricher = _get_tmdb_enricher()
            for i, media in enumerate(media_list, 1):
                if progress_callback:
                    progress_callback(i, total, media.title or media.file_path)
                if enricher.enrich_media(media, db=db):
                    stats["success"] += 1
                else:
                    stats["failed"] += 1
            return stats
        finally:
            db.close()

    def re_enrich_all_media(
        self, progress_callback: Callable = None
    ) -> dict:
        db = SessionLocal()
        try:
            media_list = db.query(Media).filter(Media.tmdb_id.isnot(None)).all()
            total = len(media_list)
            stats = {"success": 0, "failed": 0}
            enricher = _get_tmdb_enricher()
            for i, media in enumerate(media_list, 1):
                if progress_callback:
                    progress_callback(i, total, media.title or media.file_path)
                if enricher.re_enrich_media(media, db=db):
                    stats["success"] += 1
                else:
                    stats["failed"] += 1
            return stats
        finally:
            db.close()

    def fill_missing_details(self, progress_callback: Callable = None) -> dict:
        enricher = _get_tmdb_enricher()
        return enricher.fill_missing_details(progress_callback=progress_callback)

    def download_all_artwork(self, progress_callback: Callable = None) -> dict:
        enricher = _get_tmdb_enricher()
        return enricher.download_all_artwork(progress_callback=progress_callback)

    def reset_database(self) -> bool:
        try:
            from core.database import Base, engine

            # La session courante doit être fermée avant de supprimer les tables,
            # sinon elle garde des objets pointant sur des lignes disparues.
            if self._owns_session and self._db:
                self._db.close()
                self._db = None
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            logger.info("Database reset successfully.")
            return True
        except Exception as e:
            logger.error(f"Error resetting database: {e}")
            return False
