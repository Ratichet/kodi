import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from core.config import (
    BASE_DIR,
    TMDB_BASE_URL,
    TMDB_IMAGE_BASE_URL,
    get_tmdb_api_key,
    get_tmdb_language,
)

logger = logging.getLogger(__name__)

# cache directories for pictures
POSTER_CACHE_DIR = BASE_DIR / "cache" / "posters"
BACKDROP_CACHE_DIR = BASE_DIR / "cache" / "backdrops"
STILL_CACHE_DIR = BASE_DIR / "cache" / "stills"

POSTER_SIZE = "w500"
BACKDROP_SIZE = "w1280"
STILL_SIZE = "w300"


def cast_names(cast: list[dict[str, str]]) -> str:
    """Casting sérialisé pour la base : « Tom Hanks, Robin Wright »."""
    return ", ".join(actor["name"] for actor in cast if actor.get("name"))


def cached_image_path(image_path: str, size: str, cache_dir: Path) -> Path:
    """Emplacement sur disque d'une image TMDb (même règle qu'au téléchargement)."""
    return cache_dir / f"{size}{image_path.replace('/', '_')}"


def local_poster(media) -> str | None:
    return _local_image(media.poster_path, POSTER_SIZE, POSTER_CACHE_DIR)


def local_backdrop(media) -> str | None:
    return _local_image(media.backdrop_path, BACKDROP_SIZE, BACKDROP_CACHE_DIR)


def local_still(media) -> str | None:
    return _local_image(getattr(media, "still_path", None), STILL_SIZE, STILL_CACHE_DIR)


def _local_image(image_path: str, size: str, cache_dir: Path) -> str | None:
    if not image_path:
        return None
    path = cached_image_path(image_path, size, cache_dir)
    return str(path) if path.exists() else None


@dataclass
class TMDbMovie:
    # strucutred data from tmdb
    tmdb_id: int
    title: str
    original_title: str = ""
    year: int | None = None
    release_date: str = ""
    overview: str = ""
    poster_path: str | None = None
    backdrop_path: str | None = None
    genres: list[str] = field(default_factory=list)
    rating: float = 0.0
    vote_count: int = 0
    runtime: int | None = None
    tagline: str = ""
    cast: list[dict[str, str]] = field(default_factory=list)
    director: str | None = None

    @property
    def poster_url(self) -> str | None:
        if self.poster_path:
            return f"{TMDB_IMAGE_BASE_URL}/w500{self.poster_path}"
        return None

    @property
    def backdrop_url(self) -> str | None:
        if self.backdrop_path:
            return f"{TMDB_IMAGE_BASE_URL}/w1280{self.backdrop_path}"
        return None

    @property
    def genres_str(self) -> str:
        return ", ".join(self.genres)


@dataclass
class TMDbTVShow:
    # structured data from tmdb (series)
    tmdb_id: int
    name: str
    original_name: str = ""
    first_air_date: str = ""
    year: int | None = None
    overview: str = ""
    poster_path: str | None = None
    backdrop_path: str | None = None
    genres: list[str] = field(default_factory=list)
    rating: float = 0.0
    vote_count: int = 0
    number_of_seasons: int = 0
    number_of_episodes: int = 0
    status: str = ""  # "Returning Series", "Ended", etc.
    cast: list[dict[str, str]] = field(default_factory=list)
    created_by: list[str] = field(default_factory=list)

    @property
    def poster_url(self) -> str | None:
        if self.poster_path:
            return f"{TMDB_IMAGE_BASE_URL}/w500{self.poster_path}"
        return None

    @property
    def backdrop_url(self) -> str | None:
        if self.backdrop_path:
            return f"{TMDB_IMAGE_BASE_URL}/w1280{self.backdrop_path}"
        return None

    @property
    def genres_str(self) -> str:
        return ", ".join(self.genres)


