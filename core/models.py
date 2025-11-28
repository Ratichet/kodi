from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from core.database import Base


class MediaType(enum.Enum):
    MOVIE = "movie"
    EPISODE = "episode"
    MUSIC = "music"


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

    # for series specifically
    series_name = Column(String, nullable=True)
    season_number = Column(Integer, nullable=True)
    episode_number = Column(Integer, nullable=True)
    episode_title = Column(String, nullable=True)

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
        #return user-friendly title 
        if self.media_type == "episode" and self.series_name:
            ep_str = f"S{self.season_number:02d}E{self.episode_number:02d}" if self.season_number and self.episode_number else ""
            return f"{self.series_name} {ep_str}".strip()
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title or "Unknown"

    @property
    def poster_url(self) -> str | None:
        if self.poster_path:
            from core.config import TMDB_IMAGE_BASE_URL
            return f"{TMDB_IMAGE_BASE_URL}/w500{self.poster_path}"
        return None


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