import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QStackedWidget,
    QFrame,
    QFileDialog,
)
from PySide6.QtCore import Qt

from core.services.media_service import MediaService

from ui.styles import get_dark_theme
from ui.views.home_view import HomeView
from ui.views.movies_view import MoviesView
from ui.views.series_view import SeriesView
from ui.views.detail_view import DetailView
from ui.views.player_view import PlayerView
from ui.views.settings_view import SettingsView
from ui.views.music_view import MusicView, AudioPlayerBar
from ui.views.playlist_view import PlaylistView

logger = logging.getLogger(__name__)

VIEW_HOME = 0
VIEW_MOVIES = 1
VIEW_SERIES = 2
VIEW_MUSIC = 3
VIEW_PLAYLISTS = 4  # ← NEW
VIEW_DETAIL = 5
VIEW_PLAYER = 6
VIEW_SETTINGS = 7


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EpiKodi")
        self.resize(1280, 800)
        self.setMinimumSize(960, 580)

        self.setStyleSheet(get_dark_theme())

        self._media_service = MediaService()

        self._mq_tracks: list = [] 
        self._mq_index: int = -1
        self._mq_audio_end: int = -1 

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(4)

        logo = QLabel("⬡ EpiKodi")
        logo.setObjectName("logo_label")
        logo.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(logo)
        sidebar_layout.addSpacing(24)

        self._nav_buttons = []
        nav_items = [
            ("🏠  Accueil", VIEW_HOME),
            ("🎬  Films", VIEW_MOVIES),
            ("📺  Séries", VIEW_SERIES),
            ("🎵  Musique", VIEW_MUSIC),
            ("📋  Playlists", VIEW_PLAYLISTS),  # ← NEW
            ("⚙  Paramètres", VIEW_SETTINGS),
        ]

        for text, view_idx in nav_items:
            btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.clicked.connect(lambda checked=False, idx=view_idx: self._navigate(idx))
            sidebar_layout.addWidget(btn)
            self._nav_buttons.append((btn, view_idx))

        sidebar_layout.addStretch()

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a3450;")
        sidebar_layout.addWidget(sep)
        sidebar_layout.addSpacing(8)

        btn_open = QPushButton("📂  Ouvrir un fichier")
        btn_open.setObjectName("secondary_button")
        btn_open.clicked.connect(self._open_file)
        sidebar_layout.addWidget(btn_open)
        sidebar_layout.addSpacing(4)

        self._stats_label = QLabel("Bibliothèque vide")
        self._stats_label.setObjectName("subtitle")
        self._stats_label.setAlignment(Qt.AlignCenter)
        self._stats_label.setWordWrap(True)
        sidebar_layout.addWidget(self._stats_label)

        main_layout.addWidget(sidebar)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setObjectName("content_area")
        right_layout.addWidget(self._stack, stretch=1)

        self._audio_player = AudioPlayerBar()
        self._audio_player.queue_exhausted.connect(self._on_audio_queue_exhausted)
        right_layout.addWidget(self._audio_player)

        main_layout.addWidget(right_widget, stretch=1)

        self._home_view = HomeView()
        self._home_view.media_clicked.connect(self._on_media_clicked)
        self._home_view.media_play.connect(self._on_media_play)

        self._movies_view = MoviesView()
        self._movies_view.media_clicked.connect(self._on_media_clicked)
        self._movies_view.media_play.connect(self._on_media_play)

        self._series_view = SeriesView()
        self._series_view.media_clicked.connect(self._on_media_clicked)
        self._series_view.media_play.connect(self._on_media_play)

        self._music_view = MusicView()
        self._music_view.set_player_bar(self._audio_player)

        self._playlist_view = PlaylistView()
        self._playlist_view.play_queue.connect(self._on_play_queue)
        self._playlist_view.play_media.connect(self._on_media_play)

        self._detail_view = DetailView()
        self._detail_view.play_requested.connect(self._on_media_play)
        self._detail_view.back_requested.connect(self._on_detail_back)

        self._player_view = PlayerView()
        self._player_view.back_requested.connect(self._on_player_back)
        self._player_view.media_ended.connect(self._on_queue_advance)

        self._settings_view = SettingsView()
        self._settings_view.library_changed.connect(self._refresh_all_views)

        self._stack.addWidget(self._home_view)
        self._stack.addWidget(self._movies_view)
        self._stack.addWidget(self._series_view)
        self._stack.addWidget(self._music_view)
        self._stack.addWidget(self._playlist_view)
        self._stack.addWidget(self._detail_view)
        self._stack.addWidget(self._player_view)
        self._stack.addWidget(self._settings_view)

        self._current_view = VIEW_HOME
        self._previous_view = VIEW_HOME
        self._view_before_detail = VIEW_HOME
        self._navigate(VIEW_HOME)
        self._refresh_all_views()

        logger.info("MainWindow initialized")

    def _navigate(self, view_index: int):
        if view_index in (VIEW_PLAYER, VIEW_DETAIL):
            return

        self._previous_view = self._current_view
        self._current_view = view_index
        self._stack.setCurrentIndex(view_index)
        self._update_nav_highlight(view_index)
        self._audio_player.setVisible(True)
        self._refresh_view(view_index)

    def _update_nav_highlight(self, active_index: int):
        for btn, idx in self._nav_buttons:
            btn.setProperty("active", idx == active_index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _refresh_view(self, view_index: int):
        try:
            if view_index == VIEW_HOME:
                self._home_view.refresh(self._media_service)
            elif view_index == VIEW_MOVIES:
                self._movies_view.refresh(self._media_service)
            elif view_index == VIEW_SERIES:
                self._series_view.refresh(self._media_service)
            elif view_index == VIEW_MUSIC:
                self._music_view.refresh(self._media_service)
            elif view_index == VIEW_PLAYLISTS:
                self._playlist_view.refresh(self._media_service)
            elif view_index == VIEW_SETTINGS:
                self._settings_view.refresh(self._media_service)
        except Exception as e:
            logger.error(f"Failed to refresh view {view_index}: {e}")

    def _refresh_all_views(self):
        self._refresh_view(self._current_view)
        self._update_stats_label()

    def _update_stats_label(self):
        try:
            stats = self._media_service.get_stats()
            total = stats["total_media"]
            if total == 0:
                self._stats_label.setText(
                    "Bibliothèque vide\nAjoutez des dossiers\ndans les paramètres"
                )
            else:
                music_part = f" · {stats['music']} titres" if stats.get("music") else ""
                self._stats_label.setText(
                    f"{stats['movies']} films · {stats['episodes']} épisodes"
                    f"{music_part}\n"
                    f"{stats['watched']} vus · {stats['in_progress']} en cours"
                )
        except Exception:
            self._stats_label.setText("Bibliothèque")

    def _on_play_queue(self, tracks: list):
        if not tracks:
            return
        self._mq_tracks = tracks
        self._mq_index = -1
        self._mq_audio_end = -1
        self._play_mq_from(0)

    def _play_mq_from(self, index: int):
        if index >= len(self._mq_tracks):
            logger.info("Mixed queue: playback complete")
            return

        self._mq_index = index
        item = self._mq_tracks[index]

        if item.media_type == "music":
            # Collect this block of consecutive audio items
            audio_block = []
            i = index
            while i < len(self._mq_tracks) and self._mq_tracks[i].media_type == "music":
                audio_block.append(self._mq_tracks[i])
                i += 1
            self._mq_audio_end = i

            self._audio_player.set_media_service(self._media_service)
            self._audio_player.load_queue(audio_block, start_index=0)
        else:
            self._mq_audio_end = -1
            self._previous_view = self._current_view
            self._current_view = VIEW_PLAYER
            self._audio_player.setVisible(False)
            self._stack.setCurrentIndex(VIEW_PLAYER)
            self._update_nav_highlight(-1)
            self._player_view.play_media(item, self._media_service)

    def _on_queue_advance(self):
        next_idx = self._mq_index + 1
        if next_idx < len(self._mq_tracks):
            self._play_mq_from(next_idx)
        else:
            self._navigate(VIEW_PLAYLISTS)

    def _on_audio_queue_exhausted(self):
        if self._mq_audio_end >= 0 and self._mq_audio_end < len(self._mq_tracks):
            self._play_mq_from(self._mq_audio_end)
        elif self._mq_tracks:
            self._navigate(VIEW_PLAYLISTS)

    def _on_media_clicked(self, media_id: int):
        media = self._media_service.get_media_by_id(media_id)
        if not media:
            return

        if media.media_type == "music":
            self._audio_player.set_media_service(self._media_service)
            self._audio_player.play_single(media)
            return

        self._view_before_detail = self._current_view
        self._previous_view = self._current_view
        self._current_view = VIEW_DETAIL
        self._detail_view.show_media(media, self._media_service)
        self._stack.setCurrentIndex(VIEW_DETAIL)
        self._update_nav_highlight(-1)

    def _on_media_play(self, media_id: int):
        media = self._media_service.get_media_by_id(media_id)
        if not media:
            return

        if media.media_type == "music":
            self._audio_player.set_media_service(self._media_service)
            self._audio_player.play_single(media)
            return

        if self._current_view != VIEW_PLAYER:
            self._previous_view = self._current_view
        self._current_view = VIEW_PLAYER

        subtitle_paths = []
        if hasattr(self._detail_view, "get_subtitle_paths"):
            subtitle_paths = self._detail_view.get_subtitle_paths()

        self._audio_player.setVisible(False)
        self._stack.setCurrentIndex(VIEW_PLAYER)
        self._player_view.play_media(media, self._media_service, subtitle_paths)
        self._update_nav_highlight(-1)

    def _on_detail_back(self):
        target = self._view_before_detail
        self._current_view = target
        self._stack.setCurrentIndex(target)
        self._update_nav_highlight(target)
        self._refresh_view(target)

    def _on_player_back(self):
        self._audio_player.setVisible(True)
        if self._previous_view == VIEW_DETAIL:
            self._current_view = VIEW_DETAIL
            self._stack.setCurrentIndex(VIEW_DETAIL)
            self._update_nav_highlight(-1)
            if self._detail_view._media:
                refreshed = self._media_service.get_media_by_id(
                    self._detail_view._media.id
                )
                if refreshed:
                    self._detail_view.show_media(refreshed, self._media_service)
        else:
            target = (
                self._previous_view
                if self._previous_view not in (VIEW_DETAIL, VIEW_PLAYER)
                else VIEW_HOME
            )
            self._navigate(target)

    def _open_file(self):
        from core.config import SUPPORTED_VIDEO_EXTENSIONS, SUPPORTED_AUDIO_EXTENSIONS

        all_exts = SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS
        ext_filter = "Médias (" + " ".join(f"*{e}" for e in sorted(all_exts)) + ")"
        start_dir = str(Path.home() / "Videos")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un fichier", start_dir, ext_filter
        )
        if not file_path:
            return

        from pathlib import Path as _Path
        from core.config import SUPPORTED_AUDIO_EXTENSIONS

        if _Path(file_path).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
            from core.models import Media as _Media

            fake = _Media(
                file_path=file_path, title=_Path(file_path).stem, media_type="music"
            )
            self._audio_player.set_media_service(self._media_service)
            self._audio_player.play_single(fake)
        else:
            media = self._media_service.get_media_by_path(file_path)
            if not media:
                from core.services.scanner import MediaParser, MediaIndexer

                parsed = MediaParser.parse(file_path)
                if parsed:
                    media = MediaIndexer().index_media(parsed)
            if media:
                self._on_media_play(media.id)

    def closeEvent(self, event):
        try:
            self._audio_player.stop()
        except Exception:
            pass
        try:
            self._media_service.close()
        except Exception:
            pass
        super().closeEvent(event)
