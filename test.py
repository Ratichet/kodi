import atexit
import logging
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Les tests appellent drop_all() : sans cette redirection ils effaceraient la
# bibliothèque de l'utilisateur (epikodi.db à la racine du projet). Doit être posé
# AVANT tout import de core.database, qui lit la valeur au chargement.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="epikodi_tests_")
os.environ["EPIKODI_DB_PATH"] = "sqlite:///" + os.path.join(
    _TEST_DB_DIR, "library.db"
).replace("\\", "/")
atexit.register(shutil.rmtree, _TEST_DB_DIR, ignore_errors=True)

from core.config import BASE_DIR, DB_NAME, DB_PATH  # noqa: E402
from core.database import Base, SessionLocal, engine  # noqa: E402
from core.models import Media  # noqa: E402
from core.power import KeepAwake  # noqa: E402
from core.services.scanner import (  # noqa: E402
    MediaIndexer,
    MediaParser,
    MediaScanner,
    ParsedMedia,
)

# Filet de sécurité : ces tests font des drop_all().
assert str(BASE_DIR / DB_NAME).replace("\\", "/") not in DB_PATH, (
    f"Les tests pointent sur la base de production ({DB_PATH}), abandon."
)

logging.basicConfig(level=logging.WARNING)


class TestMediaParser(unittest.TestCase):
    def test_parse_simple_movie(self):
        parsed = MediaParser.parse("/movies/Inception.2010.1080p.BluRay.mkv")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.title, "Inception")
        self.assertEqual(parsed.year, 2010)
        self.assertEqual(parsed.media_type, "movie")
        self.assertEqual(parsed.quality, "1080p")

    def test_parse_movie_without_year(self):
        parsed = MediaParser.parse("/movies/Avatar.mp4")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.title, "Avatar")
        self.assertEqual(parsed.media_type, "movie")

    def test_parse_tv_episode(self):
        parsed = MediaParser.parse("/series/Breaking.Bad.S01E01.720p.mkv")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.media_type, "episode")
        self.assertEqual(parsed.series, "Breaking Bad")
        self.assertEqual(parsed.season, 1)
        self.assertEqual(parsed.episode, 1)

    def test_parse_tv_episode_full_format(self):
        parsed = MediaParser.parse(
            "/tv/Game.of.Thrones.S03E09.The.Rains.of.Castamere.1080p.mkv"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.media_type, "episode")
        self.assertEqual(parsed.series, "Game of Thrones")
        self.assertEqual(parsed.season, 3)
        self.assertEqual(parsed.episode, 9)

    def test_parse_movie_with_dots(self):
        parsed = MediaParser.parse("/movies/The.Dark.Knight.2008.BluRay.mp4")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.title, "The Dark Knight")
        self.assertEqual(parsed.year, 2008)

    def test_parse_returns_none_on_failure(self):
        parsed = MediaParser.parse("")
        self.assertTrue(parsed is None or isinstance(parsed, ParsedMedia))

    def test_get_search_title_movie(self):
        parsed = ParsedMedia(
            file_path="/test.mkv",
            title="Inception",
            year=2010,
            media_type="movie",
        )
        self.assertEqual(parsed.get_search_title(), "Inception")

    def test_get_search_title_episode(self):
        parsed = ParsedMedia(
            file_path="/test.mkv",
            title="Pilot",
            media_type="episode",
            series="Breaking Bad",
            season=1,
            episode=1,
        )
        self.assertEqual(parsed.get_search_title(), "Breaking Bad")


class TestMediaScanner(unittest.TestCase):
    def setUp(self):
        """Create a temporary directory with fake media files."""
        self.test_dir = tempfile.mkdtemp(prefix="epikodi_test_")

        # Create fake media files
        self.movie_files = [
            "Inception.2010.1080p.BluRay.mkv",
            "The.Matrix.1999.mp4",
            "Avatar.2009.avi",
        ]
        self.episode_files = [
            "Breaking.Bad.S01E01.720p.mkv",
            "Breaking.Bad.S01E02.720p.mkv",
        ]
        self.non_media_files = [
            "readme.txt",
            "notes.pdf",
            "image.jpg",
        ]

        for f in self.movie_files + self.episode_files + self.non_media_files:
            open(os.path.join(self.test_dir, f), "w").close()

        self.sub_dir = os.path.join(self.test_dir, "subfolder")
        os.makedirs(self.sub_dir)
        open(os.path.join(self.sub_dir, "Interstellar.2014.mkv"), "w").close()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_media_file(self):
        scanner = MediaScanner(min_video_size_mb=0)
        self.assertTrue(scanner.is_media_file("test.mkv"))
        self.assertTrue(scanner.is_media_file("test.mp4"))
        self.assertTrue(scanner.is_media_file("test.avi"))
        self.assertFalse(scanner.is_media_file("test.mp3"))  # audio retiré
        self.assertFalse(scanner.is_media_file("test.txt"))
        self.assertFalse(scanner.is_media_file("test.pdf"))
        self.assertFalse(scanner.is_media_file("test.jpg"))

    def test_scan_directory_finds_media(self):
        scanner = MediaScanner(min_video_size_mb=0)
        results = scanner.scan_directory(self.test_dir, recursive=False)

        self.assertEqual(len(results), 5)

        file_names = [os.path.basename(r.file_path) for r in results]
        self.assertIn("Inception.2010.1080p.BluRay.mkv", file_names)
        self.assertNotIn("readme.txt", file_names)

    def test_scan_directory_recursive(self):
        scanner = MediaScanner(min_video_size_mb=0)
        results = scanner.scan_directory(self.test_dir, recursive=True)

        self.assertEqual(len(results), 6)

        titles = [r.title for r in results]
        self.assertIn("Interstellar", titles)

    def test_scan_directory_non_recursive(self):
        scanner = MediaScanner(min_video_size_mb=0)
        results = scanner.scan_directory(self.test_dir, recursive=False)

        self.assertEqual(len(results), 5)
        titles = [r.title for r in results]
        self.assertNotIn("Interstellar", titles)

    def test_scan_nonexistent_directory(self):
        scanner = MediaScanner(min_video_size_mb=0)
        results = scanner.scan_directory("/nonexistent/path/xyz")
        self.assertEqual(results, [])

    def test_parsed_media_types(self):
        scanner = MediaScanner(min_video_size_mb=0)
        results = scanner.scan_directory(self.test_dir, recursive=False)

        movies = [r for r in results if r.media_type == "movie"]
        episodes = [r for r in results if r.media_type == "episode"]

        self.assertEqual(len(movies), 3)
        self.assertEqual(len(episodes), 2)


