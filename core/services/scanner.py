import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import guessit
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from core.config import SUPPORTED_VIDEO_EXTENSIONS
from core.database import SessionLocal
from core.models import Media

logger = logging.getLogger(__name__)

MIN_VIDEO_SIZE_MB = 50
IGNORED_KEYWORDS = ["sample", "trailer", "featurette", "extra", "scene"]


@dataclass
class ParsedMedia:

    file_path: str
    title: str
    year: int | None = None
    media_type: str = "movie"  # movie | episode
    # series info
    series: str | None = None
    season: int | None = None
    episode: int | None = None
    episode_title: str | None = None
    # quality / source
    quality: str | None = None
    source: str | None = None

    def get_search_title(self) -> str:
        """Return a clean title suitable for TMDb search."""
        if self.media_type == "episode" and self.series:
            return self.series
        return self.title


class MediaParser:
    @staticmethod
    def parse(file_path: str) -> Optional["ParsedMedia"]:
        try:
            path = Path(file_path)
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

class MediaScanner:
    """Scan directories and find valid media files."""

    def __init__(self, min_video_size_mb: float = MIN_VIDEO_SIZE_MB):
        self.supported_extensions = set(SUPPORTED_VIDEO_EXTENSIONS)
        self.parser = MediaParser()
        self.min_video_size_mb = min_video_size_mb

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
            if self.min_video_size_mb > 0:
                size_mb = path.stat().st_size / (1024 * 1024)
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
    ) -> list[ParsedMedia]:
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
        self, directories: list[str], recursive: bool = True
    ) -> list[ParsedMedia]:
        all_results = []
        for directory in directories:
            all_results.extend(self.scan_directory(directory, recursive))
        return all_results


# ── Indexer ───────────────────────────────────────────────────────────────────


class MediaIndexer:
    def __init__(self, scanner: "MediaScanner" = None):
        self.scanner = scanner or MediaScanner()

    def index_media(self, parsed: ParsedMedia, db=None) -> Media | None:
        local_session = db is None
        if local_session:
            db = SessionLocal()

        try:
            media = db.query(Media).filter(Media.file_path == parsed.file_path).first()
            if not media:
                media = Media(file_path=parsed.file_path)
                db.add(media)

            # Une fiche déjà enrichie fait autorité sur le nom du fichier.
            # « South.Park.S15E01.mkv » ne porte aucun titre d'épisode : réindexer
            # écrasait celui de TMDb par un None, et il ne revenait jamais puisque
            # l'enrichissement ignore les médias ayant déjà un tmdb_id.
            enriched = media.tmdb_id is not None
            for field, value in (
                ("title", parsed.title),
                ("year", parsed.year),
                ("media_type", parsed.media_type),
                ("series_name", parsed.series),
                ("season_number", parsed.season),
                ("episode_number", parsed.episode),
                ("episode_title", parsed.episode_title),
            ):
                if value is None or (enriched and getattr(media, field) is not None):
                    continue
                setattr(media, field, value)

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

    def index_directory(self, directory: str, recursive: bool = True) -> list[Media]:
        """Scan and index a directory using a SINGLE session.

        Les objets renvoyés sont détachés : `expire_on_commit=False` conserve les
        attributs chargés, sinon le moindre accès après la fermeture de la session
        lèverait DetachedInstanceError.
        """
        parsed_list = self.scanner.scan_directory(directory, recursive)
        indexed = []

        db = SessionLocal(expire_on_commit=False)
        try:
            for parsed in parsed_list:
                media = self.index_media(parsed, db=db)
                if media:
                    indexed.append(media)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to index directory '{directory}': {e}")
            indexed = []
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
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to remove '{file_path}': {e}")
            return False
        finally:
            db.close()

    def remove_media_under(self, directory: str) -> int:
        """Supprime toutes les entrées situées sous `directory`.

        Utilisé quand un dossier entier est supprimé ou déplacé : le système de
        fichiers n'émet alors qu'un seul événement pour le dossier.
        """
        prefix = os.path.join(os.path.abspath(directory), "")
        db = SessionLocal()
        try:
            # autoescape : un chemin contenant « _ » ou « % » est un motif LIKE valide.
            medias = (
                db.query(Media)
                .filter(Media.file_path.startswith(prefix, autoescape=True))
                .all()
            )
            for media in medias:
                db.delete(media)
            if medias:
                db.commit()
            return len(medias)
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to remove media under '{directory}': {e}")
            return 0
        finally:
            db.close()


# ── File system watcher ───────────────────────────────────────────────────────


