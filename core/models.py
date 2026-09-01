import enum

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from core.database import Base


class MediaType(enum.Enum):
    MOVIE = "movie"
    EPISODE = "episode"


class Media(Base):
    __tablename__ = "medias"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=True)
    year = Column(Integer, nullable=True)
    duration_sec = Column(Integer, default=0)
    media_type = Column(String, default="movie")

    # tmdb metadata
    overview = Column(String, nullable=True)
    poster_path = Column(String, nullable=True)
    backdrop_path = Column(String, nullable=True)
    tmdb_id = Column(Integer, nullable=True)
    genres = Column(String, nullable=True)  # JSON string or comma-separated
    rating = Column(String, nullable=True)  # e.g., "7.5/10"
    # Têtes d'affiche séparées par des virgules, dans l'ordre du générique.
    actors = Column(String, nullable=True)

    # for series specifically
    series_name = Column(String, nullable=True)
    season_number = Column(Integer, nullable=True)
    episode_number = Column(Integer, nullable=True)
    episode_title = Column(String, nullable=True)
    # `overview` porte le résumé de l'épisode : le synopsis de la série est gardé
    # à part pour l'en-tête de la vue Séries.
    series_overview = Column(String, nullable=True)
    # vignette 16:9 propre à l'épisode (« still » TMDb)
    still_path = Column(String, nullable=True)

    # user data
    is_watched = Column(Boolean, default=False)
    resume_position = Column(Integer, default=0)  # Position in milliseconds
    watch_count = Column(Integer, default=0)
    last_played = Column(DateTime(timezone=True), nullable=True)

    # timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<Media(title={self.title}, type={self.media_type}, path={self.file_path})>"

    @property
    def display_title(self) -> str:
        if self.media_type == "episode" and self.series_name:
            return f"{self.series_name} {self.episode_code}".strip()
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title or "Unknown"

    @property
    def episode_code(self) -> str:
        """« S01E04 », ou une chaîne vide si la numérotation est inconnue."""
        if self.season_number and self.episode_number:
            return f"S{self.season_number:02d}E{self.episode_number:02d}"
        return ""

    @property
    def actor_names(self) -> list[str]:
        return [name.strip() for name in (self.actors or "").split(",") if name.strip()]

    def has_actor(self, query: str) -> bool:
        """Vrai si un nom du casting commence par `query`, mot à mot.

        Un début de mot plutôt qu'une sous-chaîne : sinon chercher « an »
        ramènerait tous les films où joue une Susan ou un Bryan.
        """
        needle = query.strip().lower()
        if not needle:
            return False
        for name in self.actor_names:
            name = name.lower()
            # Le nom entier couvre « tom h », les mots couvrent « hanks ».
            if name.startswith(needle) or any(
                word.startswith(needle) for word in name.split()
            ):
                return True
        return False

    @property
    def progress_ratio(self) -> float:
        """Avancement de lecture entre 0 et 1 (0 si vu ou jamais commencé)."""
        if self.is_watched or not self.resume_position or not self.duration_sec:
            return 0.0
        return min(self.resume_position / (self.duration_sec * 1000), 1.0)

    @property
    def poster_url(self) -> str | None:
        if self.poster_path:
            from core.config import TMDB_IMAGE_BASE_URL

            return f"{TMDB_IMAGE_BASE_URL}/w500{self.poster_path}"
        return None


class DownloadStatus(enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"


class Download(Base):
    __tablename__ = "downloads"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    file_path = Column(String, nullable=False)  # destination définitive
    filename = Column(String, nullable=False)
    total_bytes = Column(Integer, default=0)  # 0 : taille annoncée inconnue
    received_bytes = Column(Integer, default=0)
    status = Column(String, default=DownloadStatus.QUEUED.value)
    error = Column(String, nullable=True)
    # Dossier où l'archive a été extraite ; le fichier téléchargé n'existe alors plus.
    extracted_to = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<Download(file={self.filename}, status={self.status})>"

    @property
    def part_path(self) -> str:
        """Fichier de travail, renommé une fois le transfert terminé.

        L'extension `.part` n'étant pas indexable, la surveillance de dossier
        ignore un téléchargement en cours : la bibliothèque ne voit le fichier
        qu'entier.
        """
        return f"{self.file_path}.part"

    @property
    def is_finished(self) -> bool:
        return self.status == DownloadStatus.DONE.value

    @property
    def progress_ratio(self) -> float:
        """Avancement entre 0 et 1 ; 0 si la taille totale est inconnue."""
        if self.is_finished:
            return 1.0
        if not self.total_bytes or not self.received_bytes:
            return 0.0
        return min(self.received_bytes / self.total_bytes, 1.0)


class MediaDirectory(Base):
    __tablename__ = "media_directories"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, unique=True, nullable=False)
    media_type_filter = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    recursive = Column(Boolean, default=True)
    last_scanned = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<MediaDirectory(path={self.path}, active={self.is_active})>"