@dataclass
class TMDbEpisode:
    # structured data from tmdb (series episode)
    tmdb_id: int
    name: str
    episode_number: int
    season_number: int
    air_date: str = ""
    overview: str = ""
    still_path: str | None = None
    rating: float = 0.0
    runtime: int | None = None


class TMDbAPIError(Exception):
    def __init__(self, message: str, status_code: int = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class TMDbService:
    def __init__(self, api_key: str = None, language: str = None):
        self.api_key = api_key or get_tmdb_api_key()
        self.language = language or get_tmdb_language()
        self.base_url = TMDB_BASE_URL
        self.session = requests.Session()

        self._last_request_time = 0
        self._min_request_interval = 0.25

        # Ensure cache directories exist
        for cache_dir in (POSTER_CACHE_DIR, BACKDROP_CACHE_DIR, STILL_CACHE_DIR):
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _rate_limit(self):
        # ensure rate limit of 4 requests per second
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _request(self, endpoint: str, params: dict = None) -> dict:
        # make request to tmdb api
        self._rate_limit()

        url = f"{self.base_url}{endpoint}"
        params = params or {}
        params["api_key"] = self.api_key
        params["language"] = self.language

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            if status_code == 401:
                raise TMDbAPIError("Invalid API key", status_code)
            elif status_code == 404:
                raise TMDbAPIError("Resource not found", status_code)
            elif status_code == 429:
                raise TMDbAPIError("Rate limit exceeded", status_code)
            else:
                raise TMDbAPIError(f"HTTP error: {e}", status_code)

        except requests.exceptions.RequestException as e:
            raise TMDbAPIError(f"Request failed: {e}")

    def search_movie(
        self, query: str, year: int = None, page: int = 1
    ) -> list[TMDbMovie]:
        # search movies by title
        params = {"query": query, "page": page}
        if year:
            params["year"] = year

        try:
            data = self._request("/search/movie", params)
        except TMDbAPIError as e:
            logger.error(f"Movie search failed for '{query}': {e}")
            return []

        movies = []
        for result in data.get("results", []):
            release_date = result.get("release_date", "")
            movie = TMDbMovie(
                tmdb_id=result["id"],
                title=result.get("title", ""),
                original_title=result.get("original_title", ""),
                release_date=release_date,
                year=int(release_date[:4])
                if release_date and len(release_date) >= 4
                else None,
                overview=result.get("overview", ""),
                poster_path=result.get("poster_path"),
                backdrop_path=result.get("backdrop_path"),
                rating=result.get("vote_average", 0.0),
                vote_count=result.get("vote_count", 0),
            )
            movies.append(movie)

        logger.debug(f"Found {len(movies)} movies for query '{query}'")
        return movies

    def get_movie_details(
        self, movie_id: int, include_credits: bool = True
    ) -> TMDbMovie | None:
        # get detailed movie info by id
        try:
            append = "credits" if include_credits else ""
            params = {"append_to_response": append} if append else {}

            data = self._request(f"/movie/{movie_id}", params)
        except TMDbAPIError as e:
            logger.error(f"Failed to get movie details for ID {movie_id}: {e}")
            return None

        release_date = data.get("release_date", "")

        genres = [g["name"] for g in data.get("genres", [])]
        cast = []
        director = None
        if include_credits and "credits" in data:
            credits = data["credits"]
            for actor in credits.get("cast", [])[:10]:
                cast.append(
                    {
                        "name": actor.get("name", ""),
                        "character": actor.get("character", ""),
                        "profile_path": actor.get("profile_path"),
                    }
                )
            for crew in credits.get("crew", []):
                if crew.get("job") == "Director":
                    director = crew.get("name")
                    break

        movie = TMDbMovie(
            tmdb_id=data["id"],
            title=data.get("title", ""),
            original_title=data.get("original_title", ""),
            release_date=release_date,
            year=int(release_date[:4])
            if release_date and len(release_date) >= 4
            else None,
            overview=data.get("overview", ""),
            poster_path=data.get("poster_path"),
            backdrop_path=data.get("backdrop_path"),
            genres=genres,
            rating=data.get("vote_average", 0.0),
            vote_count=data.get("vote_count", 0),
            runtime=data.get("runtime"),
            tagline=data.get("tagline", ""),
            cast=cast,
            director=director,
        )

        return movie

    def search_tv(
        self, query: str, year: int = None, page: int = 1
    ) -> list[TMDbTVShow]:
        # search tv shows by title
        params = {"query": query, "page": page}
        if year:
            params["first_air_date_year"] = year

        try:
            data = self._request("/search/tv", params)
        except TMDbAPIError as e:
            logger.error(f"TV search failed for '{query}': {e}")
            return []

        shows = []
        for result in data.get("results", []):
            first_air_date = result.get("first_air_date", "")
            show = TMDbTVShow(
                tmdb_id=result["id"],
                name=result.get("name", ""),
                original_name=result.get("original_name", ""),
                first_air_date=first_air_date,
                year=int(first_air_date[:4])
                if first_air_date and len(first_air_date) >= 4
                else None,
                overview=result.get("overview", ""),
                poster_path=result.get("poster_path"),
                backdrop_path=result.get("backdrop_path"),
                rating=result.get("vote_average", 0.0),
                vote_count=result.get("vote_count", 0),
            )
            shows.append(show)

        logger.debug(f"Found {len(shows)} TV shows for query '{query}'")
        return shows

    def get_tv_details(
        self, tv_id: int, include_credits: bool = True
    ) -> TMDbTVShow | None:
        # get detailed tv show info by id
        try:
            append = "credits" if include_credits else ""
            params = {"append_to_response": append} if append else {}

            data = self._request(f"/tv/{tv_id}", params)
        except TMDbAPIError as e:
            logger.error(f"Failed to get TV details for ID {tv_id}: {e}")
            return None

        first_air_date = data.get("first_air_date", "")
        genres = [g["name"] for g in data.get("genres", [])]
        created_by = [c["name"] for c in data.get("created_by", [])]
        cast = []
        if include_credits and "credits" in data:
            for actor in data["credits"].get("cast", [])[:10]:
                cast.append(
                    {
                        "name": actor.get("name", ""),
                        "character": actor.get("character", ""),
                        "profile_path": actor.get("profile_path"),
                    }
                )

        show = TMDbTVShow(
            tmdb_id=data["id"],
            name=data.get("name", ""),
            original_name=data.get("original_name", ""),
            first_air_date=first_air_date,
            year=int(first_air_date[:4])
            if first_air_date and len(first_air_date) >= 4
            else None,
            overview=data.get("overview", ""),
            poster_path=data.get("poster_path"),
            backdrop_path=data.get("backdrop_path"),
            genres=genres,
            rating=data.get("vote_average", 0.0),
            vote_count=data.get("vote_count", 0),
            number_of_seasons=data.get("number_of_seasons", 0),
            number_of_episodes=data.get("number_of_episodes", 0),
            status=data.get("status", ""),
            cast=cast,
            created_by=created_by,
        )

        return show

    def get_episode_details(
        self, tv_id: int, season: int, episode: int
    ) -> TMDbEpisode | None:
        try:
            data = self._request(f"/tv/{tv_id}/season/{season}/episode/{episode}")
        except TMDbAPIError as e:
            logger.error(
                f"Failed to get episode S{season:02d}E{episode:02d} for TV ID {tv_id}: {e}"
            )
            return None

        return TMDbEpisode(
            tmdb_id=data.get("id", 0),
            name=data.get("name", ""),
            episode_number=data.get("episode_number", episode),
            season_number=data.get("season_number", season),
            air_date=data.get("air_date", ""),
            overview=data.get("overview", ""),
            still_path=data.get("still_path"),
            rating=data.get("vote_average", 0.0),
            runtime=data.get("runtime"),
        )

    def download_image(
        self, image_path: str, size: str = POSTER_SIZE, cache_dir: Path = None
    ) -> str | None:
        if not image_path:
            return None

        cache_dir = cache_dir or POSTER_CACHE_DIR
        local_path = cached_image_path(image_path, size, cache_dir)
        if local_path.exists():
            logger.debug(f"Using cached image: {local_path}")
            return str(local_path)
        url = f"{TMDB_IMAGE_BASE_URL}/{size}{image_path}"

        try:
            self._rate_limit()
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            with open(local_path, "wb") as f:
                f.write(response.content)

            logger.info(f"Downloaded image: {local_path}")
            return str(local_path)

        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
            return None

    def download_poster(self, poster_path: str, size: str = POSTER_SIZE) -> str | None:
        return self.download_image(poster_path, size, POSTER_CACHE_DIR)

    def download_backdrop(
        self, backdrop_path: str, size: str = BACKDROP_SIZE
    ) -> str | None:
        return self.download_image(backdrop_path, size, BACKDROP_CACHE_DIR)

    def download_still(self, still_path: str, size: str = STILL_SIZE) -> str | None:
        """Vignette 16:9 propre à un épisode."""
        return self.download_image(still_path, size, STILL_CACHE_DIR)

    def smart_search(
        self, title: str, year: int = None, media_type: str = None
    ) -> dict[str, Any]:
        if media_type == "movie":
            movies = self.search_movie(title, year)
            if movies:
                return {"type": "movie", "result": movies[0]}
            return {"type": "movie", "result": None}

        if media_type == "episode":
            shows = self.search_tv(title, year)
            if shows:
                return {"type": "tv", "result": shows[0]}
            return {"type": "tv", "result": None}

        movies = self.search_movie(title, year)
        shows = self.search_tv(title, year)

        best_movie = movies[0] if movies else None
        best_show = shows[0] if shows else None

        if best_movie and not best_show:
            return {"type": "movie", "result": best_movie}
        if best_show and not best_movie:
            return {"type": "tv", "result": best_show}
        if not best_movie and not best_show:
            return {"type": None, "result": None}

        if best_movie.vote_count >= best_show.vote_count:
            return {"type": "movie", "result": best_movie}
        return {"type": "tv", "result": best_show}


class MediaMetadataEnricher:
    def __init__(self, tmdb_service: TMDbService = None):
        self.tmdb = tmdb_service or TMDbService()

    def enrich_media(self, media, db=None) -> bool:
        """Enrichit `media` depuis TMDb.

        Si `db` est fourni, `media` doit lui appartenir et la transaction y est
        validée. Sinon une session temporaire est ouverte et `media` y est fusionné.
        """
        from core.database import SessionLocal

        if not media.title:
            logger.warning(f"Cannot enrich media without title: {media.file_path}")
            return False

        if media.tmdb_id:
            logger.debug(f"Media already enriched: {media.title}")
            return True

        caller_session = db is not None
        if not caller_session:
            db = SessionLocal()
        try:
            search_title = (
                media.series_name if media.media_type == "episode" else media.title
            )
            if not search_title:
                logger.warning(f"No searchable title for: {media.file_path}")
                return False
            result = self.tmdb.smart_search(
                search_title, year=media.year, media_type=media.media_type
            )

            if not result["result"]:
                logger.warning(f"No TMDb results for: {search_title}")
                return False
            if result["type"] == "movie":
                details = self.tmdb.get_movie_details(result["result"].tmdb_id)
                if details:
                    self._apply_movie_metadata(media, details)
            else:
                details = self.tmdb.get_tv_details(result["result"].tmdb_id)
                if details:
                    self._apply_tv_metadata(media, details)
                    if media.season_number and media.episode_number:
                        episode = self.tmdb.get_episode_details(
                            details.tmdb_id, media.season_number, media.episode_number
                        )
                        if episode:
                            self._apply_episode_metadata(media, episode)
            if not caller_session:
                db.merge(media)
            db.commit()

            logger.info(f"Enriched: {media.title} (TMDb ID: {media.tmdb_id})")
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to enrich media '{media.title}': {e}")
            return False
        finally:
            if not caller_session:
                db.close()

    def _apply_movie_metadata(self, media, movie: TMDbMovie):
        media.tmdb_id = movie.tmdb_id
        media.title = movie.title
        media.year = movie.year
        media.overview = movie.overview
        media.poster_path = movie.poster_path
        media.backdrop_path = movie.backdrop_path
        media.genres = movie.genres_str
        media.rating = f"{movie.rating:.1f}/10"
        # Une réponse sans générique ne doit pas effacer un casting déjà connu.
        if movie.cast:
            media.actors = cast_names(movie.cast)
        if movie.runtime:
            media.duration_sec = movie.runtime * 60

    def _apply_tv_metadata(self, media, show: TMDbTVShow):
        media.tmdb_id = show.tmdb_id
        media.series_name = show.name
        media.year = show.year
        # Conservé à part : `overview` sera écrasé par le résumé de l'épisode.
        media.series_overview = show.overview
        media.overview = show.overview
        media.poster_path = show.poster_path
        media.backdrop_path = show.backdrop_path
        media.genres = show.genres_str
        media.rating = f"{show.rating:.1f}/10"
        if show.cast:
            media.actors = cast_names(show.cast)

    def _apply_episode_metadata(self, media, episode: TMDbEpisode):
        media.episode_title = episode.name
        if episode.overview:
            media.overview = episode.overview
        if episode.still_path:
            media.still_path = episode.still_path
        if episode.runtime:
            media.duration_sec = episode.runtime * 60

    def download_artwork(self, media) -> int:
        """Met en cache les images d'un média. Renvoie le nombre de fichiers écrits."""
        downloaded = 0
        for image_path, download in (
            (media.poster_path, self.tmdb.download_poster),
            (media.backdrop_path, self.tmdb.download_backdrop),
            (getattr(media, "still_path", None), self.tmdb.download_still),
        ):
            if image_path and download(image_path):
                downloaded += 1
        return downloaded

    def re_enrich_media(self, media, db=None) -> bool:
        if not media.tmdb_id:
            return False

        try:
            if media.media_type == "movie":
                details = self.tmdb.get_movie_details(media.tmdb_id)
                if details:
                    self._apply_movie_metadata(media, details)
            elif media.media_type == "episode":
                details = self.tmdb.get_tv_details(media.tmdb_id)
                if details:
                    self._apply_tv_metadata(media, details)
                    if media.season_number and media.episode_number:
                        episode = self.tmdb.get_episode_details(
                            media.tmdb_id, media.season_number, media.episode_number
                        )
                        if episode:
                            self._apply_episode_metadata(media, episode)

            if db:
                db.commit()
            logger.info(f"Re-enriched: {media.title} (TMDb ID: {media.tmdb_id})")
            return True

        except Exception as e:
            if db:
                db.rollback()
            logger.error(f"Failed to re-enrich media '{media.title}': {e}")
            return False

    def enrich_all_media(self, limit: int = None) -> dict[str, int]:
        from core.database import SessionLocal
        from core.models import Media

        db = SessionLocal()
        stats = {"success": 0, "failed": 0, "skipped": 0}

        try:
            query = db.query(Media).filter(Media.tmdb_id.is_(None))
            if limit:
                query = query.limit(limit)

            media_list = query.all()
            total = len(media_list)

            logger.info(f"Enriching {total} media items...")

            for i, media in enumerate(media_list, 1):
                logger.info(f"[{i}/{total}] Processing: {media.title}")

                if self.enrich_media(media, db=db):
                    stats["success"] += 1
                else:
                    stats["failed"] += 1

            return stats

        finally:
            db.close()

    def fill_missing_details(self, progress_callback=None) -> dict[str, int]:
        """Complète les fiches enrichies auxquelles il manque un champ.

        `enrich_all_media` ne regarde que les médias sans `tmdb_id` : sans cette
        passe, ni un champ apparu après coup (le casting) ni un champ effacé par un
        réindexage (le titre d'épisode) ne reviendrait jamais.
        """
        from sqlalchemy import and_, or_

        from core.database import SessionLocal
        from core.models import Media

        missing_cast = or_(Media.actors.is_(None), Media.actors == "")
        missing_title = and_(
            Media.media_type == "episode",
            or_(Media.episode_title.is_(None), Media.episode_title == ""),
        )

        db = SessionLocal()
        stats = {"repaired": 0, "failed": 0}

        try:
            media_list = (
                db.query(Media)
                .filter(Media.tmdb_id.isnot(None))
                .filter(or_(missing_cast, missing_title))
                .all()
            )
            total = len(media_list)
            # Tous les épisodes d'une série partagent son tmdb_id : sans ce cache,
            # une saison entière demanderait autant de génériques que d'épisodes.
            casts: dict[tuple[str, int], str] = {}

            for index, media in enumerate(media_list, 1):
                if progress_callback:
                    progress_callback(index, total, media.title or media.file_path)

                repaired = False
                if not media.actors:
                    key = (media.media_type, media.tmdb_id)
                    if key not in casts:
                        casts[key] = self._fetch_cast(media)
                    if casts[key]:
                        media.actors = casts[key]
                        repaired = True
                if self._fill_episode_title(media):
                    repaired = True

                stats["repaired" if repaired else "failed"] += 1

            db.commit()
            logger.info(f"Completed {stats['repaired']} media record(s)")
            return stats

        finally:
            # Une annulation depuis le callback traverse : close() abandonne alors
            # la transaction, aucune ligne n'est écrite à moitié.
            db.close()

    def _fetch_cast(self, media) -> str:
        details = (
            self.tmdb.get_tv_details(media.tmdb_id)
            if media.media_type == "episode"
            else self.tmdb.get_movie_details(media.tmdb_id)
        )
        return cast_names(details.cast) if details else ""

    def _fill_episode_title(self, media) -> bool:
        """Redemande son titre à un épisode qui n'en a plus. Vrai s'il est revenu."""
        if media.media_type != "episode" or media.episode_title:
            return False
        if not (media.season_number and media.episode_number):
            return False

        episode = self.tmdb.get_episode_details(
            media.tmdb_id, media.season_number, media.episode_number
        )
        if not episode or not episode.name:
            return False

        media.episode_title = episode.name
        return True

    def download_all_artwork(self, progress_callback=None) -> dict[str, int]:
        """Met en cache affiches, fonds d'écran et vignettes d'épisodes.

        Une seule passe sur la bibliothèque : les trois types d'images étaient
        auparavant parcourus séparément.
        """
        from sqlalchemy import or_

        from core.database import SessionLocal
        from core.models import Media

        db = SessionLocal()
        stats = {"downloaded": 0, "cached": 0, "failed": 0}

        targets = (
            (POSTER_SIZE, POSTER_CACHE_DIR, "poster_path", self.tmdb.download_poster),
            (
                BACKDROP_SIZE,
                BACKDROP_CACHE_DIR,
                "backdrop_path",
                self.tmdb.download_backdrop,
            ),
            (STILL_SIZE, STILL_CACHE_DIR, "still_path", self.tmdb.download_still),
        )

        try:
            media_list = (
                db.query(Media)
                .filter(
                    or_(
                        Media.poster_path.isnot(None),
                        Media.backdrop_path.isnot(None),
                        Media.still_path.isnot(None),
                    )
                )
                .all()
            )
            total = len(media_list)

            for index, media in enumerate(media_list, 1):
                if progress_callback:
                    progress_callback(index, total, media.title or media.file_path)

                for size, cache_dir, attribute, download in targets:
                    image_path = getattr(media, attribute)
                    if not image_path:
                        continue
                    if cached_image_path(image_path, size, cache_dir).exists():
                        stats["cached"] += 1
                    elif download(image_path):
                        stats["downloaded"] += 1
                    else:
                        stats["failed"] += 1

            return stats

        finally:
            db.close()
