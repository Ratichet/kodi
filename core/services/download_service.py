"""Téléchargement de fichiers vers un dossier de la bibliothèque.

Le service ne connaît aucune source : il reçoit une URL et la transfère. Rien ici
ne dépend de Qt, comme le reste de `core/` — l'interface fournit son propre thread
(voir `ui/views/downloads_view.py`).
"""

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.models import Download, DownloadStatus, MediaDirectory
from core.services.archives import ArchiveError, is_archive
from core.services.archives import extract as extract_archive
from core.services.link_resolvers import ResolverError, resolve

logger = logging.getLogger(__name__)

CHUNK_SIZE = 256 * 1024
REQUEST_TIMEOUT = 30
# La base n'est pas touchée à chaque bloc : une écriture SQLite toutes les
# 250 ms suffit à survivre à une fermeture brutale.
DB_UPDATE_INTERVAL = 0.25

_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Nom de repli quand l'URL n'en porte pas : un lien de page n'a pas de nom de
# fichier, il n'apparaît qu'à la réponse du serveur.
PLACEHOLDER_PREFIX = "telechargement-"


class DownloadService:
    def __init__(self, db: Session = None):
        self._db = db
        self._owns_session = db is None

    @property
    def db(self) -> Session:
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def close(self):
        if self._owns_session and self._db:
            self._db.close()
            self._db = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # =================================================================
    # Destination
    # =================================================================

    def download_dir(self) -> Path:
        """Dossier de destination.

        Par défaut le premier dossier surveillé : un fichier qui y atterrit est
        indexé et enrichi sans rien demander. `download_dir` dans les réglages
        prend le pas si l'utilisateur préfère ailleurs.
        """
        from core.config import get_setting

        configured = get_setting("download_dir")
        if configured:
            return Path(configured)

        watched = (
            self.db.query(MediaDirectory)
            .filter(MediaDirectory.is_active.is_(True))
            .order_by(MediaDirectory.id)
            .first()
        )
        if watched:
            return Path(watched.path)
        return Path.home() / "Videos"

    def destination_is_watched(self) -> bool:
        """Le dossier de destination est-il indexé automatiquement ?

        Sinon les fichiers arrivent sans jamais rejoindre la bibliothèque, ce que
        l'écran Téléchargements signale.
        """
        destination = self.download_dir().resolve()
        for directory in (
            self.db.query(MediaDirectory)
            .filter(MediaDirectory.is_active.is_(True))
            .all()
        ):
            watched = Path(directory.path).resolve()
            if destination == watched or watched in destination.parents:
                return True
        return False

    # =================================================================
    # File d'attente
    # =================================================================

    def add(self, url: str, directory: str = None) -> Download | None:
        """Met une URL en file d'attente. Renvoie None si elle est inexploitable."""
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            logger.warning(f"Unsupported download URL: {url[:80]}")
            return None

        target_dir = Path(directory) if directory else self.download_dir()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Could not create the download directory {target_dir}: {e}")
            return None

        file_path = self._claim_path(target_dir / _filename_from_url(url))
        download = Download(
            url=url,
            file_path=str(file_path),
            filename=file_path.name,
            status=DownloadStatus.QUEUED.value,
        )
        self.db.add(download)
        self.db.commit()
        self.db.refresh(download)
        logger.info(f"Queued download: {download.filename}")
        return download

    def get(self, download_id: int) -> Download | None:
        return self.db.query(Download).filter(Download.id == download_id).first()

    def get_all(self) -> list[Download]:
        return self.db.query(Download).order_by(Download.id.desc()).all()

    def next_queued(self) -> Download | None:
        return (
            self.db.query(Download)
            .filter(Download.status == DownloadStatus.QUEUED.value)
            .order_by(Download.id)
            .first()
        )

    def has_pending(self) -> bool:
        return self.next_queued() is not None

    def requeue(self, download_id: int) -> bool:
        """Remet en file un téléchargement en pause ou en erreur."""
        download = self.get(download_id)
        if download is None or download.is_finished:
            return False
        self._update(download, status=DownloadStatus.QUEUED.value, error=None)
        return True

    def pause_all(self) -> int:
        """Sort les téléchargements en attente de la file. Celui qui tourne est
        arrêté par le thread appelant, qui le passera lui-même en pause."""
        pending = (
            self.db.query(Download)
            .filter(Download.status == DownloadStatus.QUEUED.value)
            .all()
        )
        for download in pending:
            download.status = DownloadStatus.PAUSED.value
        self.db.commit()
        return len(pending)

    def remove(self, download_id: int, delete_file: bool = True) -> bool:
        """Retire une entrée. Le fichier partiel disparaît avec elle."""
        download = self.get(download_id)
        if download is None:
            return False

        if delete_file:
            part = Path(download.part_path)
            if part.exists():
                try:
                    part.unlink()
                except OSError as e:
                    logger.warning(f"Could not delete {part}: {e}")

        self.db.delete(download)
        self.db.commit()
        return True

    def clear_finished(self) -> int:
        finished = (
            self.db.query(Download)
            .filter(Download.status == DownloadStatus.DONE.value)
            .all()
        )
        for download in finished:
            self.db.delete(download)
        self.db.commit()
        return len(finished)

    # =================================================================
    # Transfert
    # =================================================================

    def run(
        self,
        download_id: int,
        on_progress=None,
        should_stop=None,
        extract_archives: bool = True,
    ) -> bool:
        """Transfère un fichier. Bloquant : à appeler depuis un thread annexe.

        Renvoie True si le fichier est complet. Une interruption demandée par
        `should_stop()` laisse le `.part` en place : le prochain passage reprend
        où il s'est arrêté.
        """
        download = self.get(download_id)
        if download is None:
            return False

        part = Path(download.part_path)
        received = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={received}-"} if received else {}

        self._update(
            download,
            status=DownloadStatus.DOWNLOADING.value,
            error=None,
            received_bytes=received,
        )

        # L'URL d'origine est conservée en base : un lien d'hébergeur résolu est à
        # usage unique, chaque reprise doit donc en redemander un.
        try:
            effective_url = resolve(download.url)
        except ResolverError as e:
            logger.warning(f"Could not resolve the link for {download.filename}: {e}")
            self._update(download, status=DownloadStatus.ERROR.value, error=str(e))
            return False

        try:
            with requests.get(
                effective_url, stream=True, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()

                # Un serveur qui ignore l'en-tête Range répond 200 avec tout le
                # fichier : reprendre l'écriture à la fin du .part le corromprait.
                if received and response.status_code != 206:
                    logger.info(
                        f"{download.filename}: server ignored the resume request, "
                        "starting over"
                    )
                    received = 0

                if received == 0:
                    self._adopt_server_filename(download, response)

                self._update(
                    download,
                    total_bytes=_total_bytes(response, received),
                    received_bytes=received,
                )

                part = Path(download.part_path)
                part.parent.mkdir(parents=True, exist_ok=True)
                last_write = time.monotonic()

                with open(part, "ab" if received else "wb") as f:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if should_stop is not None and should_stop():
                            f.flush()
                            self._update(
                                download,
                                status=DownloadStatus.PAUSED.value,
                                received_bytes=received,
                            )
                            return False
                        if not chunk:
                            continue

                        f.write(chunk)
                        received += len(chunk)

                        if on_progress is not None:
                            try:
                                on_progress(received, download.total_bytes)
                            except Exception as e:
                                # L'affichage ne doit pas pouvoir interrompre un
                                # transfert : on le signale une fois, puis on
                                # continue sans lui plutôt que d'inonder le journal.
                                logger.warning(f"Progress callback failed: {e}")
                                on_progress = None
                        if time.monotonic() - last_write >= DB_UPDATE_INTERVAL:
                            self._update(download, received_bytes=received)
                            last_write = time.monotonic()
        except (requests.RequestException, OSError) as e:
            logger.error(f"Download failed for {download.filename}: {e}")
            self._update(
                download,
                status=DownloadStatus.ERROR.value,
                error=str(e),
                received_bytes=received,
            )
            return False

        try:
            # Renommage atomique : la surveillance de dossier ne voit apparaître
            # qu'un fichier déjà complet.
            part.replace(download.file_path)
        except OSError as e:
            logger.error(f"Could not finalise {download.filename}: {e}")
            self._update(download, status=DownloadStatus.ERROR.value, error=str(e))
            return False

        extracted_to, extraction_error = (
            self._extract(download) if extract_archives else (None, None)
        )

        self._update(
            download,
            status=DownloadStatus.DONE.value,
            received_bytes=received,
            total_bytes=download.total_bytes or received,
            finished_at=datetime.now(),
            extracted_to=extracted_to,
            error=extraction_error,
        )
        logger.info(f"Downloaded {download.filename} ({received} bytes)")
        return True

    def _extract(self, download: Download):
        """Décompresse une archive téléchargée et la supprime.

        Renvoie (dossier d'extraction, message d'erreur). Un échec ne remet pas en
        cause le téléchargement lui-même : le fichier est complet, il est conservé
        tel quel et le motif s'affiche sur sa ligne.
        """
        if not is_archive(download.file_path):
            return None, None

        destination = Path(download.file_path).parent
        try:
            extract_archive(download.file_path, destination)
        except ArchiveError as e:
            logger.warning(f"Could not extract {download.filename}: {e}")
            return None, str(e)

        try:
            Path(download.file_path).unlink()
        except OSError as e:
            # Le contenu est en place : l'archive restante est un désagrément,
            # pas un échec.
            logger.warning(f"Could not delete {download.filename}: {e}")

        return str(destination), None

    def _adopt_server_filename(self, download: Download, response) -> None:
        """Préfère le nom annoncé par le serveur, l'URL en donnant rarement un bon.

        Uniquement avant le premier octet : renommer en cours de route perdrait le
        `.part` déjà écrit.
        """
        offered = _filename_from_headers(response.headers)
        if not offered and download.filename.startswith(PLACEHOLDER_PREFIX):
            # Lien de page : le nom n'apparaît qu'une fois le lien direct obtenu.
            offered = _sanitize(Path(unquote(urlparse(response.url).path)).name)
        if not offered or offered == download.filename:
            return

        target = self._claim_path(
            Path(download.file_path).parent / offered, ignore_id=download.id
        )
        self._update(download, file_path=str(target), filename=target.name)

    def _claim_path(self, candidate: Path, ignore_id: int = None) -> Path:
        """Chemin encore libre pour un nouveau fichier.

        Les entrées déjà en file comptent autant que les fichiers présents : deux
        liens de même nom ajoutés d'affilée n'ont encore rien écrit sur le disque.
        """
        query = self.db.query(Download.file_path)
        if ignore_id is not None:
            query = query.filter(Download.id != ignore_id)
        return _free_path(candidate, {path for (path,) in query.all()})

    def _update(self, download: Download, **fields) -> None:
        for key, value in fields.items():
            setattr(download, key, value)
        self.db.commit()


def _filename_from_url(url: str) -> str:
    name = _sanitize(Path(unquote(urlparse(url).path)).name)
    return name or f"{PLACEHOLDER_PREFIX}{int(time.time())}"


def _filename_from_headers(headers) -> str | None:
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disposition)
    return _sanitize(unquote(match.group(1))) if match else None


