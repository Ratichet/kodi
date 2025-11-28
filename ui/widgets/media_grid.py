import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QFrame
)
from PySide6.QtCore import Qt, Signal

from ui.widgets.poster_card import PosterCard, CARD_WIDTH, CARD_HEIGHT
from ui.widgets.flow_layout import FlowLayout

logger = logging.getLogger(__name__)


def _get_local_poster(media) -> str:
    if not media.poster_path:
        return None
    
    from core.config import BASE_DIR
    cache_dir = BASE_DIR / "cache" / "posters"
    local_path = cache_dir / f"w500{media.poster_path.replace('/', '_')}"
    
    if local_path.exists():
        return str(local_path)
    return None


def _make_subtitle(media) -> str:
    parts = []
    if media.media_type == "episode" and media.series_name:
        if media.season_number and media.episode_number:
            parts.append(f"S{media.season_number:02d}E{media.episode_number:02d}")
    if media.year:
        parts.append(str(media.year))
    if media.genres:
        first_genre = media.genres.split(",")[0].strip()
        if first_genre:
            parts.append(first_genre)
    return " · ".join(parts) if parts else ""


def _resume_pct(media) -> float:
    if media.resume_position and media.duration_sec and media.duration_sec > 0:
        return media.resume_position / (media.duration_sec * 1000)
    return 0.0


class MediaGrid(QScrollArea):

    card_clicked = Signal(int)
    card_play = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)
        
        self._container = QWidget()
        self._container.setObjectName("grid_container")
        self._layout = FlowLayout(self._container, margin=16, h_spacing=14, v_spacing=16)
        self.setWidget(self._container)
        
        self._cards = []
    
    def set_media_list(self, media_list):
        self._clear()
        
        for media in media_list:
            card = PosterCard(
                media_id=media.id,
                title=media.display_title if hasattr(media, 'display_title') else (media.title or "Unknown"),
                subtitle=_make_subtitle(media),
                poster_path=_get_local_poster(media),
                is_watched=media.is_watched,
                resume_pct=_resume_pct(media),
            )
            card.clicked.connect(self.card_clicked.emit)
            card.play_requested.connect(self.card_play.emit)
            self._layout.addWidget(card)
            self._cards.append(card)
            self._layout.invalidate()
            self._container.adjustSize()
    
    def _clear(self):
        self._layout.clear()
        self._cards.clear()
    
    def get_card_count(self) -> int:
        return len(self._cards)


class HorizontalMediaRow(QWidget):
    
    card_clicked = Signal(int)
    card_play = Signal(int)
    
    def __init__(self, section_title: str, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)

        title_label = QLabel(section_title)
        title_label.setObjectName("section_title")
        layout.addWidget(title_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(CARD_HEIGHT + 20)
        self._scroll.setFrameShape(QFrame.NoFrame)
        
        self._container = QWidget()
        self._h_layout = QHBoxLayout(self._container)
        self._h_layout.setContentsMargins(0, 0, 0, 0)
        self._h_layout.setSpacing(14)
        self._h_layout.setAlignment(Qt.AlignLeft)
        
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)
        
        self._cards = []
    
    def set_media_list(self, media_list):
        self._clear()
        
        if not media_list:
            empty = QLabel("Aucun média")
            empty.setObjectName("empty_state")
            empty.setAlignment(Qt.AlignCenter)
            self._h_layout.addWidget(empty)
            return
        
        for media in media_list:
            display_title = media.title or "Unknown"
            if media.media_type == "episode" and media.series_name:
                ep = ""
                if media.season_number and media.episode_number:
                    ep = f" S{media.season_number:02d}E{media.episode_number:02d}"
                display_title = f"{media.series_name}{ep}"
            
            card = PosterCard(
                media_id=media.id,
                title=display_title,
                subtitle=_make_subtitle(media),
                poster_path=_get_local_poster(media),
                is_watched=media.is_watched,
                resume_pct=_resume_pct(media),
            )
            card.clicked.connect(self.card_clicked.emit)
            card.play_requested.connect(self.card_play.emit)
            self._h_layout.addWidget(card)
            self._cards.append(card)
        self._h_layout.addStretch()
    
    def _clear(self):
        while self._h_layout.count():
            item = self._h_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._cards.clear()
    
    def is_empty(self) -> bool:
        return len(self._cards) == 0