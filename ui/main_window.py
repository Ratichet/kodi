import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QFileDialog
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

logger = logging.getLogger(__name__)

VIEW_HOME = 0
VIEW_MOVIES = 1
VIEW_SERIES = 2
VIEW_DETAIL = 3
VIEW_PLAYER = 4
VIEW_SETTINGS = 5


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EpiKodi")
        self.resize(1200, 750)
        self.setMinimumSize(900, 550)

        self.setStyleSheet(get_dark_theme())

        self._media_service = MediaService()

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

        self._stack = QStackedWidget()
        self._stack.setObjectName("content_area")

        self._home_view = HomeView()
        self._home_view.media_clicked.connect(self._on_media_clicked)
        self._home_view.media_play.connect(self._on_media_play)

        self._movies_view = MoviesView()
        self._movies_view.media_clicked.connect(self._on_media_clicked)
        self._movies_view.media_play.connect(self._on_media_play)

        self._series_view = SeriesView()
        self._series_view.media_clicked.connect(self._on_media_clicked)
        self._series_view.media_play.connect(self._on_media_play)

        self._detail_view = DetailView()
        self._detail_view.play_requested.connect(self._on_media_play)
        self._detail_view.back_requested.connect(self._on_detail_back)

        self._player_view = PlayerView()
        self._player_view.back_requested.connect(self._on_player_back)

        self._settings_view = SettingsView()
        self._settings_view.library_changed.connect(self._refresh_all_views)

        self._stack.addWidget(self._home_view)
        self._stack.addWidget(self._movies_view)
        self._stack.addWidget(self._series_view)
        self._stack.addWidget(self._detail_view)
        self._stack.addWidget(self._player_view)
        self._stack.addWidget(self._settings_view)

        main_layout.addWidget(self._stack, stretch=1)

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
                self._stats_label.setText(
                    f"{stats['movies']} films · {stats['episodes']} épisodes\n"
                    f"{stats['watched']} vus · {stats['in_progress']} en cours"
                )
        except Exception:
            self._stats_label.setText("Bibliothèque")

    def _on_media_clicked(self, media_id: int):
        media = self._media_service.get_media_by_id(media_id)
        if not media:
            logger.warning(f"Media not found: {media_id}")
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
            logger.warning(f"Media not found: {media_id}")
            return
        if self._current_view != VIEW_PLAYER:
            self._previous_view = self._current_view
        self._current_view = VIEW_PLAYER

        subtitle_paths = []
        if hasattr(self._detail_view, 'get_subtitle_paths'):
            subtitle_paths = self._detail_view.get_subtitle_paths()

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
        if self._previous_view == VIEW_DETAIL:
            self._current_view = VIEW_DETAIL
            self._stack.setCurrentIndex(VIEW_DETAIL)
            self._update_nav_highlight(-1)
            if self._detail_view._media:
                refreshed = self._media_service.get_media_by_id(self._detail_view._media.id)
                if refreshed:
                    self._detail_view.show_media(refreshed, self._media_service)
        else:
            target = self._previous_view if self._previous_view not in (VIEW_DETAIL, VIEW_PLAYER) else VIEW_HOME
            self._navigate(target)

    def _open_file(self):
        start_dir = str(Path.home() / "Videos")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un fichier média", start_dir,
            "Médias (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v *.mpg *.mpeg *.ts)"
        )
        if file_path:
            self._previous_view = self._current_view
            self._current_view = VIEW_PLAYER
            self._stack.setCurrentIndex(VIEW_PLAYER)
            self._player_view.play_file(file_path)
            self._update_nav_highlight(-1)

    def closeEvent(self, event):

        try:
            if hasattr(self, '_player_view'):
                self._player_view.stop()
        except Exception as e:
            logger.error(f"Error stopping player logic: {e}")

        try:
            if hasattr(self, '_player_view') and hasattr(self._player_view, 'video_widget'):
                widget = self._player_view.video_widget

                if hasattr(widget, 'player') and widget.player:
                    widget.player.release()
                    widget.player = None

                if hasattr(widget, 'instance') and widget.instance:
                    widget.instance.release()
                    widget.instance = None
                    
        except Exception as e:
            logger.error(f"Error releasing VLC resources: {e}")

        try:
            if hasattr(self, '_media_service'):
                self._media_service.close()
        except Exception:
            pass

        logger.info("EpiKodi closed")
        super().closeEvent(event)