"""
Series View - TV show library grouped by series.
Shows unique series as cards. Click to drill-down into seasons/episodes.
"""

import logging
from collections import defaultdict
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFrame,
    QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QTimer

from ui.widgets.media_grid import HorizontalMediaRow
from ui.widgets.poster_card import PosterCard
from ui.widgets.flow_layout import FlowLayout

logger = logging.getLogger(__name__)


class SeriesView(QWidget):
    """TV series library view with series grid and episode drill-down."""

    media_clicked = Signal(int)
    media_play = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("content_area")
        self._media_service = None
        self._all_episodes = []
        self._series_map = {}  # series_name -> list of Media
        self._current_series = None  # None = show all series, str = show episodes

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(20, 16, 20, 0)
        self._main_layout.setSpacing(12)

        # --- Header ---
        self._header_layout = QHBoxLayout()

        self._back_btn = QPushButton("← Retour")
        self._back_btn.setObjectName("secondary_button")
        self._back_btn.setVisible(False)
        self._back_btn.clicked.connect(self._show_all_series)
        self._header_layout.addWidget(self._back_btn)

        self._title = QLabel("Séries")
        self._title.setObjectName("page_title")
        self._header_layout.addWidget(self._title)

        self._header_layout.addStretch()

        self._count_label = QLabel("0 séries")
        self._count_label.setObjectName("subtitle")
        self._header_layout.addWidget(self._count_label)

        self._main_layout.addLayout(self._header_layout)

        # --- Search ---
        self._search = QLineEdit()
        self._search.setObjectName("search_bar")
        self._search.setPlaceholderText("Rechercher une série...")
        self._search.setMaximumWidth(400)
        self._search.setClearButtonEnabled(True)
        self._main_layout.addWidget(self._search)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a3450;")
        sep.setFixedHeight(1)
        self._main_layout.addWidget(sep)

        # --- Content: Series Grid ---
        self._series_scroll = QScrollArea()
        self._series_scroll.setWidgetResizable(True)
        self._series_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._series_scroll.setFrameShape(QFrame.NoFrame)

        self._series_container = QWidget()
        self._series_flow = FlowLayout(
            self._series_container, margin=0, h_spacing=14, v_spacing=16
        )
        self._series_scroll.setWidget(self._series_container)
        self._main_layout.addWidget(self._series_scroll, stretch=1)

        # --- Content: Episode list (hidden by default) ---
        self._episode_scroll = QScrollArea()
        self._episode_scroll.setWidgetResizable(True)
        self._episode_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._episode_scroll.setFrameShape(QFrame.NoFrame)
        self._episode_scroll.setVisible(False)

        self._episode_container = QWidget()
        self._episode_layout = QVBoxLayout(self._episode_container)
        self._episode_layout.setContentsMargins(0, 0, 0, 0)
        self._episode_layout.setSpacing(4)
        self._episode_scroll.setWidget(self._episode_container)
        self._main_layout.addWidget(self._episode_scroll, stretch=1)

        # --- Empty State ---
        self._empty_label = QLabel(
            "Aucune série trouvée.\n"
            "Ajoutez un dossier contenant des séries TV dans les paramètres."
        )
        self._empty_label.setObjectName("empty_state")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setVisible(False)
        self._main_layout.addWidget(self._empty_label, stretch=1)

        # Search debounce
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_search)
        self._search.textChanged.connect(lambda: self._search_timer.start())

    def refresh(self, media_service):
        """Reload all episodes from the MediaService."""
        self._media_service = media_service
        try:
            self._all_episodes = media_service.get_episodes()
            self._build_series_map()
            self._show_all_series()
            logger.info(
                f"Series view refreshed: {len(self._series_map)} series, "
                f"{len(self._all_episodes)} episodes"
            )
        except Exception as e:
            logger.error(f"Failed to refresh series view: {e}")

    def _build_series_map(self):
        """Group episodes by series name."""
        self._series_map = defaultdict(list)
        for ep in self._all_episodes:
            name = ep.series_name or ep.title or "Unknown"
            self._series_map[name].append(ep)

        # Sort episodes within each series
        for name in self._series_map:
            self._series_map[name].sort(
                key=lambda e: (e.season_number or 0, e.episode_number or 0)
            )

    def _show_all_series(self):
        """Show the series grid (top level)."""
        self._current_series = None
        self._back_btn.setVisible(False)
        self._title.setText("Séries")
        self._search.setPlaceholderText("Rechercher une série...")
        self._search.clear()

        self._episode_scroll.setVisible(False)
        self._series_scroll.setVisible(True)

        self._apply_search()

    def _apply_search(self):
        """Filter and display series or episodes based on search."""
        search = self._search.text().strip().lower()

        if self._current_series:
            self._show_episodes_filtered(search)
        else:
            self._show_series_filtered(search)

    def _show_series_filtered(self, search: str):
        """Display series cards filtered by search."""
        # Clear old cards
        self._series_flow.clear()

        filtered = {}
        for name, episodes in sorted(self._series_map.items()):
            if search and search not in name.lower():
                continue
            filtered[name] = episodes

        if not filtered:
            self._series_scroll.setVisible(False)
            self._empty_label.setVisible(True)
        else:
            self._empty_label.setVisible(False)
            self._series_scroll.setVisible(True)

            for name, episodes in filtered.items():
                # Use the first episode's data for the series card
                rep = episodes[0]
                ep_count = len(episodes)
                watched = sum(1 for e in episodes if e.is_watched)

                card = PosterCard(
                    media_id=rep.id,
                    title=name,
                    subtitle=f"{ep_count} épisode{'s' if ep_count > 1 else ''}"
                    f" · {watched} vu{'s' if watched > 1 else ''}",
                    poster_path=self._get_poster(rep),
                    is_watched=(watched == ep_count and ep_count > 0),
                )
                # Override click to show drill-down instead of media detail
                card.clicked.disconnect()
                card.clicked.connect(lambda mid, n=name: self._drill_into_series(n))
                card.play_requested.disconnect()
                card.play_requested.connect(
                    lambda mid, n=name: self._drill_into_series(n)
                )
                self._series_flow.addWidget(card)

        self._count_label.setText(
            f"{len(filtered)} série{'s' if len(filtered) != 1 else ''}"
        )

    def _drill_into_series(self, series_name: str):
        """Show episodes for a specific series."""
        self._current_series = series_name
        self._back_btn.setVisible(True)
        self._title.setText(series_name)
        self._search.setPlaceholderText("Rechercher un épisode...")
        self._search.clear()

        self._series_scroll.setVisible(False)
        self._episode_scroll.setVisible(True)

        self._show_episodes_filtered("")

    def _show_episodes_filtered(self, search: str):
        """Display episodes for the current series, grouped by season."""
        # Clear old content
        while self._episode_layout.count():
            item = self._episode_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        episodes = self._series_map.get(self._current_series, [])

        # Group by season
        seasons = defaultdict(list)
        for ep in episodes:
            s = ep.season_number or 0
            if search:
                ep_title = (ep.episode_title or ep.title or "").lower()
                if search not in ep_title and search not in str(ep.episode_number):
                    continue
            seasons[s].append(ep)

        if not seasons:
            empty = QLabel("Aucun épisode trouvé.")
            empty.setObjectName("empty_state")
            empty.setAlignment(Qt.AlignCenter)
            self._episode_layout.addWidget(empty)
            self._count_label.setText("0 épisodes")
            return

        total_eps = 0
        for season_num in sorted(seasons.keys()):
            eps = seasons[season_num]
            total_eps += len(eps)

            season_label = (
                f"Saison {season_num}" if season_num > 0 else "Saison inconnue"
            )
            row = HorizontalMediaRow(season_label)
            row.set_media_list(eps)
            row.card_clicked.connect(self.media_clicked.emit)
            row.card_play.connect(self.media_play.emit)
            self._episode_layout.addWidget(row)

        self._episode_layout.addStretch()
        self._count_label.setText(f"{total_eps} épisode{'s' if total_eps != 1 else ''}")

    def _get_poster(self, media) -> str:
        """Get local poster path."""
        if not media.poster_path:
            return None
        from core.config import BASE_DIR

        cache_dir = BASE_DIR / "cache" / "posters"
        local = cache_dir / f"w500{media.poster_path.replace('/', '_')}"
        return str(local) if local.exists() else None