def _sanitize(name: str) -> str:
    """Nom de fichier utilisable sous Windows comme ailleurs."""
    return _ILLEGAL_FILENAME_CHARS.sub("_", (name or "").strip()).strip(". ")[:180]


def _free_path(path: Path, taken=frozenset()) -> Path:
    """Chemin libre : « Film.mkv » devient « Film (2).mkv » si besoin.

    Le `.part` compte aussi, sinon deux téléchargements du même nom lancés
    ensemble écriraient dans le même fichier de travail.
    """

    def available(candidate: Path) -> bool:
        return (
            str(candidate) not in taken
            and not candidate.exists()
            and not Path(f"{candidate}.part").exists()
        )

    if available(path):
        return path

    stem, suffix = path.stem, path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if available(candidate):
            return candidate
    return path.with_name(f"{stem}-{int(time.time())}{suffix}")


def _total_bytes(response, received: int) -> int:
    """Taille complète du fichier, 0 si le serveur ne l'annonce pas.

    Sur une reprise (206), `Content-Length` ne vaut que pour le reste : c'est
    `Content-Range` qui porte le total.
    """
    content_range = response.headers.get("Content-Range", "")
    match = re.search(r"/(\d+)\s*$", content_range)
    if match:
        return int(match.group(1))

    length = response.headers.get("Content-Length")
    if length and length.isdigit():
        return int(length) + received
    return 0