SETTLE_INTERVAL_SEC = 2.0


class MediaWatcherHandler(FileSystemEventHandler):
    """Traduit les événements watchdog en demandes de traitement.

    Rien n'est indexé ici : `on_created` se déclenche dès le premier octet écrit,
    donc pendant une copie en cours. Les chemins sont mis en file d'attente et
    MediaWatcher ne les traite qu'une fois leur taille stabilisée.
    """

    def __init__(self, watcher: "MediaWatcher"):
        super().__init__()
        self.watcher = watcher

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            self.watcher.queue_directory(event.src_path)
        else:
            self.watcher.queue_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.watcher.queue_file(event.src_path)

    def on_deleted(self, event: FileDeletedEvent):
        if event.is_directory:
            self.watcher.drop_directory(event.src_path)
        else:
            self.watcher.drop_file(event.src_path)

    def on_moved(self, event: FileMovedEvent):
        if event.is_directory:
            self.watcher.drop_directory(event.src_path)
            self.watcher.queue_directory(event.dest_path)
        else:
            self.watcher.drop_file(event.src_path)
            self.watcher.queue_file(event.dest_path)


class MediaWatcher:
    """Surveille des dossiers et tient la bibliothèque à jour en temps réel.

    Un fichier n'est indexé qu'une fois sa taille inchangée sur deux passes
    consécutives, sinon une copie en cours serait indexée à 0 octet puis rejetée
    par le contrôle de taille sans jamais être réexaminée.

    `on_change` est appelé depuis le thread de surveillance à chaque modification
    effective de la bibliothèque : à l'appelant de repasser dans son propre thread
    (signal Qt côté interface).
    """

    def __init__(
        self,
        on_change: Callable[[], None] = None,
        settle_interval: float = SETTLE_INTERVAL_SEC,
        auto_enrich: bool = False,
    ):
        self.indexer = MediaIndexer()
        self.handler = MediaWatcherHandler(self)
        self.auto_enrich = auto_enrich
        self.observer = None
        self._on_change = on_change
        self._settle_interval = settle_interval
        self._watch_specs: dict[str, bool] = {}  # dossier -> récursif (état voulu)
        self._watches: dict[str, Any] = {}  # dossier -> ObservedWatch (état réel)
        self._pending: dict[str, int | None] = {}  # chemin -> dernière taille vue
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._settle_thread = None

    @property
    def scanner(self) -> MediaScanner:
        return self.indexer.scanner

    def set_on_change(self, callback: Callable[[], None] = None):
        self._on_change = callback

    # ── Dossiers surveillés ───────────────────────────────────────────────────

    def watch(self, directory: str, recursive: bool = True) -> bool:
        directory = os.path.abspath(directory)
        if not os.path.isdir(directory):
            logger.error(f"Directory does not exist: {directory}")
            return False

        self._watch_specs[directory] = recursive
        if self.is_running() and directory not in self._watches:
            self._schedule(directory, recursive)
        return True

    def unwatch(self, directory: str):
        directory = os.path.abspath(directory)
        self._watch_specs.pop(directory, None)
        watch = self._watches.pop(directory, None)
        if watch is not None and self.is_running():
            try:
                self.observer.unschedule(watch)
            except Exception as e:
                logger.warning(f"Could not unschedule {directory}: {e}")
        logger.info(f"Stopped watching: {directory}")

    def watched_directories(self) -> list[str]:
        return sorted(self._watches)

    def _schedule(self, directory: str, recursive: bool):
        try:
            self._watches[directory] = self.observer.schedule(
                self.handler, directory, recursive=recursive
            )
            logger.info(f"Started watching: {directory}")
        except OSError as e:
            logger.error(f"Could not watch {directory}: {e}")

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    def start(self) -> bool:
        if self.is_running():
            return True
        if not self._watch_specs:
            logger.info("Media watcher: no directory to watch.")
            return False

        self._stop_event.clear()
        # Un Observer arrêté est un thread mort : il en faut un neuf à chaque start.
        self.observer = Observer()
        self._watches.clear()
        for directory, recursive in list(self._watch_specs.items()):
            self._schedule(directory, recursive)

        if not self._watches:
            self.observer = None
            return False

        self.observer.start()
        self._settle_thread = threading.Thread(
            target=self._settle_loop, name="epikodi-watcher-settle", daemon=True
        )
        self._settle_thread.start()
        logger.info(f"Media watcher started on {len(self._watches)} directory(ies)")
        return True

    def stop(self):
        self._stop_event.set()

        thread, self._settle_thread = self._settle_thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._settle_interval * 2)

        observer, self.observer = self.observer, None
        self._watches.clear()
        with self._lock:
            self._pending.clear()

        # join() sur un Observer jamais démarré lève RuntimeError.
        if observer is not None and observer.is_alive():
            observer.stop()
            observer.join(timeout=5)
            logger.info("Media watcher stopped")

    def is_running(self) -> bool:
        return self.observer is not None and self.observer.is_alive()

    # ── File d'attente ────────────────────────────────────────────────────────

    def queue_file(self, path):
        path = os.fspath(path)
        if not self.scanner.is_media_file(path):
            return
        with self._lock:
            self._pending.setdefault(path, None)

    def queue_directory(self, path):
        """Met en file tous les médias d'un dossier ajouté ou déplacé d'un bloc."""
        try:
            for entry in Path(path).rglob("*"):
                if entry.is_file():
                    self.queue_file(str(entry))
        except OSError as e:
            logger.warning(f"Could not walk {path}: {e}")

    def drop_file(self, path):
        path = os.fspath(path)
        with self._lock:
            self._pending.pop(path, None)
        if not self.scanner.is_media_file(path):
            return
        if self.indexer.remove_media(path):
            logger.info(f"Media file removed from library: {path}")
            self._notify()

    def drop_directory(self, path):
        path = os.fspath(path)
        prefix = os.path.join(os.path.abspath(path), "")
        with self._lock:
            for pending in [p for p in self._pending if os.path.abspath(p).startswith(prefix)]:
                self._pending.pop(pending, None)
        removed = self.indexer.remove_media_under(path)
        if removed:
            logger.info(f"Removed {removed} media item(s) under: {path}")
            self._notify()

    # ── Traitement différé ────────────────────────────────────────────────────

    def _settle_loop(self):
        while not self._stop_event.wait(self._settle_interval):
            try:
                self._process_pending()
            except Exception as e:
                logger.error(f"Watcher settle pass failed: {e}", exc_info=True)

    def _process_pending(self):
        with self._lock:
            snapshot = dict(self._pending)
        if not snapshot:
            return

        indexed_ids = []
        for path, previous_size in snapshot.items():
            try:
                size = os.path.getsize(path)
            except OSError:
                # Disparu ou verrouillé : la suppression passe par on_deleted.
                with self._lock:
                    self._pending.pop(path, None)
                continue

            if size != previous_size:
                # Toujours en cours d'écriture : on réessaie à la passe suivante.
                with self._lock:
                    if path in self._pending:
                        self._pending[path] = size
                continue

            with self._lock:
                self._pending.pop(path, None)
            media_id = self._index_path(path)
            if media_id is not None:
                indexed_ids.append(media_id)

        if not indexed_ids:
            return
        if self.auto_enrich:
            self._enrich(indexed_ids)
        self._notify()

    def _index_path(self, path: str) -> int | None:
        # is_valid_media_file, pas is_media_file : applique aussi la taille minimale
        # et les mots-clés ignorés (sample, trailer…).
        if not self.scanner.is_valid_media_file(Path(path)):
            logger.debug(f"Watcher: ignored by scanner rules: {path}")
            return None
        parsed = self.scanner.parser.parse(path)
        if parsed is None:
            return None
        media = self.indexer.index_media(parsed)
        if media is None:
            return None
        logger.info(f"Watcher indexed new media: {path}")
        return media.id

    def _enrich(self, media_ids: list[int]):
        from core.services.tmdb_service import MediaMetadataEnricher

        db = SessionLocal()
        try:
            enricher = MediaMetadataEnricher()
            for media_id in media_ids:
                media = db.query(Media).filter(Media.id == media_id).first()
                if media is None:
                    continue
                if not enricher.enrich_media(media, db=db):
                    continue
                # Sans les images en cache, la vignette resterait un placeholder.
                enricher.download_artwork(media)
        except Exception as e:
            logger.error(f"Watcher enrichment failed: {e}")
        finally:
            db.close()

    def _notify(self):
        callback = self._on_change
        if callback is None:
            return
        try:
            callback()
        except Exception as e:
            logger.error(f"Watcher change callback failed: {e}")


# ── Convenience ───────────────────────────────────────────────────────────────


def scan_and_index(directories: list[str], recursive: bool = True) -> list[Media]:
    indexer = MediaIndexer()
    all_media = []
    for directory in directories:
        all_media.extend(indexer.index_directory(directory, recursive))
    return all_media
