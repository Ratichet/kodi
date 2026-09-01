import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ui.widgets.media_grid import HorizontalMediaRow

logger = logging.getLogger(__name__)


class HomeView(QScrollArea):
    media_clicked = Signal(int)
    media_play = Signal(int)
    watched_toggled = Signal(int, bool)
    navigate_to = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)

        self._container = QWidget()
        self._container.setObjectName("content_area")
        self._main_layout = QVBoxLayout(self._container)
        self._main_layout.setContentsMargins(0, 16, 0, 16)
        self._main_layout.setSpacing(4)

        header = QLabel("  Bienvenue sur EpiKodi")
        header.setObjectName("page_title")
        self._main_layout.addWidget(header)

        self._continue_row = self._add_row("▶  Continuer la lecture")
        self._recent_row = self._add_row("🕐  Récemment ajoutés")
        self._movies_row = self._add_row("🎬  Films")
        self._series_row = self._add_row("📺  Épisodes")

        self._main_layout.addStretch()
        self.setWidget(self._container)

    def _add_row(self, title: str) -> HorizontalMediaRow:
        row = HorizontalMediaRow(title)
        row.card_clicked.connect(self.media_clicked.emit)
        row.card_play.connect(self.media_play.emit)
        row.card_watched_toggled.connect(self.watched_toggled.emit)
        self._main_layout.addWidget(row)
        return row

    def refresh(self, media_service):
        try:
            in_progress = media_service.get_in_progress(limit=15)
            self._continue_row.set_media_list(in_progress)
            self._continue_row.setVisible(len(in_progress) > 0)
            recent = media_service.get_recently_added(limit=15)
            self._recent_row.set_media_list(recent)
            movies = media_service.get_movies(limit=15)
            self._movies_row.set_media_list(movies)
            episodes = media_service.get_episodes(limit=15)
            self._series_row.set_media_list(episodes)
            self._series_row.setVisible(len(episodes) > 0)

            logger.info(
                f"Home refreshed: {len(in_progress)} in progress, "
                f"{len(recent)} recent, {len(movies)} movies, "
                f"{len(episodes)} episodes"
            )
        except Exception as e:
            logger.error(f"Failed to refresh home view: {e}")