class TestMediaIndexer(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.indexer = MediaIndexer(scanner=MediaScanner(min_video_size_mb=0))

    def tearDown(self):
        pass

    def test_index_movie(self):
        parsed = ParsedMedia(
            file_path="/tmp/test/Inception.2010.mkv",
            title="Inception",
            year=2010,
            media_type="movie",
        )

        media = self.indexer.index_media(parsed)
        self.assertIsNotNone(media)
        self.assertEqual(media.title, "Inception")
        self.assertEqual(media.year, 2010)
        self.assertEqual(media.media_type, "movie")

    def test_index_episode_saves_all_fields(self):

        parsed = ParsedMedia(
            file_path="/tmp/test/Breaking.Bad.S01E01.mkv",
            title="Breaking Bad",
            year=2008,
            media_type="episode",
            series="Breaking Bad",
            season=1,
            episode=1,
            episode_title="Pilot",
        )

        media = self.indexer.index_media(parsed)
        self.assertIsNotNone(media)
        self.assertEqual(media.media_type, "episode")
        self.assertEqual(media.series_name, "Breaking Bad")
        self.assertEqual(media.season_number, 1)
        self.assertEqual(media.episode_number, 1)
        self.assertEqual(media.episode_title, "Pilot")

    def test_index_deduplication(self):

        parsed = ParsedMedia(
            file_path="/tmp/test/Inception.2010.mkv",
            title="Inception",
            year=2010,
            media_type="movie",
        )

        media1 = self.indexer.index_media(parsed)
        media2 = self.indexer.index_media(parsed)

        self.assertIsNotNone(media1)
        self.assertIsNotNone(media2)
        self.assertEqual(media1.id, media2.id)

    def test_index_directory(self):

        test_dir = tempfile.mkdtemp(prefix="epikodi_idx_test_")
        try:
            # Create fake media files
            for name in ["Movie.A.2020.mkv", "Movie.B.2021.mp4"]:
                open(os.path.join(test_dir, name), "w").close()

            indexed = self.indexer.index_directory(test_dir)
            self.assertEqual(len(indexed), 2)

            db = SessionLocal()
            count = db.query(Media).count()
            db.close()
            self.assertEqual(count, 2)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_remove_media(self):
        parsed = ParsedMedia(
            file_path="/tmp/test/ToDelete.mkv",
            title="ToDelete",
            media_type="movie",
        )

        media = self.indexer.index_media(parsed)
        self.assertIsNotNone(media)

        removed = self.indexer.remove_media("/tmp/test/ToDelete.mkv")
        self.assertTrue(removed)

        db = SessionLocal()
        result = (
            db.query(Media).filter(Media.file_path == "/tmp/test/ToDelete.mkv").first()
        )
        db.close()
        self.assertIsNone(result)

    def test_remove_nonexistent(self):
        removed = self.indexer.remove_media("/tmp/nonexistent.mkv")
        self.assertFalse(removed)

    def test_index_update_metadata(self):

        parsed_v1 = ParsedMedia(
            file_path="/tmp/test/Show.S01E01.mkv",
            title="Show",
            media_type="episode",
            series="Show",
            season=1,
            episode=1,
        )
        media = self.indexer.index_media(parsed_v1)
        self.assertEqual(media.episode_title, None)

        parsed_v2 = ParsedMedia(
            file_path="/tmp/test/Show.S01E01.mkv",
            title="Show",
            media_type="episode",
            series="Show",
            season=1,
            episode=1,
            episode_title="Pilot",  # Nouveau champ dÃ©tectÃ©
        )

        media_updated = self.indexer.index_media(parsed_v2)

        self.assertEqual(media_updated.id, media.id)  # MÃªme ID DB
        self.assertEqual(media_updated.episode_title, "Pilot")  # Champ mis Ã  jour


class TestMediaServiceBasic(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        db = SessionLocal()
        db.add_all(
            [
                Media(
                    file_path="/movies/a.mkv",
                    title="Alpha",
                    year=2020,
                    media_type="movie",
                ),
                Media(
                    file_path="/movies/b.mkv",
                    title="Beta",
                    year=2021,
                    media_type="movie",
                    is_watched=True,
                ),
                Media(
                    file_path="/series/c.mkv",
                    title="Pilot",
                    media_type="episode",
                    series_name="Gamma Show",
                    season_number=1,
                    episode_number=1,
                ),
                Media(
                    file_path="/movies/d.mkv",
                    title="Delta",
                    year=2019,
                    media_type="movie",
                    resume_position=50000,
                ),
            ]
        )
        db.commit()
        db.close()

    def test_get_movies(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            movies = svc.get_movies()
            self.assertEqual(len(movies), 3)  # Alpha, Beta, Delta

    def test_get_episodes(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            episodes = svc.get_episodes()
            self.assertEqual(len(episodes), 1)

    def test_search_media(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            results = svc.search_media("Alpha")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].title, "Alpha")

    def test_search_by_series_name(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            results = svc.search_media("Gamma")
            self.assertEqual(len(results), 1)

    def test_get_in_progress(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            in_progress = svc.get_in_progress()
            self.assertEqual(len(in_progress), 1)
            self.assertEqual(in_progress[0].title, "Delta")

    def test_mark_as_watched(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            media = svc.search_media("Alpha")[0]
            svc.mark_as_watched(media.id)

            refreshed = svc.get_media_by_id(media.id)
            self.assertTrue(refreshed.is_watched)
            self.assertEqual(refreshed.watch_count, 1)
            self.assertEqual(refreshed.resume_position, 0)

    def test_get_stats(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            stats = svc.get_stats()
            self.assertEqual(stats["total_media"], 4)
            self.assertEqual(stats["movies"], 3)
            self.assertEqual(stats["episodes"], 1)
            self.assertEqual(stats["watched"], 1)
            self.assertEqual(stats["in_progress"], 1)

    def test_add_and_remove_directory(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            d = svc.add_media_directory("/tmp/test_media")
            self.assertIsNotNone(d)
            self.assertEqual(d.path, "/tmp/test_media")

            dirs = svc.get_media_directories()
            self.assertEqual(len(dirs), 1)

            removed = svc.remove_media_directory(d.id)
            self.assertTrue(removed)

            dirs = svc.get_media_directories()
            self.assertEqual(len(dirs), 0)

    def test_mark_as_unwatched(self):
        """DetailView appelle cette méthode : elle doit exister et remettre à zéro."""
        from core.services.media_service import MediaService

        with MediaService() as svc:
            media = svc.search_media("Beta")[0]
            self.assertTrue(media.is_watched)

            svc.mark_as_unwatched(media.id)

            refreshed = svc.get_media_by_id(media.id)
            self.assertFalse(refreshed.is_watched)
            self.assertEqual(refreshed.watch_count, 0)
            self.assertEqual(refreshed.resume_position, 0)

    def test_update_progress_counts_one_view_only(self):
        """Le timer de sauvegarde appelle update_progress toutes les 10 s : la fin
        d'un média ne doit être comptée qu'une fois."""
        from core.services.media_service import MediaService

        with MediaService() as svc:
            media = svc.search_media("Alpha")[0]
            for _ in range(4):
                svc.update_progress(media.id, 95_000, 100_000)

            refreshed = svc.get_media_by_id(media.id)
            self.assertTrue(refreshed.is_watched)
            self.assertEqual(refreshed.watch_count, 1)

    def test_index_directory_results_stay_readable(self):
        """index_directory ferme sa session : les objets renvoyés doivent rester
        lisibles (sinon DetachedInstanceError chez l'appelant)."""
        test_dir = tempfile.mkdtemp(prefix="epikodi_detach_")
        try:
            for name in ["Movie.C.2022.mkv", "Movie.D.2023.mp4"]:
                open(os.path.join(test_dir, name), "w").close()

            indexer = MediaIndexer(scanner=MediaScanner(min_video_size_mb=0))
            indexed = indexer.index_directory(test_dir)

            self.assertEqual(len(indexed), 2)
            titles = sorted(m.title for m in indexed)
            self.assertEqual(titles, ["Movie C", "Movie D"])
            self.assertTrue(all(m.id is not None for m in indexed))
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


class TestSeriesGrouping(unittest.TestCase):
    """Regroupement par série alimentant la vue Séries."""

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        db = SessionLocal()
        rows = []
        for season, episode, watched in [
            (1, 1, True),
            (1, 2, True),
            (1, 3, False),
            (2, 1, False),
        ]:
            rows.append(
                Media(
                    file_path=f"/s/show.s{season}e{episode}.mkv",
                    title="Show",
                    media_type="episode",
                    series_name="Show",
                    season_number=season,
                    episode_number=episode,
                    episode_title=f"Titre {season}x{episode}",
                    duration_sec=2700,
                    is_watched=watched,
                    resume_position=600_000 if (season, episode) == (1, 3) else 0,
                )
            )
        rows.append(
            Media(file_path="/m/movie.mkv", title="Un film", media_type="movie")
        )
        db.add_all(rows)
        db.commit()
        db.close()

    def _series(self):
        from core.services.media_service import MediaService
        from ui.views.series_view import Series

        with MediaService() as svc:
            return Series("Show", svc.get_series_episodes("Show"))

    def test_get_series_episodes_is_ordered_and_scoped(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            episodes = svc.get_series_episodes("Show")

        self.assertEqual(len(episodes), 4)  # le film n'est pas repris
        self.assertEqual(
            [e.episode_code for e in episodes],
            ["S01E01", "S01E02", "S01E03", "S02E01"],
        )

    def test_season_split_and_progress(self):
        series = self._series()

        self.assertEqual(series.season_count, 2)
        self.assertEqual(series.episode_count, 4)
        self.assertEqual(series.watched_count, 2)
        self.assertEqual(len(series.seasons[1]), 3)
        self.assertEqual(len(series.seasons[2]), 1)
        self.assertAlmostEqual(series.progress_ratio, 0.5)

    def test_next_to_watch_prefers_a_started_episode(self):
        series = self._series()

        nxt = series.next_to_watch()
        self.assertEqual(nxt.episode_code, "S01E03")
        self.assertGreater(nxt.progress_ratio, 0)

    def test_next_to_watch_falls_back_to_first_unwatched(self):
        from core.services.media_service import MediaService
        from ui.views.series_view import Series

        with MediaService() as svc:
            started = next(
                e for e in svc.get_series_episodes("Show") if e.resume_position
            )
            svc.mark_as_watched(started.id)
            series = Series("Show", svc.get_series_episodes("Show"))

        self.assertEqual(series.next_to_watch().episode_code, "S02E01")

    def test_next_to_watch_is_none_when_everything_is_seen(self):
        from core.services.media_service import MediaService
        from ui.views.series_view import Series

        with MediaService() as svc:
            for episode in svc.get_series_episodes("Show"):
                svc.mark_as_watched(episode.id)
            series = Series("Show", svc.get_series_episodes("Show"))

        self.assertIsNone(series.next_to_watch())
        self.assertEqual(series.progress_ratio, 1.0)


class _FakeTMDb:
    """Tient la place de TMDbService : le casting des tests ne sort pas de la machine."""

    MOVIE_CAST = [
        {"name": "Tom Hanks", "character": "Forrest"},
        {"name": "Robin Wright", "character": "Jenny"},
    ]
    TV_CAST = [
        {"name": "Damian Lewis", "character": "Winters"},
        {"name": "Ron Livingston", "character": "Nixon"},
    ]

    def __init__(self, movie_cast=None, tv_cast=None):
        self.movie_cast = self.MOVIE_CAST if movie_cast is None else movie_cast
        self.tv_cast = self.TV_CAST if tv_cast is None else tv_cast
        self.movie_calls = []
        self.tv_calls = []
        self.episode_calls = []

    def get_movie_details(self, movie_id, include_credits=True):
        from core.services.tmdb_service import TMDbMovie

        self.movie_calls.append(movie_id)
        return TMDbMovie(tmdb_id=movie_id, title="Titre TMDb", cast=self.movie_cast)

    def get_tv_details(self, tv_id, include_credits=True):
        from core.services.tmdb_service import TMDbTVShow

        self.tv_calls.append(tv_id)
        return TMDbTVShow(tmdb_id=tv_id, name="Série TMDb", cast=self.tv_cast)

    def get_episode_details(self, tv_id, season, episode):
        from core.services.tmdb_service import TMDbEpisode

        self.episode_calls.append((tv_id, season, episode))
        return TMDbEpisode(
            tmdb_id=tv_id,
            name=f"Titre TMDb S{season:02d}E{episode:02d}",
            season_number=season,
            episode_number=episode,
        )


def _library_with_cast():
    """Bibliothèque de référence : deux films, deux séries, un média non enrichi."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    db.add_all(
        [
            Media(
                file_path="/movies/forrest.mkv",
                title="Forrest Gump",
                year=1994,
                media_type="movie",
                tmdb_id=13,
                actors="Tom Hanks, Robin Wright, Gary Sinise",
            ),
            Media(
                file_path="/movies/matrix.mkv",
                title="Matrix",
                year=1999,
                media_type="movie",
                tmdb_id=603,
                actors="Keanu Reeves, Carrie-Anne Moss",
            ),
            Media(
                file_path="/movies/inconnu.mkv",
                title="Film sans générique",
                media_type="movie",
            ),
            Media(
                file_path="/series/bob.s01e01.mkv",
                title="Currahee",
                episode_title="Currahee",
                media_type="episode",
                series_name="Band of Brothers",
                season_number=1,
                episode_number=1,
                tmdb_id=4613,
                actors="Damian Lewis, Ron Livingston",
            ),
            Media(
                file_path="/series/bob.s01e02.mkv",
                title="Day of Days",
                episode_title="Day of Days",
                media_type="episode",
                series_name="Band of Brothers",
                season_number=1,
                episode_number=2,
                tmdb_id=4613,
                actors="Damian Lewis, Ron Livingston",
            ),
            Media(
                file_path="/series/got.s01e01.mkv",
                title="Winter Is Coming",
                episode_title="Winter Is Coming",
                media_type="episode",
                series_name="Game of Thrones",
                season_number=1,
                episode_number=1,
                tmdb_id=1399,
                actors="Emilia Clarke, Kit Harington",
            ),
        ]
    )
    db.commit()
    db.close()


class TestActorSearch(unittest.TestCase):
    """Recherche par acteur : le casting TMDb est rangé dans `Media.actors`."""

    def setUp(self):
        _library_with_cast()

    def test_a_movie_is_found_by_its_lead_actor(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            results = svc.search_media("Tom Hanks")

        self.assertEqual([m.title for m in results], ["Forrest Gump"])

    def test_a_surname_alone_is_enough(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            self.assertEqual([m.title for m in svc.search_media("reeves")], ["Matrix"])
            self.assertEqual([m.title for m in svc.search_media("Sinise")], ["Forrest Gump"])

    def test_a_fragment_inside_a_name_is_not_a_match(self):
        """Sinon « an » ramènerait tous les films où joue une Susan ou un Bryan."""
        from core.services.media_service import MediaService

        with MediaService() as svc:
            self.assertEqual(svc.search_media("anks"), [])
            self.assertEqual(svc.search_media("eeves"), [])

    def test_the_episodes_of_a_series_are_found_by_their_actor(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            results = svc.search_media("Damian")

        self.assertEqual(len(results), 2)
        self.assertEqual({m.series_name for m in results}, {"Band of Brothers"})

    def test_searching_a_title_still_works(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            self.assertEqual([m.title for m in svc.search_media("Matrix")], ["Matrix"])
            self.assertEqual(len(svc.search_media("Gump")), 1)

    def test_a_media_without_cast_never_matches(self):
        media = Media(file_path="/m/x.mkv", title="Sans générique")

        self.assertEqual(media.actor_names, [])
        self.assertFalse(media.has_actor("Hanks"))

    def test_an_empty_search_matches_nobody(self):
        media = Media(file_path="/m/x.mkv", title="Film", actors="Tom Hanks")

        self.assertFalse(media.has_actor(""))
        self.assertFalse(media.has_actor("   "))

    def test_a_first_name_followed_by_a_partial_surname_matches(self):
        media = Media(file_path="/m/x.mkv", title="Film", actors="Tom Hanks")

        self.assertTrue(media.has_actor("tom h"))
        self.assertTrue(media.has_actor("TOM HANKS"))
        self.assertFalse(media.has_actor("tom c"))

    def test_the_cast_is_saved_when_a_movie_is_enriched(self):
        from core.services.tmdb_service import MediaMetadataEnricher, TMDbMovie

        media = Media(file_path="/m/forrest.mkv", title="Forrest")
        enricher = MediaMetadataEnricher(tmdb_service=_FakeTMDb())
        enricher._apply_movie_metadata(
            media, TMDbMovie(tmdb_id=13, title="Forrest Gump", cast=_FakeTMDb.MOVIE_CAST)
        )

        self.assertEqual(media.actors, "Tom Hanks, Robin Wright")
        self.assertTrue(media.has_actor("Wright"))

    def test_the_cast_is_saved_when_a_series_is_enriched(self):
        from core.services.tmdb_service import MediaMetadataEnricher, TMDbTVShow

        media = Media(file_path="/s/bob.mkv", title="Currahee", media_type="episode")
        enricher = MediaMetadataEnricher(tmdb_service=_FakeTMDb())
        enricher._apply_tv_metadata(
            media, TMDbTVShow(tmdb_id=4613, name="Band of Brothers", cast=_FakeTMDb.TV_CAST)
        )

        self.assertEqual(media.actors, "Damian Lewis, Ron Livingston")

    def test_a_reply_without_a_cast_keeps_the_known_names(self):
        """TMDb répond parfois sans générique : mieux vaut garder l'ancien."""
        from core.services.tmdb_service import MediaMetadataEnricher, TMDbMovie

        media = Media(file_path="/m/x.mkv", title="Film", actors="Tom Hanks")
        enricher = MediaMetadataEnricher(tmdb_service=_FakeTMDb())
        enricher._apply_movie_metadata(media, TMDbMovie(tmdb_id=13, title="Film"))

        self.assertEqual(media.actors, "Tom Hanks")

    def test_a_library_indexed_before_the_cast_existed_is_filled_in(self):
        from core.services.tmdb_service import MediaMetadataEnricher

        db = SessionLocal()
        db.query(Media).update({Media.actors: None})
        db.commit()
        db.close()

        fake = _FakeTMDb()
        stats = MediaMetadataEnricher(tmdb_service=fake).fill_missing_details()

        db = SessionLocal()
        try:
            forrest = db.query(Media).filter(Media.title == "Forrest Gump").one()
            episodes = db.query(Media).filter(Media.series_name == "Band of Brothers").all()
        finally:
            db.close()

        self.assertEqual(stats["repaired"], 5)  # le film sans tmdb_id reste de côté
        self.assertEqual(forrest.actors, "Tom Hanks, Robin Wright")
        self.assertTrue(all(e.actors == "Damian Lewis, Ron Livingston" for e in episodes))

    def test_a_series_costs_one_call_whatever_its_number_of_episodes(self):
        """Les épisodes partagent le tmdb_id de la série : une seule requête."""
        from core.services.tmdb_service import MediaMetadataEnricher

        db = SessionLocal()
        db.query(Media).update({Media.actors: None})
        db.commit()
        db.close()

        fake = _FakeTMDb()
        MediaMetadataEnricher(tmdb_service=fake).fill_missing_details()

        self.assertEqual(sorted(fake.tv_calls), [1399, 4613])
        self.assertEqual(sorted(fake.movie_calls), [13, 603])

    def test_filling_the_cast_leaves_the_rest_of_the_sheet_alone(self):
        from core.services.tmdb_service import MediaMetadataEnricher

        db = SessionLocal()
        db.query(Media).update({Media.actors: None})
        db.commit()
        db.close()

        MediaMetadataEnricher(tmdb_service=_FakeTMDb()).fill_missing_details()

        db = SessionLocal()
        try:
            titles = sorted(m.title for m in db.query(Media).all())
        finally:
            db.close()

        self.assertIn("Forrest Gump", titles)
        self.assertNotIn("Titre TMDb", titles)

    def test_a_complete_library_is_not_fetched_again(self):
        from core.services.tmdb_service import MediaMetadataEnricher

        fake = _FakeTMDb()
        stats = MediaMetadataEnricher(tmdb_service=fake).fill_missing_details()

        self.assertEqual((fake.movie_calls, fake.tv_calls, fake.episode_calls), ([], [], []))
        self.assertEqual(stats["repaired"], 0)

    def test_an_old_database_gains_the_column(self):
        from sqlalchemy import inspect, text

        from core.database import init_db

        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE medias DROP COLUMN actors"))
        self.assertNotIn("actors", {c["name"] for c in inspect(engine).get_columns("medias")})

        init_db()

        self.assertIn("actors", {c["name"] for c in inspect(engine).get_columns("medias")})


class TestActorSearchInTheViews(unittest.TestCase):
    """Côté interface : la recherche par acteur, et la passe de scan qui l'alimente."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from core.services.media_service import MediaService

        _library_with_cast()
        self.service = MediaService()
        self.addCleanup(self.service.close)

    @staticmethod
    def _series_shown(view) -> list[str]:
        return [
            view._grid.itemAt(i).widget().title_label.toolTip()
            for i in range(view._grid.count())
        ]

    def _movies_view(self):
        from ui.views.movies_view import MoviesView

        view = MoviesView()
        view.refresh(self.service)
        self.addCleanup(view.deleteLater)
        return view

    def _series_view(self):
        from ui.views.series_view import SeriesView

        view = SeriesView()
        view.refresh(self.service)
        self.addCleanup(view.deleteLater)
        return view

    def _search_movies(self, view, text: str) -> list[str]:
        # Les cartes affichent « Titre (année) » : on repasse par la fiche.
        view._search.setText(text)
        view._apply_filters()
        return [
            self.service.get_media_by_id(card.media_id).title
            for card in view._grid._cards
        ]

    def test_an_actor_filters_the_movie_grid(self):
        view = self._movies_view()

        self.assertEqual(self._search_movies(view, "Keanu"), ["Matrix"])
        self.assertEqual(self._search_movies(view, "hanks"), ["Forrest Gump"])

    def test_a_title_still_filters_the_movie_grid(self):
        view = self._movies_view()

        self.assertEqual(self._search_movies(view, "gump"), ["Forrest Gump"])
        self.assertEqual(self._search_movies(view, "zzz"), [])

    def test_the_other_filters_still_apply_to_an_actor_search(self):
        view = self._movies_view()
        index = view._year_filter.findData(1999)
        view._year_filter.setCurrentIndex(index)

        self.assertEqual(self._search_movies(view, "Keanu"), ["Matrix"])
        self.assertEqual(self._search_movies(view, "hanks"), [])

    def test_the_movie_field_says_it_accepts_an_actor(self):
        view = self._movies_view()

        self.assertIn("acteur", view._search.placeholderText().lower())

    def test_an_actor_filters_the_series_grid(self):
        view = self._series_view()

        view._search.setText("Emilia")
        view._apply_search()
        self.assertEqual(self._series_shown(view), ["Game of Thrones"])

        view._search.setText("lewis")
        view._apply_search()
        self.assertEqual(self._series_shown(view), ["Band of Brothers"])

    def test_a_series_name_still_filters_the_series_grid(self):
        view = self._series_view()

        view._search.setText("thrones")
        view._apply_search()

        self.assertEqual(self._series_shown(view), ["Game of Thrones"])

    def test_the_series_field_says_it_accepts_an_actor(self):
        view = self._series_view()

        self.assertIn("acteur", view._search.placeholderText().lower())

    def test_a_full_scan_goes_and_gets_the_missing_casts(self):
        """Sans cette passe, une bibliothèque d'avant la colonne resterait muette."""
        from ui.views.settings_view import AutoScanWorker

        class _FakeService:
            def __init__(self):
                self.steps = []

            def scan_all_directories(self):
                self.steps.append("scan")
                return []

            def enrich_all_media(self, progress_callback=None):
                self.steps.append("enrich")
                return {"success": 0, "failed": 0}

            def fill_missing_details(self, progress_callback=None):
                self.steps.append("details")
                return {"repaired": 0, "failed": 0}

            def download_all_artwork(self, progress_callback=None):
                self.steps.append("artwork")
                return {}

        service = _FakeService()
        AutoScanWorker()._execute(service)

        self.assertEqual(service.steps, ["scan", "enrich", "details", "artwork"])


class TestEpisodeTitles(unittest.TestCase):
    """Le titre d'un épisode vient de TMDb : un réindexage ne doit pas l'effacer.

    Un nom de fichier n'en porte pas (« South.Park.S15E01.MULTi.1080p.mkv ») : le
    scan écrasait le titre TMDb par ce vide, et comme l'enrichissement ne repasse
    pas sur un média ayant déjà un tmdb_id, le nom ne revenait jamais.
    """

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.indexer = MediaIndexer(scanner=MediaScanner(min_video_size_mb=0))

    @staticmethod
    def _parsed(episode_title=None, season=15, episode=1):
        return ParsedMedia(
            file_path="/series/South.Park.S15E01.MULTi.1080p.mkv",
            title="South Park",
            media_type="episode",
            series="South Park",
            season=season,
            episode=episode,
            episode_title=episode_title,
        )

    def _enrich(self, media_id, **fields):
        """Pose ce que TMDb aurait écrit sur la fiche."""
        db = SessionLocal()
        try:
            media = db.query(Media).filter(Media.id == media_id).one()
            for name, value in fields.items():
                setattr(media, name, value)
            db.commit()
        finally:
            db.close()

    def _reload(self, media_id) -> Media:
        db = SessionLocal(expire_on_commit=False)
        try:
            return db.query(Media).filter(Media.id == media_id).one()
        finally:
            db.close()

    def test_a_rescan_keeps_the_title_that_tmdb_gave(self):
        media = self.indexer.index_media(self._parsed())
        self._enrich(media.id, tmdb_id=2190, episode_title="Humancenti-Pad")

        self.indexer.index_media(self._parsed())  # « 🔄 Tout mettre à jour »

        self.assertEqual(self._reload(media.id).episode_title, "Humancenti-Pad")

    def test_a_rescan_keeps_the_localised_title_of_a_film(self):
        parsed = ParsedMedia(
            file_path="/movies/The.Lord.of.the.Rings.2001.mkv",
            title="The Lord Of The Rings",
            year=2001,
            media_type="movie",
        )
        media = self.indexer.index_media(parsed)
        self._enrich(media.id, tmdb_id=120, title="Le Seigneur des anneaux")

        self.indexer.index_media(parsed)

        self.assertEqual(self._reload(media.id).title, "Le Seigneur des anneaux")

    def test_a_rescan_still_completes_a_media_not_yet_enriched(self):
        media = self.indexer.index_media(self._parsed())

        self.indexer.index_media(self._parsed(episode_title="HUMANCENTiPAD"))

        self.assertEqual(self._reload(media.id).episode_title, "HUMANCENTiPAD")

    def test_a_title_lost_by_an_older_version_comes_back(self):
        from core.services.tmdb_service import MediaMetadataEnricher

        media = self.indexer.index_media(self._parsed())
        self._enrich(media.id, tmdb_id=2190, actors="Trey Parker")

        fake = _FakeTMDb()
        stats = MediaMetadataEnricher(tmdb_service=fake).fill_missing_details()

        self.assertEqual(fake.episode_calls, [(2190, 15, 1)])
        self.assertEqual(stats["repaired"], 1)
        self.assertEqual(self._reload(media.id).episode_title, "Titre TMDb S15E01")

    def test_an_episode_that_still_has_its_title_is_left_alone(self):
        from core.services.tmdb_service import MediaMetadataEnricher

        media = self.indexer.index_media(self._parsed())
        self._enrich(
            media.id, tmdb_id=2190, actors="Trey Parker", episode_title="Humancenti-Pad"
        )

        fake = _FakeTMDb()
        MediaMetadataEnricher(tmdb_service=fake).fill_missing_details()

        self.assertEqual(fake.episode_calls, [])
        self.assertEqual(self._reload(media.id).episode_title, "Humancenti-Pad")

    def test_an_episode_without_numbering_is_never_asked_for(self):
        from core.services.tmdb_service import MediaMetadataEnricher

        media = self.indexer.index_media(self._parsed(season=None, episode=None))
        self._enrich(media.id, tmdb_id=2190, actors="Trey Parker")

        fake = _FakeTMDb()
        MediaMetadataEnricher(tmdb_service=fake).fill_missing_details()

        self.assertEqual(fake.episode_calls, [])


class TestMusicRemoval(unittest.TestCase):
    """La prise en charge audio a été retirée : rien ne doit la faire revenir."""

    def test_audio_files_are_not_media(self):
        scanner = MediaScanner(min_video_size_mb=0)
        for name in ["a.mp3", "b.flac", "c.wav", "d.m4a", "e.opus"]:
            self.assertFalse(scanner.is_media_file(name), name)

    def test_audio_files_are_skipped_by_a_scan(self):
        directory = tempfile.mkdtemp(prefix="epikodi_noaudio_")
        try:
            for name in ["Track.mp3", "Album.flac", "Inception.2010.mkv"]:
                open(os.path.join(directory, name), "w").close()

            scanner = MediaScanner(min_video_size_mb=0)
            results = scanner.scan_directory(directory, recursive=False)

            self.assertEqual([r.title for r in results], ["Inception"])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_startup_purges_legacy_music_rows(self):
        from sqlalchemy import text

        from core.database import init_db

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        db = SessionLocal()
        db.add_all(
            [
                Media(file_path="/mu/a.mp3", title="Track", media_type="music"),
                Media(file_path="/m/b.mkv", title="Film", media_type="movie"),
            ]
        )
        db.commit()
        db.close()

        init_db()

        db = SessionLocal()
        try:
            remaining = [m.media_type for m in db.query(Media).all()]
        finally:
            db.close()
        self.assertEqual(remaining, ["movie"])

        # Les tables de playlists doivent avoir disparu.
        with engine.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
        self.assertNotIn("playlists", tables)
        self.assertNotIn("playlist_items", tables)

    def test_stats_have_no_music_entry(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            self.assertNotIn("music", svc.get_stats())


class TestMediaWatcher(unittest.TestCase):
    """Surveillance temps réel des dossiers de la bibliothèque."""

    SETTLE = 0.3
    TIMEOUT = 20.0

    def setUp(self):
        from core.services.scanner import MediaWatcher

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.media_dir = tempfile.mkdtemp(prefix="epikodi_watch_")
        self.watcher = MediaWatcher(settle_interval=self.SETTLE)
        # Fichiers de test légers : on ne teste pas ici le seuil de taille.
        self.watcher.indexer.scanner.min_video_size_mb = 0

    def tearDown(self):
        self.watcher.stop()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _write(self, *parts, size=1024):
        path = os.path.join(self.media_dir, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        return path

    def _titles(self):
        db = SessionLocal()
        try:
            return sorted(m.title for m in db.query(Media).all())
        finally:
            db.close()

    def _wait_for(self, predicate, message):
        deadline = time.time() + self.TIMEOUT
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.1)
        self.fail(f"{message} (bibliothèque : {self._titles()})")

    def _start(self):
        self.assertTrue(self.watcher.watch(self.media_dir))
        self.assertTrue(self.watcher.start())

    # ── tests ────────────────────────────────────────────────────────────────

    def test_stop_without_start_is_safe(self):
        """MediaService.close() appelle stop() même si rien n'a été démarré."""
        from core.services.scanner import MediaWatcher

        MediaWatcher().stop()  # ne doit pas lever

    def test_start_without_directory_returns_false(self):
        self.assertFalse(self.watcher.start())
        self.assertFalse(self.watcher.is_running())

    def test_indexes_new_file(self):
        self._start()
        self._write("Inception.2010.1080p.mkv")
        self._wait_for(lambda: "Inception" in self._titles(), "fichier jamais indexé")

    def test_indexes_file_in_new_subdirectory(self):
        self._start()
        self._write("Breaking Bad", "Season 01", "Breaking.Bad.S01E01.mkv")
        self._wait_for(
            lambda: "Breaking Bad" in self._titles(), "sous-dossier jamais indexé"
        )

    def test_ignores_partial_copy_until_it_settles(self):
        """Un fichier encore en cours de copie ne doit pas être indexé."""
        self._start()
        path = os.path.join(self.media_dir, "Interstellar.2014.mkv")

        with open(path, "wb") as f:
            for _ in range(24):  # ~1,2 s d'écriture, soit plusieurs passes
                f.write(b"x" * 4096)
                f.flush()
                os.fsync(f.fileno())
                time.sleep(0.05)
                self.assertEqual(
                    self._titles(), [], "indexé alors que la copie continuait"
                )

        self._wait_for(
            lambda: "Interstellar" in self._titles(),
            "jamais indexé une fois la copie terminée",
        )

    def test_ignores_samples_and_tiny_files(self):
        """Le watcher applique les mêmes règles que le scan complet."""
        self.watcher.indexer.scanner.min_video_size_mb = 50
        self._start()
        self._write("Inception.sample.mkv", size=2048)
        self._write("partial.mkv", size=2048)

        time.sleep(self.SETTLE * 6)
        self.assertEqual(self._titles(), [])

    def test_removes_deleted_file(self):
        self._start()
        path = self._write("The.Matrix.1999.mkv")
        self._wait_for(lambda: "The Matrix" in self._titles(), "fichier jamais indexé")

        os.remove(path)
        self._wait_for(lambda: self._titles() == [], "fichier jamais retiré")

    def test_removes_deleted_directory(self):
        """La suppression d'un dossier n'émet qu'un seul événement."""
        self._start()
        self._write("Breaking Bad", "Season 01", "Breaking.Bad.S01E01.mkv")
        self._write("Breaking Bad", "Season 01", "Breaking.Bad.S01E02.mkv")
        self._wait_for(
            lambda: len(self._titles()) == 2, "épisodes jamais indexés"
        )

        shutil.rmtree(os.path.join(self.media_dir, "Breaking Bad"))
        self._wait_for(lambda: self._titles() == [], "épisodes jamais retirés")

    def test_can_restart_after_stop(self):
        """Un Observer arrêté est un thread mort : start() doit en recréer un."""
        self._start()
        self.watcher.stop()
        self.assertFalse(self.watcher.is_running())

        self.assertTrue(self.watcher.start())
        self.assertTrue(self.watcher.is_running())
        self._write("Avatar.2009.mkv")
        self._wait_for(
            lambda: "Avatar" in self._titles(), "surveillance morte après redémarrage"
        )

    def test_notifies_on_change(self):
        calls = []
        self.watcher.set_on_change(lambda: calls.append(1))
        self._start()
        self._write("Dune.2021.mkv")
        self._wait_for(lambda: calls, "callback on_change jamais appelé")

    def test_unwatch_stops_indexing(self):
        self._start()
        self.watcher.unwatch(self.media_dir)
        self._write("Ignored.2020.mkv")

        time.sleep(self.SETTLE * 6)
        self.assertEqual(self._titles(), [])


class TestMediaServiceWatching(unittest.TestCase):
    """Câblage MediaService : les dossiers actifs sont surveillés."""

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.media_dir = tempfile.mkdtemp(prefix="epikodi_svcwatch_")

    def tearDown(self):
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def test_start_watching_covers_active_directories(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            svc.add_media_directory(self.media_dir)
            # auto_enrich=False : aucun appel réseau pendant les tests.
            self.assertTrue(svc.start_watching(auto_enrich=False))
            self.assertTrue(svc.is_watching())
            self.assertIn(
                os.path.abspath(self.media_dir), svc.watcher.watched_directories()
            )
            svc.stop_watching()
            self.assertFalse(svc.is_watching())

    def test_start_watching_without_directory(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            self.assertFalse(svc.start_watching(auto_enrich=False))
            self.assertFalse(svc.is_watching())

    def test_directory_added_later_is_watched(self):
        """Ajouter le premier dossier depuis les Paramètres doit lancer la veille."""
        from core.services.media_service import MediaService

        with MediaService() as svc:
            self.assertFalse(svc.start_watching(auto_enrich=False))
            svc.add_media_directory(self.media_dir)

            self.assertTrue(svc.is_watching())
            self.assertIn(
                os.path.abspath(self.media_dir), svc.watcher.watched_directories()
            )


class TestDeleteMedia(unittest.TestCase):
    """Supprimer depuis l'interface efface le fichier, ses sous-titres et l'entrée."""

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.media_dir = tempfile.mkdtemp(prefix="epikodi_delete_")
        for name in ("Film.mkv", "Film.fr.srt", "Film.srt", "Film.2.mkv"):
            open(os.path.join(self.media_dir, name), "w").close()
        db = SessionLocal()
        db.add_all(
            [
                Media(file_path=os.path.join(self.media_dir, "Film.mkv"), title="Film"),
                Media(file_path=os.path.join(self.media_dir, "Film.2.mkv"), title="Film 2"),
                Media(file_path=os.path.join(self.media_dir, "gone.mkv"), title="Gone"),
            ]
        )
        db.commit()
        self.ids = {m.title: m.id for m in db.query(Media).all()}
        db.close()

    def tearDown(self):
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def test_delete_removes_files_subtitles_and_rows(self):
        from core.services.media_service import MediaService

        with MediaService() as svc:
            failed = svc.delete_media([self.ids["Film"], self.ids["Gone"]])
            self.assertEqual(failed, [])
            # Un fichier déjà absent du disque n'empêche pas de retirer l'entrée.
            self.assertEqual([m.title for m in svc.get_all_media()], ["Film 2"])

        # Les sous-titres partent avec la vidéo, pas un autre film au nom proche.
        self.assertEqual(os.listdir(self.media_dir), ["Film.2.mkv"])


class TestLeavingThePlayer(unittest.TestCase):
    """Quitter le lecteur pour une autre vue doit rester réversible.

    Avant, cliquer sur Accueil pendant un film laissait la lecture tourner en fond
    sans aucun moyen de revenir au lecteur.
    """

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.media_dir = tempfile.mkdtemp(prefix="epikodi_player_")
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        path = os.path.join(self.media_dir, "Inception.2010.mkv")
        with open(path, "wb") as f:
            f.write(b"\0" * 4096)

        db = SessionLocal()
        db.add(Media(file_path=path, title="Inception", year=2010,
                     media_type="movie", duration_sec=8880))
        db.add(Media(file_path=os.path.join(self.media_dir, "Absent.2021.mkv"),
                     title="Absent", year=2021, media_type="movie"))
        db.commit()
        db.close()

        from ui.main_window import MainWindow

        self.win = MainWindow()
        # isVisible() d'un enfant reste faux tant que la fenêtre n'est pas
        # affichée : sans show(), l'assertion ne testerait rien de réel.
        self.win.show()
        self.addCleanup(self.win.close)
        self.player = self.win._player_view

        from core.services.media_service import MediaService

        with MediaService() as svc:
            self.film_id = next(m.id for m in svc.get_movies() if m.title == "Inception")
            self.missing_id = next(m.id for m in svc.get_movies() if m.title == "Absent")

    def _play(self, media_id=None):
        from ui.main_window import VIEW_MOVIES

        self.win._navigate(VIEW_MOVIES)
        self.win._on_media_play(media_id or self.film_id)
        self.app.processEvents()

    def test_navigating_away_pauses_and_offers_a_way_back(self):
        from ui.main_window import VIEW_HOME, VIEW_PLAYER

        self._play()
        self.assertEqual(self.win._stack.currentIndex(), VIEW_PLAYER)
        self.assertFalse(self.win._btn_resume_player.isVisible())

        self.win._navigate(VIEW_HOME)
        self.app.processEvents()

        self.assertEqual(self.win._stack.currentIndex(), VIEW_HOME)
        self.assertFalse(self.player.video_widget.player.is_playing())
        self.assertTrue(self.player.has_media())
        self.assertTrue(self.win._btn_resume_player.isVisible())
        self.assertIn("Inception", self.win._btn_resume_player.text())

    def test_resume_returns_to_the_same_media(self):
        from ui.main_window import VIEW_HOME, VIEW_MOVIES, VIEW_PLAYER

        self._play()
        self.win._navigate(VIEW_HOME)
        self.win._navigate(VIEW_MOVIES)
        self.app.processEvents()
        self.assertTrue(self.win._btn_resume_player.isVisible())

        self.win._return_to_player()
        self.app.processEvents()

        self.assertEqual(self.win._stack.currentIndex(), VIEW_PLAYER)
        self.assertFalse(self.win._btn_resume_player.isVisible())
        self.assertEqual(self.player.current_title(), "Inception (2010)")
        # Le bouton retour du lecteur ramène là où on naviguait.
        self.assertEqual(self.win._previous_view, VIEW_MOVIES)

    def test_stopping_from_the_player_clears_the_offer(self):
        from ui.main_window import VIEW_HOME

        self._play()
        self.win._navigate(VIEW_HOME)
        self.win._return_to_player()
        self.player._on_back()  # bouton ⏹
        self.app.processEvents()

        self.assertFalse(self.player.has_media())
        self.assertFalse(self.win._btn_resume_player.isVisible())

    def test_a_finished_title_is_not_offered_for_resume(self):
        self._play()
        self.win._on_playback_finished()  # VLC signale la fin, rien à enchaîner
        self.app.processEvents()

        self.assertFalse(self.player.has_media())
        self.assertFalse(self.win._btn_resume_player.isVisible())

    def test_a_missing_file_is_not_offered_for_resume(self):
        from ui.main_window import VIEW_HOME

        self._play(self.missing_id)
        self.win._navigate(VIEW_HOME)
        self.app.processEvents()

        self.assertFalse(self.player.has_media())
        self.assertFalse(self.win._btn_resume_player.isVisible())

    def test_resume_without_media_is_a_no_op(self):
        from ui.main_window import VIEW_HOME

        self.win._navigate(VIEW_HOME)
        self.win._return_to_player()
        self.app.processEvents()

        self.assertEqual(self.win._stack.currentIndex(), VIEW_HOME)


class TestPlayerShutdown(unittest.TestCase):
    """Fermeture pendant une lecture.

    Deux pannes observées, toutes deux reproduites hors suite avec un vrai flux :
    l'application se figeait dans `libvlc_media_player_stop()` appelé depuis le
    thread graphique pendant que VLC montait sa sortie Direct3D, et elle plantait
    sèchement quand la boucle Qt se terminait sans passer par closeEvent.
    """

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        from ui.main_window import MainWindow

        self.win = MainWindow()
        self.addCleanup(self.win.close)
        self.player = self.win._player_view
        self.video = self.player.video_widget

    def test_stop_hands_the_window_back_before_stopping_vlc(self):
        """L'ordre est ce qui casse l'interblocage : détacher, puis arrêter."""
        calls = []
        self.video.detach_surface = lambda: calls.append("detach")
        original_stop = self.video.player.stop
        self.video.player.stop = lambda: calls.append("stop") or original_stop()

        self.player._stop_vlc()

        self.assertEqual(calls, ["detach", "stop"])

    def test_stop_does_not_block_forever(self):
        """Un stop() qui ne rend jamais la main ne doit pas figer l'application."""
        import threading

        never = threading.Event()
        self.video.player.stop = never.wait  # ne revient jamais

        started = time.monotonic()
        finished = self.player._stop_vlc(timeout=0.5)
        elapsed = time.monotonic() - started

        self.assertFalse(finished, "aurait dû signaler l'abandon")
        self.assertLess(elapsed, 5.0, f"bloqué {elapsed:.1f}s")

    def test_shutdown_releases_libvlc(self):
        self.assertFalse(self.video.is_released())
        self.player.shutdown()
        self.assertTrue(self.video.is_released())

    def test_shutdown_is_idempotent(self):
        self.win._shutdown_player()
        self.win._shutdown_player()  # closeEvent puis aboutToQuit
        self.assertTrue(self.video.is_released())

    def test_player_shutdown_can_be_called_twice(self):
        """Un second arrêt touchait un lecteur libéré : violation d'accès."""
        self.player.shutdown()
        self.player.shutdown()
        self.player.stop()  # ne doit plus rien tenter côté libVLC
        self.assertTrue(self.video.is_released())

    def test_close_event_shuts_the_player_down(self):
        self.win.close()
        self.assertTrue(self.video.is_released())

    def test_about_to_quit_shuts_the_player_down(self):
        """Sortir de la boucle sans closeEvent laissait libVLC tourner pendant
        l'arrêt de l'interpréteur, ce qui tuait le processus."""
        self.app.aboutToQuit.emit()
        self.assertTrue(self.video.is_released())

    def test_a_released_player_is_never_polled_again(self):
        self.player.shutdown()
        # Ces deux slots sont pilotés par des QTimer : s'ils touchaient un lecteur
        # libéré, le crash serait natif et non rattrapable.
        self.player._update_ui()
        self.player._save_progress()

    def test_surface_is_reattached_before_each_playback(self):
        """stop() rend la fenêtre à Qt : sans rattachement, la lecture suivante
        s'ouvrirait dans une fenêtre VLC séparée."""
        directory = tempfile.mkdtemp(prefix="epikodi_surface_")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, "Clip.2024.mkv")
        with open(path, "wb") as f:
            f.write(b"\0" * 2048)

        attached = []
        self.video.attach_surface = lambda: attached.append(True)
        self.player.play_media(
            Media(id=1, file_path=path, title="Clip", media_type="movie")
        )
        self.addCleanup(self.player.stop)

        self.assertEqual(len(attached), 1)


class _RecordingKeepAwake:
    """Enregistre les demandes du lecteur sans toucher à la session."""

    def __init__(self):
        self.active = False
        self.acquisitions = 0

    def acquire(self):
        if not self.active:
            self.acquisitions += 1
        self.active = True

    def release(self):
        self.active = False

    def set_active(self, active):
        if active:
            self.acquire()
        else:
            self.release()

    def is_active(self):
        return self.active


class _CountingKeepAwake(KeepAwake):
    """KeepAwake dont les appels système sont remplacés par des compteurs."""

    def __init__(self, works=True):
        super().__init__()
        self.works = works
        self.starts = 0
        self.stops = 0

    def _start(self):
        self.starts += 1
        return self.works

    def _stop(self):
        self.stops += 1


class TestScreenStaysAwake(unittest.TestCase):
    """L'écran s'éteignait en plein film.

    Le système ne compte que le clavier et la souris comme signes d'activité, et
    un spectateur n'y touche pas pendant deux heures : il faut lui dire
    explicitement qu'une vidéo tourne, et le lui retirer dès qu'elle s'arrête.
    """

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.media_dir = tempfile.mkdtemp(prefix="epikodi_awake_")
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        self.path = os.path.join(self.media_dir, "Inception.2010.mkv")
        with open(self.path, "wb") as f:
            f.write(b"\0" * 4096)

        from ui.main_window import MainWindow

        self.win = MainWindow()
        self.addCleanup(self.win.close)
        self.player = self.win._player_view
        # Inhiber pour de vrai agirait sur la session de l'utilisateur (ou
        # lancerait un processus annexe) : on n'observe que les demandes émises.
        self.keep_awake = _RecordingKeepAwake()
        self.player._keep_awake = self.keep_awake

    def _play(self):
        self.player.play_media(
            Media(id=1, file_path=self.path, title="Inception", media_type="movie")
        )
        self.addCleanup(self.player.stop)

    def test_playback_keeps_the_screen_awake(self):
        self._play()
        self.assertTrue(self.keep_awake.is_active())

    def test_a_missing_file_does_not_keep_the_screen_awake(self):
        self.player.play_media(
            Media(
                id=2,
                file_path=os.path.join(self.media_dir, "Absent.mkv"),
                title="Absent",
                media_type="movie",
            )
        )
        self.assertFalse(self.keep_awake.is_active())

    def test_stopping_lets_the_screen_sleep_again(self):
        self._play()
        self.player.stop()
        self.assertFalse(self.keep_awake.is_active())

    def test_the_end_of_a_film_lets_the_screen_sleep_again(self):
        self._play()
        self.player._on_playback_ended()
        self.assertFalse(self.keep_awake.is_active())

    def test_leaving_the_player_lets_the_screen_sleep_and_resume_restores_it(self):
        self._play()
        self.player.suspend()
        self.assertFalse(self.keep_awake.is_active())

        self.player.resume()
        self.assertTrue(self.keep_awake.is_active())

    def test_the_state_follows_vlc(self):
        """Une pause relâche l'inhibition, la reprise la repose."""
        self._play()

        self.player.video_widget.player.is_playing = lambda: False
        self.player._sync_keep_awake()
        self.assertFalse(self.keep_awake.is_active())

        self.player.video_widget.player.is_playing = lambda: True
        self.player._sync_keep_awake()
        self.assertTrue(self.keep_awake.is_active())

    def test_a_released_player_never_holds_the_screen_awake(self):
        self._play()
        self.player.shutdown()
        self.player._sync_keep_awake()  # piloté par un QTimer encore vivant
        self.assertFalse(self.keep_awake.is_active())


class TestKeepAwake(unittest.TestCase):
    """Mécanique de l'inhibition, indépendamment de la plateforme."""

    def test_acquiring_twice_only_asks_the_system_once(self):
        keep = _CountingKeepAwake()
        keep.acquire()
        keep.acquire()
        self.assertEqual(keep.starts, 1)
        self.assertTrue(keep.is_active())

    def test_the_state_is_reasserted_after_a_while(self):
        """Windows perd l'inhibition après un verrouillage de session."""
        keep = _CountingKeepAwake()
        keep.acquire()
        keep._last_assert -= 3600  # une heure plus tard
        keep.acquire()
        self.assertEqual(keep.starts, 2)

    def test_releasing_without_acquiring_is_a_no_op(self):
        keep = _CountingKeepAwake()
        keep.release()
        self.assertEqual(keep.stops, 0)

    def test_release_then_acquire_asks_again(self):
        keep = _CountingKeepAwake()
        keep.acquire()
        keep.release()
        keep.acquire()
        self.assertEqual((keep.starts, keep.stops), (2, 1))
        self.assertTrue(keep.is_active())

    def test_a_failed_inhibition_is_not_reported_as_active(self):
        """Sans mécanisme disponible, on retombe sur le comportement d'avant."""
        keep = _CountingKeepAwake(works=False)
        keep.acquire()
        self.assertFalse(keep.is_active())
        keep.release()  # ne doit rien tenter de défaire
        self.assertEqual(keep.stops, 0)


class TestDownloadQueue(unittest.TestCase):
    """File de téléchargement (écran Téléchargements).

    Les transferts sont testés contre un vrai serveur HTTP local : la reprise
    dépend du dialogue exact avec le serveur (en-tête `Range`, réponse 206 ou 200),
    et c'est précisément la partie qui peut corrompre un fichier.
    """

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        payload = bytes(range(256)) * 4096  # 1 Mio, soit 4 blocs de 256 Kio

        class Handler(BaseHTTPRequestHandler):
            honour_range = True
            fail = False

            def do_GET(self):
                if Handler.fail:
                    self.send_error(500, "Nope")
                    return

                start = 0
                header = self.headers.get("Range", "")
                if header and Handler.honour_range:
                    start = int(header.split("=")[1].split("-")[0])
                    body = payload[start:]
                    self.send_response(206)
                    self.send_header(
                        "Content-Range",
                        f"bytes {start}-{len(payload) - 1}/{len(payload)}",
                    )
                else:
                    body = payload
                    self.send_response(200)

                if "disposition" in self.path:
                    self.send_header(
                        "Content-Disposition", 'attachment; filename="Vrai.Nom.mkv"'
                    )
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass  # le serveur de test n'a pas à polluer la sortie

        cls.payload = payload
        cls.handler = Handler
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        from pathlib import Path

        import core.config
        from core.services.download_service import DownloadService

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.handler.honour_range = True
        self.handler.fail = False

        self.directory = tempfile.mkdtemp(prefix="epikodi_downloads_")
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)

        # Le settings.json réel porte la clé TMDb de l'utilisateur : on écrit ailleurs.
        self.addCleanup(
            setattr, core.config, "SETTINGS_FILE", core.config.SETTINGS_FILE
        )
        core.config.SETTINGS_FILE = Path(self.directory) / "settings.json"
        core.config.set_setting("download_dir", self.directory)

        self.service = DownloadService()
        self.addCleanup(self.service.close)

    def _url(self, name: str = "/Film.2024.mkv") -> str:
        return self.base_url + name

    def test_a_queued_download_takes_its_name_from_the_url(self):
        download = self.service.add(self._url())

        self.assertEqual(download.filename, "Film.2024.mkv")
        self.assertEqual(download.status, "queued")
        self.assertEqual(
            download.file_path, os.path.join(self.directory, "Film.2024.mkv")
        )

    def test_a_link_that_is_not_http_is_refused(self):
        self.assertIsNone(self.service.add("magnet:?xt=urn:btih:deadbeef"))
        self.assertIsNone(self.service.add(""))
        self.assertEqual(self.service.get_all(), [])

    def test_a_download_lands_complete_in_the_destination(self):
        download = self.service.add(self._url())

        self.assertTrue(self.service.run(download.id))

        with open(download.file_path, "rb") as f:
            self.assertEqual(f.read(), self.payload)
        self.assertEqual(download.status, "done")
        self.assertEqual(download.total_bytes, len(self.payload))
        self.assertFalse(os.path.exists(download.part_path))

    def test_an_interrupted_download_leaves_a_part_file(self):
        """Le nom définitif n'apparaît qu'à la fin : `.part` n'est pas indexable,
        donc la bibliothèque ne voit jamais un fichier à moitié arrivé."""
        download = self.service.add(self._url())

        self.assertFalse(self.service.run(download.id, should_stop=_stop_after(1)))

        self.assertEqual(download.status, "paused")
        self.assertTrue(os.path.exists(download.part_path))
        self.assertFalse(os.path.exists(download.file_path))
        self.assertLess(os.path.getsize(download.part_path), len(self.payload))

    def test_an_interrupted_download_resumes_where_it_stopped(self):
        download = self.service.add(self._url())
        self.service.run(download.id, should_stop=_stop_after(1))
        written = os.path.getsize(download.part_path)

        self.assertTrue(self.service.run(download.id))

        with open(download.file_path, "rb") as f:
            self.assertEqual(f.read(), self.payload)
        self.assertGreater(written, 0, "rien n'avait été écrit, la reprise ne prouve rien")

    def test_a_server_that_ignores_range_starts_over(self):
        """Répondre 200 à une requête Range renvoie tout le fichier : continuer
        d'écrire à la fin du `.part` dupliquerait le début."""
        download = self.service.add(self._url())
        self.service.run(download.id, should_stop=_stop_after(1))
        self.handler.honour_range = False

        self.assertTrue(self.service.run(download.id))

        with open(download.file_path, "rb") as f:
            self.assertEqual(f.read(), self.payload)

    def test_a_failing_server_marks_the_download_in_error(self):
        self.handler.fail = True
        download = self.service.add(self._url())

        self.assertFalse(self.service.run(download.id))

        self.assertEqual(download.status, "error")
        self.assertTrue(download.error)

    def test_the_name_offered_by_the_server_wins(self):
        download = self.service.add(self._url("/telechargement?disposition=1"))

        self.service.run(download.id)

        self.assertEqual(download.filename, "Vrai.Nom.mkv")
        self.assertTrue(os.path.exists(os.path.join(self.directory, "Vrai.Nom.mkv")))

    def test_two_downloads_of_the_same_name_do_not_collide(self):
        first = self.service.add(self._url())
        second = self.service.add(self._url())

        self.assertNotEqual(first.file_path, second.file_path)
        self.assertEqual(second.filename, "Film.2024 (2).mkv")

    def test_the_queue_is_served_in_order(self):
        first = self.service.add(self._url("/A.2024.mkv"))
        second = self.service.add(self._url("/B.2024.mkv"))

        self.assertEqual(self.service.next_queued().id, first.id)
        self.service.run(first.id)
        self.assertEqual(self.service.next_queued().id, second.id)
        self.service.run(second.id)
        self.assertIsNone(self.service.next_queued())

    def test_pausing_takes_the_queue_out_of_the_waiting_list(self):
        self.service.add(self._url("/A.2024.mkv"))
        self.service.add(self._url("/B.2024.mkv"))

        self.assertEqual(self.service.pause_all(), 2)

        self.assertIsNone(self.service.next_queued())
        self.assertFalse(self.service.has_pending())

    def test_a_paused_download_can_be_queued_again(self):
        download = self.service.add(self._url())
        self.service.pause_all()

        self.assertTrue(self.service.requeue(download.id))
        self.assertEqual(download.status, "queued")

    def test_a_finished_download_is_not_queued_again(self):
        download = self.service.add(self._url())
        self.service.run(download.id)

        self.assertFalse(self.service.requeue(download.id))
        self.assertEqual(download.status, "done")

    def test_removing_an_entry_takes_the_partial_file_with_it(self):
        download = self.service.add(self._url())
        self.service.run(download.id, should_stop=_stop_after(1))
        part = download.part_path

        self.assertTrue(self.service.remove(download.id))

        self.assertFalse(os.path.exists(part))
        self.assertEqual(self.service.get_all(), [])

    def test_a_failing_progress_callback_does_not_abort_the_transfer(self):
        """L'affichage ne doit pas pouvoir casser un téléchargement."""

        def boom(received, total):
            raise OverflowError("écran cassé")

        download = self.service.add(self._url())

        self.assertTrue(self.service.run(download.id, on_progress=boom))

        with open(download.file_path, "rb") as f:
            self.assertEqual(f.read(), self.payload)

    def test_a_partial_file_is_never_indexed(self):
        """C'est ce qui permet de télécharger directement dans un dossier surveillé."""
        download = self.service.add(self._url())
        self.service.run(download.id, should_stop=_stop_after(1))

        results = MediaScanner(min_video_size_mb=0).scan_directory(
            self.directory, recursive=False
        )

        self.assertEqual(results, [])

    def test_the_destination_falls_back_on_the_first_watched_folder(self):
        from core.config import set_setting
        from core.models import MediaDirectory

        set_setting("download_dir", "")
        watched = os.path.join(self.directory, "surveille")
        os.makedirs(watched)
        self.service.db.add(MediaDirectory(path=watched, is_active=True))
        self.service.db.commit()

        self.assertEqual(str(self.service.download_dir()), watched)
        self.assertTrue(self.service.destination_is_watched())

    def test_an_unwatched_destination_is_reported(self):
        from core.models import MediaDirectory

        self.service.db.add(
            MediaDirectory(path=os.path.join(self.directory, "ailleurs"), is_active=True)
        )
        self.service.db.commit()

        self.assertFalse(self.service.destination_is_watched())


def _make_rar(entries: dict) -> bytes:
    """RAR 4 sans compression, assez pour bsdtar. Clés : chemins séparés par « \\ ».

    Aucun outil libre ne crée de RAR : on écrit les blocs à la main.
    """
    import struct
    import zlib

    def block(head_type, flags, body):
        rest = struct.pack("<BHH", head_type, flags, 7 + len(body)) + body
        return struct.pack("<H", zlib.crc32(rest) & 0xFFFF) + rest

    out = b"Rar!\x1a\x07\x00" + block(0x73, 0, b"\x00" * 6)
    for name, data in entries.items():
        raw = name.encode()
        header = struct.pack(
            "<IIBIIBBHI",
            len(data),  # taille compressée
            len(data),  # taille réelle
            2,  # système hôte : Windows
            zlib.crc32(data),
            0x5A210000,  # date DOS
            20,  # version requise
            0x30,  # méthode « store »
            len(raw),
            0x20,  # attribut « archive »
        )
        out += block(0x74, 0x8000, header + raw) + data
    return out + block(0x7B, 0x4000, b"")


def _bsdtar_available() -> bool:
    from core.services.archives import _bsdtar

    return _bsdtar() is not None


class TestArchiveExtraction(unittest.TestCase):
    """Décompression d'un ZIP ou d'un RAR téléchargé, puis suppression de l'archive."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            payload = b""

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(Handler.payload)))
                self.end_headers()
                self.wfile.write(Handler.payload)

            def log_message(self, *args):
                pass

        cls.handler = Handler
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        from pathlib import Path

        import core.config
        from core.services.download_service import DownloadService

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.directory = tempfile.mkdtemp(prefix="epikodi_zip_")
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.addCleanup(
            setattr, core.config, "SETTINGS_FILE", core.config.SETTINGS_FILE
        )
        core.config.SETTINGS_FILE = Path(self.directory) / "settings.json"
        core.config.set_setting("download_dir", self.directory)

        self.service = DownloadService()
        self.addCleanup(self.service.close)

    def _serve_zip(self, entries: dict):
        """Publie une archive construite à la volée. Clés = chemins dans l'archive."""
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            for name, content in entries.items():
                bundle.writestr(zipfile.ZipInfo(name), content)
        self.handler.payload = buffer.getvalue()

    def _download(self, name: str = "/Pack.zip"):
        download = self.service.add(self.base_url + name)
        self.service.run(download.id)
        return download

    def test_a_downloaded_zip_is_extracted_then_removed(self):
        self._serve_zip({"Film.2024.mkv": b"video", "Film.2024.srt": b"1\n"})

        download = self._download()

        self.assertEqual(download.status, "done")
        self.assertTrue(os.path.exists(os.path.join(self.directory, "Film.2024.mkv")))
        self.assertTrue(os.path.exists(os.path.join(self.directory, "Film.2024.srt")))
        self.assertFalse(os.path.exists(download.file_path), "le ZIP aurait dû partir")
        self.assertEqual(download.extracted_to, self.directory)

    def test_the_tree_inside_the_archive_is_preserved(self):
        self._serve_zip({"Serie.S01/S01E01.mkv": b"video"})

        self._download()

        self.assertTrue(
            os.path.exists(os.path.join(self.directory, "Serie.S01", "S01E01.mkv"))
        )

    def test_an_entry_escaping_the_destination_is_skipped(self):
        """Une archive peut contenir « ../ailleurs » : l'extraction écrirait alors
        hors du dossier de destination."""
        self._serve_zip({"../evade.mkv": b"video", "Film.mkv": b"video"})

        self._download()

        escaped = os.path.join(os.path.dirname(self.directory), "evade.mkv")
        self.assertFalse(os.path.exists(escaped), "l'entrée est sortie du dossier")
        self.assertTrue(os.path.exists(os.path.join(self.directory, "Film.mkv")))

    def test_an_existing_file_is_left_alone(self):
        existing = os.path.join(self.directory, "Film.mkv")
        with open(existing, "wb") as f:
            f.write(b"la version que j'avais deja")
        self._serve_zip({"Film.mkv": b"la version de l'archive"})

        self._download()

        with open(existing, "rb") as f:
            self.assertEqual(f.read(), b"la version que j'avais deja")

    def test_a_corrupt_archive_keeps_the_file_and_explains(self):
        """Le téléchargement, lui, a réussi : on ne jette pas le fichier."""
        self.handler.payload = b"ceci n'est pas une archive"

        download = self._download()

        self.assertEqual(download.status, "done")
        self.assertTrue(os.path.exists(download.file_path))
        self.assertIn("Archive", download.error)
        self.assertIsNone(download.extracted_to)

    def test_a_video_file_is_not_touched(self):
        self.handler.payload = b"video"

        download = self._download("/Film.2024.mkv")

        self.assertTrue(os.path.exists(download.file_path))
        self.assertIsNone(download.extracted_to)

    def test_extraction_can_be_turned_off(self):
        self._serve_zip({"Film.mkv": b"video"})
        download = self.service.add(self.base_url + "/Pack.zip")

        self.service.run(download.id, extract_archives=False)

        self.assertTrue(os.path.exists(download.file_path))
        self.assertFalse(os.path.exists(os.path.join(self.directory, "Film.mkv")))

    def _serve_rar(self, entries: dict):
        self.handler.payload = _make_rar(entries)

    @unittest.skipUnless(_bsdtar_available(), "bsdtar absent : RAR non testable")
    def test_a_downloaded_rar_is_extracted_then_removed(self):
        self._serve_rar({"Film.mkv": b"video", "Serie.S01\\S01E01.mkv": b"ep"})

        download = self._download("/Pack.rar")

        self.assertEqual(download.status, "done")
        self.assertIsNone(download.error)
        with open(os.path.join(self.directory, "Film.mkv"), "rb") as f:
            self.assertEqual(f.read(), b"video")
        self.assertTrue(
            os.path.exists(os.path.join(self.directory, "Serie.S01", "S01E01.mkv"))
        )
        self.assertFalse(os.path.exists(download.file_path), "le RAR aurait dû partir")

    @unittest.skipUnless(_bsdtar_available(), "bsdtar absent : RAR non testable")
    def test_an_existing_file_is_left_alone_in_a_rar(self):
        existing = os.path.join(self.directory, "Film.mkv")
        with open(existing, "wb") as f:
            f.write(b"la mienne")
        self._serve_rar({"Film.mkv": b"celle de l'archive"})

        download = self._download("/Pack.rar")

        self.assertIsNone(download.error)
        with open(existing, "rb") as f:
            self.assertEqual(f.read(), b"la mienne")

    @unittest.skipUnless(_bsdtar_available(), "bsdtar absent : RAR non testable")
    def test_a_rar_entry_escaping_the_destination_is_refused(self):
        self._serve_rar({"..\\evade.mkv": b"bad", "Film.mkv": b"video"})

        download = self._download("/Pack.rar")

        escaped = os.path.join(os.path.dirname(self.directory), "evade.mkv")
        self.assertFalse(os.path.exists(escaped), "l'entrée est sortie du dossier")
        # L'archive suspecte reste là, avec le motif sur sa ligne.
        self.assertTrue(os.path.exists(download.file_path))
        self.assertIn("..", download.error)

    @unittest.skipUnless(_bsdtar_available(), "bsdtar absent : RAR non testable")
    def test_a_corrupt_rar_keeps_the_file_and_explains(self):
        self.handler.payload = b"ceci n'est pas une archive"

        download = self._download("/Pack.rar")

        self.assertEqual(download.status, "done")
        self.assertTrue(os.path.exists(download.file_path))
        self.assertIn("Archive", download.error)


class TestUpdater(unittest.TestCase):
    """Mise à jour automatique : la release GitHub est simulée en local."""

    @classmethod
    def setUpClass(cls):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            release = None  # None : l'API répond 404, aucune release publiée
            payload = b""

            def do_GET(self):
                if self.path == "/latest":
                    if Handler.release is None:
                        self.send_response(404)
                        self.end_headers()
                        return
                    body = json.dumps(Handler.release).encode()
                else:
                    body = Handler.payload
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.handler = Handler
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        from pathlib import Path

        from core.services import updater

        self.updater = updater
        self.directory = Path(tempfile.mkdtemp(prefix="epikodi_update_"))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        for name, value in (
            ("RELEASES_URL", self.base_url + "/latest"),
            ("UPDATE_DIR", self.directory / "update"),
        ):
            self.addCleanup(setattr, updater, name, getattr(updater, name))
            setattr(updater, name, value)
        self.handler.release = None

    def _publish(self, tag: str):
        self.handler.release = {
            "tag_name": tag,
            "assets": [
                {"name": "EpiKodi-linux", "browser_download_url": "ailleurs"},
                {
                    "name": f"EpiKodi-{tag}-windows.zip",
                    "browser_download_url": self.base_url + "/asset.zip",
                    "size": 3,
                },
            ],
        }

    def test_a_newer_release_is_offered(self):
        from core.config import APP_VERSION

        major, minor, patch = (int(n) for n in APP_VERSION.split("."))
        self._publish(f"v{major}.{minor}.{patch + 1}")

        release = self.updater.check()

        self.assertEqual(release.version, f"{major}.{minor}.{patch + 1}")
        self.assertEqual(release.url, self.base_url + "/asset.zip")

    def test_the_same_or_an_older_release_is_ignored(self):
        from core.config import APP_VERSION

        self._publish(f"v{APP_VERSION}")
        self.assertIsNone(self.updater.check())
        self._publish("v0.9.99")
        self.assertIsNone(self.updater.check())

    def test_no_release_at_all(self):
        self.assertIsNone(self.updater.check())

    def test_download_unpacks_the_application_folder(self):
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("EpiKodi/EpiKodi.exe", b"exe")
            bundle.writestr("EpiKodi/_internal/lib.dll", b"dll")
        self.handler.payload = buffer.getvalue()
        seen = []

        staging = self.updater.download(
            self.updater.Release("9.9.9", self.base_url + "/asset.zip", 0),
            progress=lambda received, total: seen.append((received, total)),
        )

        self.assertTrue((staging / "EpiKodi.exe").is_file())
        self.assertTrue((staging / "_internal" / "lib.dll").is_file())
        self.assertEqual(seen[-1], (len(self.handler.payload),) * 2)

    def test_an_archive_without_the_application_is_refused(self):
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("autre.txt", b"rien")
        self.handler.payload = buffer.getvalue()

        with self.assertRaises(self.updater.UpdateError):
            self.updater.download(
                self.updater.Release("9.9.9", self.base_url + "/asset.zip", 0)
            )

    @unittest.skipUnless(sys.platform == "win32", "robocopy et PowerShell : Windows")
    def test_install_script_mirrors_the_new_version(self):
        """Le script remplace le dossier : fichiers périmés retirés, nouveaux posés."""
        import subprocess

        staging = self.directory / "update" / "EpiKodi"
        target = self.directory / "installed"
        (staging / "_internal").mkdir(parents=True)
        (target / "_internal").mkdir(parents=True)
        (target / "_internal" / "obsolete.dll").write_bytes(b"old")
        (staging / "_internal" / "new.dll").write_bytes(b"new")
        # Relancé à la fin du script : un vrai programme, inoffensif et bref.
        windows = os.environ.get("SystemRoot", r"C:\Windows")
        shutil.copy(os.path.join(windows, "System32", "hostname.exe"), staging / "EpiKodi.exe")
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()

        script = self.updater.write_install_script(staging, target, gone.pid)
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        self.assertTrue((target / "_internal" / "new.dll").is_file())
        self.assertFalse((target / "_internal" / "obsolete.dll").exists())
        self.assertTrue((target / "EpiKodi.exe").is_file())
        self.assertFalse(staging.exists(), "le dossier de transit aurait dû partir")


class TestOneFichierLinks(unittest.TestCase):
    """Résolution d'un lien d'hébergeur avant le transfert.

    Un lien 1fichier désigne une page HTML, pas le fichier : sans échange préalable
    auprès de l'API, le téléchargement enregistrerait la page. L'API est simulée en
    local, aucun test ne sort de la machine.
    """

    @classmethod
    def setUpClass(cls):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        payload = b"EPIKODI--" * 2048

        class Handler(BaseHTTPRequestHandler):
            answer_ok = True
            message = "Not a premium account"
            error_code = 200  # 1fichier répond aussi en KO avec un code 4xx
            calls = []

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                Handler.calls.append(
                    (self.path, self.headers.get("Authorization"), body)
                )

                if Handler.answer_ok:
                    reply = {
                        "status": "OK",
                        "url": f"http://{self.headers['Host']}/direct/Film.2024.mkv",
                    }
                    self._send_json(json.dumps(reply).encode())
                else:
                    reply = {"status": "KO", "message": Handler.message}
                    self._send_json(json.dumps(reply).encode(), Handler.error_code)

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _send_json(self, encoded, code=200):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *args):
                pass

        cls.payload = payload
        cls.handler = Handler
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.api_base = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        from pathlib import Path

        import core.config
        from core.services import link_resolvers
        from core.services.download_service import DownloadService

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.handler.answer_ok = True
        self.handler.error_code = 200
        self.handler.calls = []

        self.addCleanup(
            setattr, link_resolvers, "ONEFICHIER_API", link_resolvers.ONEFICHIER_API
        )
        link_resolvers.ONEFICHIER_API = self.api_base

        self.directory = tempfile.mkdtemp(prefix="epikodi_1fichier_")
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.addCleanup(
            setattr, core.config, "SETTINGS_FILE", core.config.SETTINGS_FILE
        )
        core.config.SETTINGS_FILE = Path(self.directory) / "settings.json"
        core.config.set_setting("download_dir", self.directory)
        core.config.set_setting("onefichier_api_key", "cle-de-test")

        self.page_url = "https://1fichier.com/?abc123"
        self.service = DownloadService()
        self.addCleanup(self.service.close)

    def test_an_ordinary_url_is_left_alone(self):
        from core.services.link_resolvers import resolve

        url = "https://example.com/Film.mkv"

        self.assertEqual(resolve(url), url)
        self.assertEqual(self.handler.calls, [])

    def test_a_direct_subdomain_is_not_resolved_again(self):
        """L'API rend un lien sur `sX.1fichier.com` : le repasser au résolveur
        échouerait, alors que c'est déjà le fichier."""
        from core.services.link_resolvers import resolve

        url = "https://s01.1fichier.com/d123/Film.mkv"

        self.assertEqual(resolve(url), url)
        self.assertEqual(self.handler.calls, [])

    def test_a_page_link_is_resolved_then_transferred(self):
        download = self.service.add(self.page_url)

        self.assertTrue(self.service.run(download.id))

        self.assertEqual(download.status, "done")
        with open(download.file_path, "rb") as f:
            self.assertEqual(f.read(), self.payload)

    def test_the_name_comes_from_the_resolved_link(self):
        """Une page n'a pas de nom de fichier : sans ce repli, le média
        s'appellerait « telechargement-<horodatage> » et guessit n'en tirerait rien."""
        download = self.service.add(self.page_url)

        self.service.run(download.id)

        self.assertEqual(download.filename, "Film.2024.mkv")

    def test_an_affiliate_parameter_is_dropped(self):
        """« ?abc&af=5010551 » s'ouvre dans un navigateur mais l'API répond
        « Resource not found » : elle veut l'identifiant seul."""
        download = self.service.add("https://1fichier.com/?3kp8fm6y9m&af=5010551")

        self.assertTrue(self.service.run(download.id))

        _, _, body = self.handler.calls[0]
        self.assertEqual(body.get("url"), "https://1fichier.com/?3kp8fm6y9m")

    def test_a_folder_link_is_refused_before_any_call(self):
        download = self.service.add("https://1fichier.com/dir/AbCdEf12")

        self.assertFalse(self.service.run(download.id))

        self.assertIn("dossier", download.error)
        self.assertEqual(self.handler.calls, [])

    def test_the_key_travels_as_a_bearer_token(self):
        download = self.service.add(self.page_url)

        self.service.run(download.id)

        path, authorization, body = self.handler.calls[0]
        self.assertEqual(path, "/v1/download/get_token.cgi")
        self.assertEqual(authorization, "Bearer cle-de-test")
        self.assertEqual(body.get("url"), self.page_url)

    def test_without_a_key_the_link_is_refused_before_any_call(self):
        from core.config import set_setting

        set_setting("onefichier_api_key", "")
        download = self.service.add(self.page_url)

        self.assertFalse(self.service.run(download.id))

        self.assertEqual(download.status, "error")
        self.assertIn("clé API", download.error)
        self.assertEqual(self.handler.calls, [])

    def test_the_api_message_is_reported(self):
        """Seul le message de 1fichier distingue une clé invalide d'un compte sans
        abonnement ou d'un fichier supprimé."""
        self.handler.answer_ok = False
        download = self.service.add(self.page_url)

        self.assertFalse(self.service.run(download.id))

        self.assertEqual(download.status, "error")
        self.assertIn("Not a premium account", download.error)
        self.assertFalse(os.path.exists(download.file_path))

    def test_the_reason_survives_an_http_error_code(self):
        """1fichier répond 401 pour une clé refusée et 404 pour un lien mort, avec
        le motif dans le corps : s'arrêter au code perdrait la distinction."""
        self.handler.answer_ok = False
        self.handler.message = "Resource not found"
        self.handler.error_code = 404
        self.addCleanup(setattr, self.handler, "message", "Not a premium account")
        download = self.service.add(self.page_url)

        self.assertFalse(self.service.run(download.id))

        self.assertIn("Resource not found", download.error)
        self.assertIn("404", download.error)

    def test_every_attempt_asks_for_a_fresh_link(self):
        """Les liens rendus sont à usage unique : réutiliser celui de la tentative
        précédente échouerait à la reprise."""
        download = self.service.add(self.page_url)

        self.service.run(download.id)
        self.service.run(download.id)

        self.assertEqual(len(self.handler.calls), 2)


class TestApplicationIdentity(unittest.TestCase):
    """Icône de l'application.

    `--icon` de PyInstaller ne grave l'image que dans l'exécutable, pour
    l'explorateur : la barre des tâches affiche l'icône de la fenêtre Qt, qui doit
    donc être posée dans le code et livrée avec le paquet.
    """

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def test_the_icon_ships_with_the_sources(self):
        from core.config import ICON_FILE

        self.assertTrue(ICON_FILE.is_file(), f"{ICON_FILE} manquant")

    def test_the_icon_is_square_and_multi_size(self):
        """Une icône non carrée est écrasée par Windows, et une taille unique est
        rééchantillonnée salement dans la barre des tâches."""
        from PySide6.QtGui import QIcon

        from core.config import ICON_FILE

        sizes = QIcon(str(ICON_FILE)).availableSizes()

        self.assertGreaterEqual(len(sizes), 5, f"trop peu de tailles : {sizes}")
        for size in sizes:
            self.assertEqual(size.width(), size.height(), f"{size} n'est pas carrée")

    def test_the_main_window_carries_the_icon(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        from ui.main_window import MainWindow

        window = MainWindow()
        self.addCleanup(window.close)

        self.assertFalse(window.windowIcon().isNull())


class TestDownloadsNavigation(unittest.TestCase):
    """L'écran Téléchargements dans la fenêtre principale.

    Les constantes VIEW_* doivent suivre l'ordre d'ajout au QStackedWidget : une
    inversion afficherait silencieusement la mauvaise vue.
    """

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        from ui.main_window import MainWindow

        self.win = MainWindow()
        self.addCleanup(self.win.close)

    def test_navigating_shows_the_downloads_view(self):
        from ui.main_window import VIEW_DOWNLOADS

        self.win._navigate(VIEW_DOWNLOADS)

        self.assertIs(self.win._stack.currentWidget(), self.win._downloads_view)

    def test_the_sidebar_offers_the_screen(self):
        from ui.main_window import VIEW_DOWNLOADS

        targets = [view_index for _, view_index in self.win._nav_buttons]

        self.assertIn(VIEW_DOWNLOADS, targets)

    def test_progress_carries_the_size_of_a_real_film(self):
        """Signal(int) est un int C++ 32 bits : au-delà de 2,1 Gio chaque émission
        levait OverflowError et la progression ne s'affichait plus jamais."""
        from ui.views.downloads_view import _QueueWorker

        worker = _QueueWorker()
        seen = []
        worker.progress.connect(lambda *args: seen.append(args))

        worker.progress.emit(1, 3_000_000_000, 8_000_000_000)

        self.assertEqual(seen, [(1, 3_000_000_000, 8_000_000_000)])

    def test_closing_the_window_stops_the_queue(self):
        self.win.close()

        self.assertFalse(self.win._downloads_view.is_busy())


def _stop_after(chunks: int):
    """Interrompt un transfert après un nombre de blocs donné."""
    seen = []

    def should_stop() -> bool:
        seen.append(1)
        return len(seen) > chunks

    return should_stop


class TestPlaybackLanguagePreferences(unittest.TestCase):
    """Pistes audio et sous-titres choisis à l'ouverture (Paramètres → Lecture).

    Les options sont posées sur le média et non sur `vlc.Instance()` : l'instance
    libVLC est unique pour tout le processus, un argument d'instance n'aurait donc
    été pris en compte qu'au redémarrage suivant.
    """

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from pathlib import Path

        import core.config

        # settings.json porte la clé TMDb de l'utilisateur : on écrit ailleurs.
        directory = tempfile.mkdtemp(prefix="epikodi_settings_")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.addCleanup(
            setattr, core.config, "SETTINGS_FILE", core.config.SETTINGS_FILE
        )
        core.config.SETTINGS_FILE = Path(directory) / "settings.json"

        self.media_path = os.path.join(directory, "Clip.2024.mkv")
        with open(self.media_path, "wb") as f:
            f.write(b"\0" * 2048)

    def _player(self):
        from ui.views.player_view import PlayerView

        player = PlayerView()
        self.addCleanup(player.shutdown)
        return player

    def _spy_on_media_options(self, player) -> list:
        """Collecte les options posées sur les médias créés par le lecteur."""
        options = []
        instance = player.video_widget.instance
        real_media_new = instance.media_new

        def media_new(mrl, *args):
            media = real_media_new(mrl, *args)
            real_add_option = media.add_option

            def add_option(option):
                options.append(option)
                return real_add_option(option)

            media.add_option = add_option
            return media

        instance.media_new = media_new
        self.addCleanup(delattr, instance, "media_new")
        return options

    def _write_subtitle(self, suffix: str) -> str:
        """Pose un fichier de sous-titres à côté du média, « .fr.srt » par exemple."""
        path = self.media_path.replace(".mkv", suffix)
        with open(path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nbonjour\n")
        return path

    def _autoloaded_subtitle(self, player, paths=None):
        """Sous-titre externe que le lecteur charge de lui-même.

        Le chargement est différé de 800 ms — VLC rejette un sous-titre tant que le
        média n'est pas ouvert — d'où la boucle d'attente.
        """
        loaded = []
        player._load_subtitle = loaded.append
        player._subtitle_paths = (
            paths if paths is not None else player._detect_subtitles(self.media_path)
        )
        player._autoload_subtitle()

        deadline = time.monotonic() + 3
        while not loaded and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        return loaded[0] if loaded else None

    def test_no_preference_by_default(self):
        from core.config import get_audio_language, get_subtitle_language

        self.assertEqual(get_audio_language(), "")
        self.assertEqual(get_subtitle_language(), "")

    def test_the_settings_survive_a_write_and_a_read(self):
        from core.config import get_audio_language, get_subtitle_language, set_setting

        set_setting("audio_language", "fre,fra,fr,french")
        set_setting("subtitle_language", "eng,en,english")

        self.assertEqual(get_audio_language(), "fre,fra,fr,french")
        self.assertEqual(get_subtitle_language(), "eng,en,english")

    def test_the_chosen_languages_reach_vlc(self):
        from core.config import set_setting

        set_setting("audio_language", "eng,en,english")
        set_setting("subtitle_language", "fre,fra,fr,french")
        player = self._player()
        options = self._spy_on_media_options(player)

        player.play_file(self.media_path)
        self.addCleanup(player.stop)

        self.assertIn(":audio-language=eng,en,english", options)
        self.assertIn(":sub-language=fre,fra,fr,french", options)

    def test_only_the_configured_language_is_passed(self):
        """Une préférence vide ne doit pas devenir une option : VLC l'appliquerait."""
        from core.config import set_setting

        set_setting("subtitle_language", "eng,en,english")
        player = self._player()
        options = self._spy_on_media_options(player)

        player.play_file(self.media_path)
        self.addCleanup(player.stop)

        self.assertEqual(options, [":sub-language=eng,en,english"])

    def test_without_preference_the_file_order_is_left_alone(self):
        player = self._player()
        options = self._spy_on_media_options(player)

        player.play_file(self.media_path)
        self.addCleanup(player.stop)

        self.assertEqual(options, [])

    def test_a_subtitle_file_in_the_chosen_language_wins(self):
        from core.config import set_setting

        self._write_subtitle(".en.srt")
        expected = self._write_subtitle(".fr.srt")
        set_setting("subtitle_language", "fre,fra,fr,french")

        self.assertEqual(self._autoloaded_subtitle(self._player()), expected)

    def test_without_a_match_the_first_subtitle_file_is_kept(self):
        from core.config import set_setting

        first = self._write_subtitle(".en.srt")
        self._write_subtitle(".it.srt")
        set_setting("subtitle_language", "ger,deu,de,german")

        self.assertEqual(self._autoloaded_subtitle(self._player()), first)

    def test_a_language_suffix_has_to_be_a_whole_segment(self):
        """Sinon le « fr » de la préférence se reconnaîtrait dans « Frozen.srt »."""
        from core.config import set_setting

        set_setting("subtitle_language", "fre,fra,fr,french")
        paths = ["/films/Frozen.srt", "/films/Frozen.fr.srt"]

        self.assertEqual(
            self._autoloaded_subtitle(self._player(), paths), "/films/Frozen.fr.srt"
        )

    def test_three_letter_subtitle_files_are_detected(self):
        """« Film.eng.srt » est aussi courant que « Film.en.srt », et était ignoré."""
        expected = self._write_subtitle(".eng.srt")

        self.assertIn(expected, self._player()._detect_subtitles(self.media_path))

    def test_the_settings_screen_saves_the_choices(self):
        from core.config import get_audio_language, get_subtitle_language
        from ui.views.settings_view import SettingsView

        view = SettingsView()
        self.addCleanup(view.deleteLater)

        for combo, codes in (
            (view._audio_lang_combo, "eng,en,english"),
            (view._sub_lang_combo, "fre,fra,fr,french"),
        ):
            index = combo.findData(codes)
            self.assertGreaterEqual(index, 0)
            combo.setCurrentIndex(index)

        self.assertEqual(get_audio_language(), "eng,en,english")
        self.assertEqual(get_subtitle_language(), "fre,fra,fr,french")

    def test_the_settings_screen_shows_the_saved_choices(self):
        from core.config import set_setting
        from ui.views.settings_view import SettingsView

        set_setting("audio_language", "jpn,ja,japanese")
        set_setting("subtitle_language", "ita,it,italian")

        view = SettingsView()
        self.addCleanup(view.deleteLater)
        view.refresh(None)

        self.assertEqual(view._audio_lang_combo.currentData(), "jpn,ja,japanese")
        self.assertEqual(view._sub_lang_combo.currentData(), "ita,it,italian")

    def test_reopening_the_settings_screen_does_not_rewrite_the_choices(self):
        """Positionner un combo émet currentIndexChanged : sans blocage, chaque
        passage dans les Paramètres réécrivait les réglages qu'il venait de lire."""
        import core.config
        from ui.views.settings_view import SettingsView

        core.config.set_setting("audio_language", "ita,it,italian")
        core.config.set_setting("subtitle_language", "eng,en,english")

        writes = []
        self.addCleanup(setattr, core.config, "set_setting", core.config.set_setting)

        def spy(key, value):
            writes.append((key, value))
            return True

        core.config.set_setting = spy

        view = SettingsView()
        self.addCleanup(view.deleteLater)
        view.refresh(None)

        self.assertEqual(writes, [])


class TestEpisodeSkipping(unittest.TestCase):
    """Passer à l'épisode suivant / précédent depuis le lecteur."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.media_dir = tempfile.mkdtemp(prefix="epikodi_skip_")
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)

        db = SessionLocal()
        # Saison 1 : 3 épisodes ; saison 2 : 2 épisodes ; plus un film.
        for season, count in ((1, 3), (2, 2)):
            for number in range(1, count + 1):
                db.add(Media(
                    file_path=self._file(f"Show.S{season:02d}E{number:02d}.mkv"),
                    title="Show", media_type="episode", series_name="Show",
                    season_number=season, episode_number=number,
                    episode_title=f"Titre {season}x{number}", duration_sec=1200,
                ))
        db.add(Media(file_path=self._file("Film.mkv"), title="Film",
                     media_type="movie", duration_sec=6000))
        db.commit()
        db.close()

        from ui.main_window import MainWindow

        self.win = MainWindow()
        self.win.show()
        self.addCleanup(self.win.close)
        self.player = self.win._player_view

        from core.services.media_service import MediaService

        self.svc = MediaService()
        self.addCleanup(self.svc.close)
        self.episodes = self.svc.get_series_episodes("Show")
        self.film = next(m for m in self.svc.get_movies() if m.title == "Film")

    def _file(self, name):
        path = os.path.join(self.media_dir, name)
        with open(path, "wb") as f:
            f.write(b"\0" * 2048)
        return path

    def _play(self, media):
        self.win._on_media_play(media.id)
        self.app.processEvents()

    def _code(self):
        media = self.svc.get_media_by_id(self.player.current_media_id())
        return media.episode_code if media else None

    def test_skip_forward_through_the_season(self):
        self._play(self.episodes[0])
        self.assertEqual(self._code(), "S01E01")

        self.player._btn_next_ep.click()
        self.app.processEvents()
        self.assertEqual(self._code(), "S01E02")

    def test_skip_crosses_into_the_next_season(self):
        self._play(self.episodes[2])  # S01E03, dernier de la saison 1
        self.player._btn_next_ep.click()
        self.app.processEvents()

        self.assertEqual(self._code(), "S02E01")

    def test_skip_backwards(self):
        self._play(self.episodes[3])  # S02E01
        self.player._btn_prev_ep.click()
        self.app.processEvents()

        self.assertEqual(self._code(), "S01E03")

    def test_buttons_reflect_the_position_in_the_series(self):
        self._play(self.episodes[0])
        self.assertFalse(self.player._btn_prev_ep.isEnabled(), "1er épisode")
        self.assertTrue(self.player._btn_next_ep.isEnabled())

        self._play(self.episodes[-1])
        self.assertTrue(self.player._btn_prev_ep.isEnabled())
        self.assertFalse(self.player._btn_next_ep.isEnabled(), "dernier épisode")

    def test_a_movie_has_no_episode_controls(self):
        self._play(self.film)
        self.assertFalse(self.player._btn_next_ep.isVisible())
        self.assertFalse(self.player._btn_prev_ep.isVisible())

    def test_keyboard_shortcuts(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        self._play(self.episodes[1])  # S01E02

        self.player.keyPressEvent(
            QKeyEvent(QKeyEvent.KeyPress, Qt.Key_N, Qt.NoModifier)
        )
        self.app.processEvents()
        self.assertEqual(self._code(), "S01E03")

        self.player.keyPressEvent(
            QKeyEvent(QKeyEvent.KeyPress, Qt.Key_P, Qt.NoModifier)
        )
        self.app.processEvents()
        self.assertEqual(self._code(), "S01E02")

    def test_position_is_saved_before_switching(self):
        """Le timer ne sauvegarde que toutes les 10 s : changer d'épisode juste
        après une reprise ne doit pas perdre la position."""
        first = self.episodes[0]
        self.svc.update_progress(first.id, 300_000, 1_200_000)
        self._play(first)

        self.player._current_media_id = first.id  # aucune décodage réel ici
        self.player._btn_next_ep.click()
        self.app.processEvents()

        self.assertGreater(self.svc.get_media_by_id(first.id).resume_position, 0)

    def test_finishing_an_episode_chains_to_the_next(self):
        self._play(self.episodes[0])
        self.win._on_playback_finished()
        self.app.processEvents()

        self.assertEqual(self._code(), "S01E02")


class TestArtwork(unittest.TestCase):
    """Chargement asynchrone des visuels et image de repli."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def _write_image(self, width, height, color="#3366cc"):
        from PySide6.QtGui import QColor, QPixmap

        directory = tempfile.mkdtemp(prefix="epikodi_art_")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, "image.png")
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor(color))
        pixmap.save(path, "PNG")
        return path

    def _drain(self):
        from ui.widgets.artwork import wait_for_pending

        wait_for_pending()
        for _ in range(20):
            self.app.processEvents()

    def test_load_async_delivers_the_pixmap(self):
        """Le QRunnable est détruit dès la fin de run() : si le signal part avec lui,
        l'image n'arrive jamais et les grilles restent sur leur placeholder."""
        from ui.widgets.artwork import load_async

        path = self._write_image(200, 300)
        received = []
        load_async(path, 100, 150, received.append)
        self._drain()

        self.assertEqual(len(received), 1, "aucune image livrée")
        self.assertEqual(received[0].width(), 100)
        self.assertEqual(received[0].height(), 150)

    def test_load_async_ignores_a_missing_file(self):
        from ui.widgets.artwork import load_async

        received = []
        load_async("/nowhere/nope.jpg", 50, 50, received.append)
        self._drain()

        self.assertEqual(received, [])

    def test_poster_card_shows_the_real_artwork(self):
        from ui.widgets.poster_card import CARD_WIDTH, POSTER_HEIGHT, PosterCard

        path = self._write_image(500, 750, "#11aa55")
        card = PosterCard(media_id=1, title="Un film", poster_path=path)
        before = card.poster_label.pixmap().toImage().pixelColor(
            CARD_WIDTH // 2, POSTER_HEIGHT // 2
        )
        self._drain()
        after = card.poster_label.pixmap().toImage().pixelColor(
            CARD_WIDTH // 2, POSTER_HEIGHT // 2
        )

        self.assertNotEqual(before.name(), after.name(), "l'affiche n'a pas remplacé le repli")
        self.assertEqual(after.name(), "#11aa55")

    def test_placeholder_colour_is_stable_across_runs(self):
        """hash() est randomisé à chaque démarrage : la bibliothèque changeait de
        couleurs à chaque lancement."""
        import zlib

        from PySide6.QtGui import QColor

        from ui.widgets.artwork import gradient_placeholder

        seed = "Inception"
        first = gradient_placeholder(60, 90, seed=seed)
        second = gradient_placeholder(60, 90, seed=seed)
        self.assertEqual(
            first.toImage().pixelColor(0, 0).name(),
            second.toImage().pixelColor(0, 0).name(),
        )

        expected = QColor.fromHsv(zlib.crc32(seed.encode("utf-8")) % 360, 120, 70)
        self.assertEqual(first.toImage().pixelColor(0, 0).name(), expected.name())

    def test_placeholders_differ_between_titles(self):
        from ui.widgets.artwork import gradient_placeholder

        colours = {
            gradient_placeholder(40, 60, seed=name).toImage().pixelColor(0, 0).name()
            for name in ["Inception", "Matrix", "Dune", "Arrival"]
        }
        self.assertGreater(len(colours), 1)


class TestEpisodeCard(unittest.TestCase):
    """Carte d'épisode : vignette dédiée, avancement, état vu."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _episode(**overrides):
        fields = dict(
            id=1,
            file_path="/s/show.s01e04.mkv",
            title="Show",
            media_type="episode",
            series_name="Show",
            season_number=1,
            episode_number=4,
            episode_title="Un titre d'épisode",
            overview="Un résumé plutôt long qui doit être tronqué proprement " * 3,
            duration_sec=2700,
        )
        fields.update(overrides)
        return Media(**fields)

    def test_card_uses_the_episode_code_and_title(self):
        from ui.widgets.episode_card import EpisodeCard

        card = EpisodeCard(self._episode())
        self.assertIn("S01E04", card._title_label.text())
        self.assertIn("Un titre d'épisode", card._title_label.text())

    def test_overview_is_shortened_but_kept_in_the_tooltip(self):
        from ui.widgets.episode_card import EpisodeCard

        episode = self._episode()
        card = EpisodeCard(episode)
        self.assertLess(len(card._overview_label.text()), len(episode.overview))
        self.assertTrue(card._overview_label.text().endswith("…"))
        # L'infobulle porte le résumé complet (à l'espacement de bord près).
        self.assertEqual(card._overview_label.toolTip(), episode.overview.strip())

    def test_progress_and_watched_states(self):
        from ui.widgets.episode_card import EpisodeCard

        watched = EpisodeCard(self._episode(is_watched=True))
        self.assertIn("Vu", watched._meta_label.text())

        started = EpisodeCard(
            self._episode(resume_position=1_350_000, is_watched=False)
        )
        self.assertIn("50 %", started._meta_label.text())
        self.assertAlmostEqual(started._progress, 0.5, places=2)

        fresh = EpisodeCard(self._episode())
        self.assertEqual(fresh._progress, 0.0)
        self.assertNotIn("Vu", fresh._meta_label.text())

    def test_click_emits_the_media_id(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QMouseEvent

        from ui.widgets.episode_card import EpisodeCard

        card = EpisodeCard(self._episode(id=42))
        seen = []
        card.clicked.connect(seen.append)

        event = QMouseEvent(
            QMouseEvent.MouseButtonRelease,
            QPoint(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        card.mouseReleaseEvent(event)
        self.assertEqual(seen, [42])


class TestHomeRowCards(unittest.TestCase):
    """Les rangées de l'Accueil doivent montrer la vignette propre à l'épisode.

    Avec une PosterCard, tous les épisodes d'une série affichaient la même affiche.
    """

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _episode(number, **overrides):
        fields = dict(
            id=number,
            file_path=f"/s/show.s02e{number:02d}.mkv",
            title="Rick et Morty",
            media_type="episode",
            series_name="Rick et Morty",
            season_number=2,
            episode_number=number,
            episode_title=f"Épisode {number}",
            still_path=f"/still_{number}.jpg",
            poster_path="/series.jpg",
            duration_sec=1320,
        )
        fields.update(overrides)
        return Media(**fields)

    def test_episodes_get_an_episode_card(self):
        from ui.widgets.episode_card import EpisodeCard
        from ui.widgets.media_grid import HorizontalMediaRow

        row = HorizontalMediaRow("Récemment ajoutés")
        row.set_media_list([self._episode(1), self._episode(2)])

        self.assertEqual(len(row._cards), 2)
        self.assertTrue(all(isinstance(c, EpisodeCard) for c in row._cards))

    def test_movies_keep_a_poster_card(self):
        from ui.widgets.media_grid import HorizontalMediaRow
        from ui.widgets.poster_card import PosterCard

        row = HorizontalMediaRow("Films")
        row.set_media_list(
            [Media(id=9, file_path="/m/a.mkv", title="Un film", media_type="movie")]
        )

        self.assertEqual(len(row._cards), 1)
        self.assertIsInstance(row._cards[0], PosterCard)

    def test_a_mixed_row_keeps_both_kinds(self):
        from ui.widgets.episode_card import EpisodeCard
        from ui.widgets.media_grid import HorizontalMediaRow
        from ui.widgets.poster_card import PosterCard

        row = HorizontalMediaRow("Récemment ajoutés")
        row.set_media_list([
            self._episode(1),
            Media(id=9, file_path="/m/a.mkv", title="Un film", media_type="movie"),
        ])

        self.assertIsInstance(row._cards[0], EpisodeCard)
        self.assertIsInstance(row._cards[1], PosterCard)

    def test_the_row_is_tall_enough_for_both_card_kinds(self):
        from ui.widgets.episode_card import CARD_HEIGHT as EPISODE_H
        from ui.widgets.media_grid import HorizontalMediaRow
        from ui.widgets.poster_card import CARD_HEIGHT as POSTER_H

        row = HorizontalMediaRow("Films")
        self.assertGreaterEqual(row._scroll.height(), max(EPISODE_H, POSTER_H))

    def test_the_card_names_its_series(self):
        """Une rangée de l'Accueil mélange les séries : le nom est indispensable."""
        from ui.widgets.media_grid import HorizontalMediaRow

        row = HorizontalMediaRow("Récemment ajoutés")
        row.set_media_list([self._episode(1)])

        card = row._cards[0]
        self.assertIn("S02E01", card._title_label.text())
        self.assertIn("Rick et Morty", card._meta_label.text())

    def test_clicking_an_episode_starts_playback(self):
        from ui.widgets.media_grid import HorizontalMediaRow

        row = HorizontalMediaRow("Récemment ajoutés")
        row.set_media_list([self._episode(4)])

        played = []
        row.card_play.connect(played.append)
        row._cards[0].clicked.emit(4)

        self.assertEqual(played, [4])

    def test_watched_toggle_reaches_the_row(self):
        from ui.widgets.media_grid import HorizontalMediaRow

        row = HorizontalMediaRow("Récemment ajoutés")
        row.set_media_list([self._episode(5)])

        seen = []
        row.card_watched_toggled.connect(lambda mid, w: seen.append((mid, w)))
        row._cards[0].watched_toggled.emit(5, True)

        self.assertEqual(seen, [(5, True)])


class TestFlowLayout(unittest.TestCase):
    """La grille calculait une hauteur nulle tant que la fenêtre n'était pas
    affichée, car _do_layout ignorait les widgets non encore visibles."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {e}") from e
        cls.app = QApplication.instance() or QApplication([])

    def test_lays_out_widgets_before_first_show(self):
        from PySide6.QtWidgets import QWidget

        from ui.widgets.flow_layout import FlowLayout
        from ui.widgets.poster_card import CARD_HEIGHT, PosterCard

        host = QWidget()
        layout = FlowLayout(host, margin=16, h_spacing=14, v_spacing=16)
        for i in range(6):
            layout.addWidget(PosterCard(media_id=i, title=f"Card {i}"))

        self.assertGreaterEqual(layout.heightForWidth(800), CARD_HEIGHT)


if __name__ == "__main__":
    print("=" * 60)
    print("EpiKodi - Running Tests")
    print("=" * 60)
    unittest.main(verbosity=2)
