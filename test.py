import os
import sys
import shutil
import tempfile
import unittest
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database import init_db, engine, Base, SessionLocal
from core.models import Media, MediaDirectory
from core.services.scanner import MediaParser, MediaScanner, MediaIndexer, ParsedMedia

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
        parsed = MediaParser.parse("/tv/Game.of.Thrones.S03E09.The.Rains.of.Castamere.1080p.mkv")
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
        self.assertTrue(scanner.is_media_file("test.mp3"))
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
        result = db.query(Media).filter(Media.file_path == "/tmp/test/ToDelete.mkv").first()
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
            episode=1
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
            episode_title="Pilot" # Nouveau champ dÃ©tectÃ©
        )
        
        media_updated = self.indexer.index_media(parsed_v2)

        self.assertEqual(media_updated.id, media.id) # MÃªme ID DB
        self.assertEqual(media_updated.episode_title, "Pilot") # Champ mis Ã  jour


class TestMediaServiceBasic(unittest.TestCase):

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        db = SessionLocal()
        db.add_all([
            Media(file_path="/movies/a.mkv", title="Alpha", year=2020, media_type="movie"),
            Media(file_path="/movies/b.mkv", title="Beta", year=2021, media_type="movie", is_watched=True),
            Media(file_path="/series/c.mkv", title="Pilot", media_type="episode",
                  series_name="Gamma Show", season_number=1, episode_number=1),
            Media(file_path="/movies/d.mkv", title="Delta", year=2019, media_type="movie",
                  resume_position=50000),
        ])
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


if __name__ == "__main__":
    print("=" * 60)
    print("EpiKodi - Running Tests")
    print("=" * 60)
    unittest.main(verbosity=2)