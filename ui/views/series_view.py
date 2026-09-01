"""Vue Séries : grille des séries, puis navigation par saison avec vignettes d'épisodes."""

import logging
from collections import defaultdict

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.services.tmdb_service import local_backdrop, local_poster
from ui.widgets.episode_card import EpisodeCard
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.poster_card import PosterCard

logger = logging.getLogger(__name__)

HEADER_HEIGHT = 260
POSTER_W, POSTER_H = 120, 180


class Series:
    """Agrégat des épisodes d'une même série."""

    def __init__(self, name: str, episodes: list):
        self.name = name
        self.episodes = sorted(
            episodes, key=lambda e: (e.season_number or 0, e.episode_number or 0)
        )
        self.seasons = defaultdict(list)
        for episode in self.episodes:
            self.seasons[episode.season_number or 0].append(episode)

    @property
    def representative(self):
        """Épisode porteur des métadonnées de la série (affiche, genres…)."""
        return next((e for e in self.episodes if e.tmdb_id), self.episodes[0])

    @property
    def episode_count(self) -> int:
        return len(self.episodes)

    @property
    def season_count(self) -> int:
        return len(self.seasons)

    @property
    def watched_count(self) -> int:
        return sum(1 for e in self.episodes if e.is_watched)

    @property
    def progress_ratio(self) -> float:
        if not self.episodes:
            return 0.0
        return self.watched_count / self.episode_count

    def has_actor(self, query: str) -> bool:
        """Le casting est porté par les épisodes : il suffit qu'un seul le connaisse."""
        return any(episode.has_actor(query) for episode in self.episodes)

    def next_to_watch(self):
        """Épisode commencé, sinon premier non vu, sinon rien."""
        started = [e for e in self.episodes if e.progress_ratio > 0]
        if started:
            return max(started, key=lambda e: e.last_played or e.id)
        return next((e for e in self.episodes if not e.is_watched), None)

    def subtitle(self) -> str:
        parts = [f"{self.season_count} saison{'s' if self.season_count > 1 else ''}"]
        parts.append(f"{self.episode_count} ép.")
        return "  ·  ".join(parts)


