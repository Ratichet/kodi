import logging
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import time

from core.config import (
    TMDB_API_KEY,
    TMDB_LANGUAGE,
    TMDB_BASE_URL,
    TMDB_IMAGE_BASE_URL,
    BASE_DIR,
)

logger = logging.getLogger(__name__)

# cache directories for pictures
POSTER_CACHE_DIR = BASE_DIR / "cache" / "posters"
BACKDROP_CACHE_DIR = BASE_DIR / "cache" / "backdrops"


@dataclass
class TMDbMovie:
    # strucutred data from tmdb
    tmdb_id: int
    title: str
    original_title: str = ""
    year: Optional[int] = None
    release_date: str = ""
    overview: str = ""
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    genres: List[str] = field(default_factory=list)
    rating: float = 0.0
    vote_count: int = 0
    runtime: Optional[int] = None
    tagline: str = ""
    cast: List[Dict[str, str]] = field(default_factory=list)
    director: Optional[str] = None

    @property
    def poster_url(self) -> Optional[str]:
        if self.poster_path:
            return f"{TMDB_IMAGE_BASE_URL}/w500{self.poster_path}"
        return None

    @property
    def backdrop_url(self) -> Optional[str]:
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
    year: Optional[int] = None
    overview: str = ""
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    genres: List[str] = field(default_factory=list)
    rating: float = 0.0
    vote_count: int = 0
    number_of_seasons: int = 0
    number_of_episodes: int = 0
    status: str = ""  # "Returning Series", "Ended", etc.
    cast: List[Dict[str, str]] = field(default_factory=list)
    created_by: List[str] = field(default_factory=list)

    @property
    def poster_url(self) -> Optional[str]:
        if self.poster_path:
            return f"{TMDB_IMAGE_BASE_URL}/w500{self.poster_path}"
        return None

    @property
    def backdrop_url(self) -> Optional[str]:
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
    still_path: Optional[str] = None
    rating: float = 0.0
    runtime: Optional[int] = None


class TMDbAPIError(Exception):
    def __init__(self, message: str, status_code: int = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class TMDbService:
    def __init__(self, api_key: str = None, language: str = None):
        self.api_key = api_key or TMDB_API_KEY
        self.language = language or TMDB_LANGUAGE
        self.base_url = TMDB_BASE_URL
        self.session = requests.Session()

        self._last_request_time = 0
        self._min_request_interval = 0.25

        # Ensure cache directories exist
        POSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        BACKDROP_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _rate_limit(self):
        # ensure rate limit of 4 requests per second
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _request(self, endpoint: str, params: Dict = None) -> Dict:
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
    ) -> List[TMDbMovie]:
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
    ) -> Optional[TMDbMovie]:
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
    ) -> List[TMDbTVShow]:
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
    ) -> Optional[TMDbTVShow]:
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
    ) -> Optional[TMDbEpisode]:
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
        self, image_path: str, size: str = "w500", cache_dir: Path = None
    ) -> Optional[str]:
        if not image_path:
            return None

        cache_dir = cache_dir or POSTER_CACHE_DIR
        filename = f"{size}{image_path.replace('/', '_')}"
        local_path = cache_dir / filename
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

    def download_poster(self, poster_path: str, size: str = "w500") -> Optional[str]:
        return self.download_image(poster_path, size, POSTER_CACHE_DIR)

    def download_backdrop(
        self, backdrop_path: str, size: str = "w1280"
    ) -> Optional[str]:
        return self.download_image(backdrop_path, size, BACKDROP_CACHE_DIR)

    def smart_search(
        self, title: str, year: int = None, media_type: str = None
    ) -> Dict[str, Any]:
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

    def enrich_media(self, media) -> bool:
        from core.database import SessionLocal

        if not media.title:
            logger.warning(f"Cannot enrich media without title: {media.file_path}")
            return False

        if media.tmdb_id:
            logger.debug(f"Media already enriched: {media.title}")
            return True

        db = SessionLocal()
        try:
            search_title = (
                media.series_name if media.media_type == "episode" else media.title
            )
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
            db.merge(media)
            db.commit()

            logger.info(f"Enriched: {media.title} (TMDb ID: {media.tmdb_id})")
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to enrich media '{media.title}': {e}")
            return False
        finally:
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
        if movie.runtime:
            media.duration_sec = movie.runtime * 60

    def _apply_tv_metadata(self, media, show: TMDbTVShow):
        media.tmdb_id = show.tmdb_id
        media.series_name = show.name
        media.year = show.year
        media.overview = show.overview
        media.poster_path = show.poster_path
        media.backdrop_path = show.backdrop_path
        media.genres = show.genres_str
        media.rating = f"{show.rating:.1f}/10"

    def _apply_episode_metadata(self, media, episode: TMDbEpisode):
        media.episode_title = episode.name
        if episode.overview:
            media.overview = episode.overview
        if episode.runtime:
            media.duration_sec = episode.runtime * 60

    def enrich_all_media(self, limit: int = None) -> Dict[str, int]:
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

                if self.enrich_media(media):
                    stats["success"] += 1
                else:
                    stats["failed"] += 1

            return stats

        finally:
            db.close()

    def download_all_posters(self) -> Dict[str, int]:
        from core.database import SessionLocal
        from core.models import Media

        db = SessionLocal()
        stats = {"downloaded": 0, "cached": 0, "failed": 0}

        try:
            media_list = db.query(Media).filter(Media.poster_path.isnot(None)).all()

            for media in media_list:
                local_path = (
                    POSTER_CACHE_DIR / f"w500{media.poster_path.replace('/', '_')}"
                )

                if local_path.exists():
                    stats["cached"] += 1
                    continue

                result = self.tmdb.download_poster(media.poster_path)
                if result:
                    stats["downloaded"] += 1
                else:
                    stats["failed"] += 1

            return stats

        finally:
            db.close()
