import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer

from ui.widgets.media_grid import MediaGrid

logger = logging.getLogger(__name__)


class MoviesView(QWidget):
    
    media_clicked = Signal(int)
    media_play = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("content_area")
        self._media_service = None
        self._all_movies = []
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 0)
        layout.setSpacing(12)

        header_layout = QHBoxLayout()
        
        title = QLabel("Films")
        title.setObjectName("page_title")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        self._count_label = QLabel("0 films")
        self._count_label.setObjectName("subtitle")
        header_layout.addWidget(self._count_label)
        
        layout.addLayout(header_layout)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        
        self._search = QLineEdit()
        self._search.setObjectName("search_bar")
        self._search.setPlaceholderText("Rechercher un film...")
        self._search.setMinimumWidth(250)
        self._search.setMaximumWidth(400)
        self._search.setClearButtonEnabled(True)
        filter_layout.addWidget(self._search)
        
        filter_layout.addStretch()

        self._genre_filter = QComboBox()
        self._genre_filter.addItem("Tous les genres", None)
        self._genre_filter.setMinimumWidth(150)
        filter_layout.addWidget(self._genre_filter)
        self._year_filter = QComboBox()
        self._year_filter.addItem("Toutes les années", None)
        self._year_filter.setMinimumWidth(140)
        filter_layout.addWidget(self._year_filter)
        self._watched_filter = QComboBox()
        self._watched_filter.addItem("Tous", None)
        self._watched_filter.addItem("Non vus", "unwatched")
        self._watched_filter.addItem("Vus", "watched")
        self._watched_filter.setMinimumWidth(120)
        filter_layout.addWidget(self._watched_filter)
        layout.addLayout(filter_layout)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a3450;")
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        self._grid = MediaGrid()
        self._grid.card_clicked.connect(self.media_clicked.emit)
        self._grid.card_play.connect(self.media_play.emit)
        layout.addWidget(self._grid, stretch=1)
        self._empty_label = QLabel("Aucun film trouvé.\nAjoutez un dossier dans les paramètres pour scanner vos médias.")
        self._empty_label.setObjectName("empty_state")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label, stretch=1)

        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filters)
        
        self._search.textChanged.connect(lambda: self._search_timer.start())
        self._genre_filter.currentIndexChanged.connect(self._apply_filters)
        self._year_filter.currentIndexChanged.connect(self._apply_filters)
        self._watched_filter.currentIndexChanged.connect(self._apply_filters)
    
    def refresh(self, media_service):
        self._media_service = media_service
        try:
            self._all_movies = media_service.get_movies()
            self._populate_filter_options()
            self._apply_filters()
            logger.info(f"Movies view refreshed: {len(self._all_movies)} movies")
        except Exception as e:
            logger.error(f"Failed to refresh movies view: {e}")
    
    def _populate_filter_options(self):
        genres = set()
        years = set()
        for movie in self._all_movies:
            if movie.genres:
                for g in movie.genres.split(","):
                    g = g.strip()
                    if g:
                        genres.add(g)
            if movie.year:
                years.add(movie.year)
        current_genre = self._genre_filter.currentData()
        self._genre_filter.blockSignals(True)
        self._genre_filter.clear()
        self._genre_filter.addItem("Tous les genres", None)
        for g in sorted(genres):
            self._genre_filter.addItem(g, g)
        if current_genre:
            idx = self._genre_filter.findData(current_genre)
            if idx >= 0:
                self._genre_filter.setCurrentIndex(idx)
        self._genre_filter.blockSignals(False)
        current_year = self._year_filter.currentData()
        self._year_filter.blockSignals(True)
        self._year_filter.clear()
        self._year_filter.addItem("Toutes les années", None)
        for y in sorted(years, reverse=True):
            self._year_filter.addItem(str(y), y)
        if current_year:
            idx = self._year_filter.findData(current_year)
            if idx >= 0:
                self._year_filter.setCurrentIndex(idx)
        self._year_filter.blockSignals(False)
    
    def _apply_filters(self):
        search_text = self._search.text().strip().lower()
        genre = self._genre_filter.currentData()
        year = self._year_filter.currentData()
        watched = self._watched_filter.currentData()
        filtered = []
        for movie in self._all_movies:
            if search_text:
                title = (movie.title or "").lower()
                if search_text not in title:
                    continue
            if genre:
                movie_genres = (movie.genres or "").lower()
                if genre.lower() not in movie_genres:
                    continue
            if year and movie.year != year:
                continue
            if watched == "watched" and not movie.is_watched:
                continue
            if watched == "unwatched" and movie.is_watched:
                continue
            
            filtered.append(movie)
        self._grid.set_media_list(filtered)
        self._count_label.setText(f"{len(filtered)} film{'s' if len(filtered) != 1 else ''}")
        has_items = len(filtered) > 0
        self._grid.setVisible(has_items)
        self._empty_label.setVisible(not has_items)
        if has_items:
            QTimer.singleShot(10, lambda: self._grid._container.adjustSize())