class SeriesHeader(QWidget):
    """Bandeau de la série : fond d'écran, affiche, métadonnées et synopsis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(HEADER_HEIGHT)
        self._backdrop = None
        self._poster = None
        self._title = ""
        self._meta = ""
        self._overview = ""

    def set_series(self, series: Series):
        media = series.representative
        self._title = series.name

        meta = []
        if media.year:
            meta.append(str(media.year))
        meta.append(f"{series.season_count} saison{'s' if series.season_count > 1 else ''}")
        meta.append(f"{series.episode_count} épisodes")
        if media.rating:
            meta.append(f"★ {media.rating}")
        if media.genres:
            meta.append(media.genres)
        self._meta = "  ·  ".join(meta)

        self._overview = (media.series_overview or "").strip()

        backdrop = local_backdrop(media)
        self._backdrop = QPixmap(backdrop) if backdrop else None

        poster = local_poster(media)
        self._poster = (
            QPixmap(poster).scaled(
                POSTER_W, POSTER_H, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            if poster
            else None
        )
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()

        if self._backdrop and not self._backdrop.isNull():
            scaled = self._backdrop.scaled(
                width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            painter.drawPixmap(
                0,
                0,
                scaled,
                (scaled.width() - width) // 2,
                (scaled.height() - height) // 2,
                width,
                height,
            )
        else:
            base = QLinearGradient(0, 0, width, height)
            base.setColorAt(0, QColor("#1a1a2e"))
            base.setColorAt(1, QColor("#16213e"))
            painter.fillRect(0, 0, width, height, QBrush(base))

        veil = QLinearGradient(0, 0, 0, height)
        veil.setColorAt(0.0, QColor(22, 33, 62, 130))
        veil.setColorAt(0.6, QColor(22, 33, 62, 200))
        veil.setColorAt(1.0, QColor(22, 33, 62, 250))
        painter.fillRect(0, 0, width, height, QBrush(veil))

        text_x = 32
        if self._poster:
            poster_y = (height - POSTER_H) // 2
            painter.fillRect(35, poster_y + 3, POSTER_W, POSTER_H, QColor(0, 0, 0, 110))
            painter.drawPixmap(32, poster_y, self._poster)
            painter.setPen(QColor(255, 255, 255, 45))
            painter.drawRect(32, poster_y, POSTER_W, POSTER_H)
            text_x = 32 + POSTER_W + 24

        text_width = max(width - text_x - 32, 120)
        y = 56

        painter.setPen(QColor("#eaeaea"))
        painter.setFont(QFont("Segoe UI", 22, QFont.Bold))
        painter.drawText(
            QRectF(text_x, y - 28, text_width, 34),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._elided(painter, self._title, text_width),
        )

        if self._meta:
            painter.setPen(QColor("#8892a0"))
            painter.setFont(QFont("Segoe UI", 10))
            # Une longue liste de genres débordait hors du bandeau.
            painter.drawText(text_x, y + 26, self._elided(painter, self._meta, text_width))

        if self._overview:
            painter.setPen(QColor("#c0c8d4"))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(
                text_x,
                y + 46,
                text_width,
                height - y - 60,
                Qt.TextWordWrap | Qt.AlignTop,
                self._overview,
            )

        painter.end()

    @staticmethod
    def _elided(painter: QPainter, text: str, width: int) -> str:
        return painter.fontMetrics().elidedText(text, Qt.ElideRight, int(width))


class SeriesView(QWidget):
    media_clicked = Signal(int)
    media_play = Signal(int)
    watched_toggled = Signal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("content_area")
        self._media_service = None
        self._series: dict[str, Series] = {}
        self._current: Series | None = None
        self._current_season: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── barre supérieure ─────────────────────────────────────────────────
        top = QWidget()
        top.setFixedHeight(58)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(20, 0, 20, 0)
        top_layout.setSpacing(12)

        self._back_btn = QPushButton("←  Toutes les séries")
        self._back_btn.setObjectName("secondary_button")
        self._back_btn.setVisible(False)
        self._back_btn.clicked.connect(self.show_all_series)
        top_layout.addWidget(self._back_btn)

        self._title = QLabel("Séries")
        self._title.setObjectName("page_title")
        top_layout.addWidget(self._title)
        top_layout.addStretch()

        self._search = QLineEdit()
        self._search.setObjectName("search_bar")
        self._search.setPlaceholderText("Rechercher une série ou un acteur…")
        self._search.setFixedWidth(280)
        self._search.setClearButtonEnabled(True)
        top_layout.addWidget(self._search)

        self._count = QLabel("")
        self._count.setObjectName("subtitle")
        top_layout.addWidget(self._count)
        root.addWidget(top)

        # ── niveau 1 : grille des séries ─────────────────────────────────────
        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._grid_scroll.setFrameShape(QFrame.NoFrame)
        grid_container = QWidget()
        self._grid = FlowLayout(grid_container, margin=20, h_spacing=14, v_spacing=16)
        self._grid_scroll.setWidget(grid_container)
        root.addWidget(self._grid_scroll, stretch=1)

        # ── niveau 2 : détail d'une série ────────────────────────────────────
        self._detail = QScrollArea()
        self._detail.setWidgetResizable(True)
        self._detail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._detail.setFrameShape(QFrame.NoFrame)
        self._detail.setVisible(False)

        detail_container = QWidget()
        detail_container.setObjectName("content_area")
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 24)
        detail_layout.setSpacing(0)

        self._header = SeriesHeader()
        detail_layout.addWidget(self._header)

        action_bar = QWidget()
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(32, 14, 32, 6)
        action_layout.setSpacing(10)

        self._resume_btn = QPushButton("▶  Reprendre")
        self._resume_btn.setObjectName("primary_button")
        self._resume_btn.setMinimumWidth(200)
        self._resume_btn.clicked.connect(self._play_next)
        action_layout.addWidget(self._resume_btn)

        self._progress_label = QLabel("")
        self._progress_label.setObjectName("subtitle")
        action_layout.addWidget(self._progress_label)
        action_layout.addStretch()
        detail_layout.addWidget(action_bar)

        # sélecteur de saison
        self._season_bar = QWidget()
        self._season_layout = QHBoxLayout(self._season_bar)
        self._season_layout.setContentsMargins(32, 6, 32, 10)
        self._season_layout.setSpacing(8)
        detail_layout.addWidget(self._season_bar)

        episodes_container = QWidget()
        self._episode_grid = FlowLayout(
            episodes_container, margin=0, h_spacing=16, v_spacing=18
        )
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(32, 0, 32, 0)
        wrapper_layout.addWidget(episodes_container)
        detail_layout.addWidget(wrapper, stretch=1)

        self._detail.setWidget(detail_container)
        root.addWidget(self._detail, stretch=1)

        # ── état vide ────────────────────────────────────────────────────────
        self._empty = QLabel(
            "Aucune série trouvée.\n"
            "Ajoutez un dossier contenant vos séries dans les Paramètres."
        )
        self._empty.setObjectName("empty_state")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setVisible(False)
        root.addWidget(self._empty, stretch=1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._apply_search)
        self._search.textChanged.connect(lambda: self._search_timer.start())

    # ── données ───────────────────────────────────────────────────────────────

    def refresh(self, media_service):
        self._media_service = media_service
        episodes = media_service.get_episodes()

        grouped = defaultdict(list)
        for episode in episodes:
            grouped[episode.series_name or episode.title or "Inconnu"].append(episode)
        self._series = {name: Series(name, eps) for name, eps in grouped.items()}

        if self._current and self._current.name in self._series:
            # On revient sur la même série après une lecture : on garde la saison.
            self._open_series(self._current.name, keep_season=True)
        else:
            self.show_all_series()

        logger.info(
            f"Series view refreshed: {len(self._series)} series, {len(episodes)} episodes"
        )

    # ── niveau 1 ──────────────────────────────────────────────────────────────

    def show_all_series(self):
        self._current = None
        self._current_season = None
        self._back_btn.setVisible(False)
        self._title.setText("Séries")
        self._search.setPlaceholderText("Rechercher une série ou un acteur…")
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._detail.setVisible(False)
        self._render_series_grid("")

    def _render_series_grid(self, query: str):
        self._grid.clear()

        matches = [
            series
            for name, series in sorted(self._series.items())
            if not query or query in name.lower() or series.has_actor(query)
        ]

        has_results = bool(matches)
        self._grid_scroll.setVisible(has_results)
        self._empty.setVisible(not has_results)
        self._empty.setText(
            "Aucune série ne correspond à cette recherche."
            if query and self._series
            else "Aucune série trouvée.\n"
            "Ajoutez un dossier contenant vos séries dans les Paramètres."
        )

        for series in matches:
            media = series.representative
            remaining = series.episode_count - series.watched_count
            card = PosterCard(
                media_id=media.id,
                title=series.name,
                subtitle=series.subtitle(),
                poster_path=local_poster(media),
                is_watched=(remaining == 0),
                resume_pct=series.progress_ratio,
                badge=f"{remaining} à voir" if 0 < remaining < series.episode_count else "",
            )
            card.clicked.connect(lambda _id, n=series.name: self._open_series(n))
            card.play_requested.connect(lambda _id, n=series.name: self._open_series(n))
            self._grid.addWidget(card)

        self._count.setText(f"{len(matches)} série{'s' if len(matches) != 1 else ''}")

    # ── niveau 2 ──────────────────────────────────────────────────────────────

    def _open_series(self, name: str, keep_season: bool = False):
        series = self._series.get(name)
        if not series:
            self.show_all_series()
            return

        self._current = series
        self._back_btn.setVisible(True)
        self._title.setText(name)
        self._search.setPlaceholderText("Rechercher un épisode…")
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)

        self._grid_scroll.setVisible(False)
        self._empty.setVisible(False)
        self._detail.setVisible(True)

        self._header.set_series(series)
        self._update_actions(series)
        self._build_season_bar(series, keep_season)

    def _update_actions(self, series: Series):
        nxt = series.next_to_watch()
        if nxt is None:
            self._resume_btn.setText("▶  Revoir depuis le début")
            self._resume_btn.setEnabled(bool(series.episodes))
        elif nxt.progress_ratio > 0:
            self._resume_btn.setText(f"▶  Reprendre {nxt.episode_code}")
        else:
            self._resume_btn.setText(f"▶  Lire {nxt.episode_code}")

        self._progress_label.setText(
            f"{series.watched_count} / {series.episode_count} épisodes vus"
        )

    def _build_season_bar(self, series: Series, keep_season: bool):
        while self._season_layout.count():
            item = self._season_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        seasons = sorted(series.seasons)
        if keep_season and self._current_season in series.seasons:
            active = self._current_season
        else:
            nxt = series.next_to_watch()
            active = nxt.season_number if nxt and nxt.season_number else seasons[0]
        self._current_season = active

        for season in seasons:
            episodes = series.seasons[season]
            watched = sum(1 for e in episodes if e.is_watched)
            label = f"Saison {season}" if season else "Hors saison"
            button = QPushButton(f"{label}  ({watched}/{len(episodes)})")
            button.setCheckable(True)
            button.setChecked(season == active)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(self._season_button_style())
            # La saison voyage avec le bouton : la surbrillance ne dépend plus de
            # l'ordre des widgets dans le layout.
            button.setProperty("season", season)
            button.clicked.connect(lambda _c=False, s=season: self._select_season(s))
            self._season_layout.addWidget(button)

        self._season_layout.addStretch()
        self._render_episodes("")

    @staticmethod
    def _season_button_style() -> str:
        return """
            QPushButton {
                background-color: #1e2a4a; color: #8892a0;
                border: 1px solid #2a3450; border-radius: 16px;
                padding: 7px 16px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { color: #eaeaea; border-color: #8892a0; }
            QPushButton:checked {
                background-color: #e94560; color: white; border-color: #e94560;
            }
        """

    def _select_season(self, season: int):
        self._current_season = season
        for index in range(self._season_layout.count()):
            widget = self._season_layout.itemAt(index).widget()
            if isinstance(widget, QPushButton):
                widget.setChecked(widget.property("season") == season)
        self._render_episodes(self._search.text().strip().lower())

    def _render_episodes(self, query: str):
        self._episode_grid.clear()
        if not self._current:
            return

        if query:
            # Une recherche d'épisode porte sur toute la série, pas la saison seule.
            episodes = [
                e
                for e in self._current.episodes
                if query in (e.episode_title or "").lower()
                or query in (e.overview or "").lower()
                or query in (e.episode_code or "").lower()
            ]
        else:
            episodes = self._current.seasons.get(self._current_season, [])

        for episode in episodes:
            card = EpisodeCard(episode)
            card.clicked.connect(self.media_play.emit)
            card.details_requested.connect(self.media_clicked.emit)
            card.watched_toggled.connect(self.watched_toggled.emit)
            self._episode_grid.addWidget(card)

        self._count.setText(f"{len(episodes)} épisode{'s' if len(episodes) != 1 else ''}")

    def _play_next(self):
        if not self._current:
            return
        target = self._current.next_to_watch() or self._current.episodes[0]
        self.media_play.emit(target.id)

    # ── recherche ─────────────────────────────────────────────────────────────

    def _apply_search(self):
        query = self._search.text().strip().lower()
        if self._current:
            self._render_episodes(query)
        else:
            self._render_series_grid(query)
