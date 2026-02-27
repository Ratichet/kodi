import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QLinearGradient, QBrush, QFont

logger = logging.getLogger(__name__)


def _resolve_poster(media) -> str | None:
    if not media.poster_path:
        return None
    from core.config import BASE_DIR

    p = BASE_DIR / "cache" / "posters" / f"w500{media.poster_path.replace('/', '_')}"
    return str(p) if p.exists() else None


def _resolve_backdrop(media) -> str | None:
    if not media.backdrop_path:
        return None
    from core.config import BASE_DIR

    p = (
        BASE_DIR
        / "cache"
        / "backdrops"
        / f"w1280{media.backdrop_path.replace('/', '_')}"
    )
    return str(p) if p.exists() else None


def _format_duration(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return ""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m:02d}min"
    return f"{m}min"


def _format_resume(ms: int) -> str:
    if not ms or ms <= 0:
        return ""
    s = (ms // 1000) % 60
    m = (ms // 60000) % 60
    h = ms // 3600000
    return f"{h:02d}:{m:02d}:{s:02d}"


class BackdropHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(340)
        self._backdrop_pixmap = None
        self._poster_pixmap = None
        self._title = ""
        self._year = ""
        self._genres = ""
        self._rating = ""
        self._duration = ""

    def set_data(
        self,
        title: str,
        year: str,
        genres: str,
        rating: str,
        duration: str,
        backdrop_path: str = None,
        poster_path: str = None,
    ):
        self._title = title
        self._year = year
        self._genres = genres
        self._rating = rating
        self._duration = duration

        if backdrop_path and Path(backdrop_path).exists():
            self._backdrop_pixmap = QPixmap(backdrop_path)
        else:
            self._backdrop_pixmap = None

        if poster_path and Path(poster_path).exists():
            self._poster_pixmap = QPixmap(poster_path).scaled(
                130, 195, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        else:
            self._poster_pixmap = None

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if self._backdrop_pixmap:
            scaled = self._backdrop_pixmap.scaled(
                w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            x_off = (scaled.width() - w) // 2
            y_off = (scaled.height() - h) // 2
            painter.drawPixmap(0, 0, scaled, x_off, y_off, w, h)
        else:
            gradient = QLinearGradient(0, 0, w, h)
            gradient.setColorAt(0, QColor("#1a1a2e"))
            gradient.setColorAt(1, QColor("#16213e"))
            painter.fillRect(0, 0, w, h, QBrush(gradient))

        overlay = QLinearGradient(0, 0, 0, h)
        overlay.setColorAt(0.0, QColor(0, 0, 0, 80))
        overlay.setColorAt(0.5, QColor(0, 0, 0, 120))
        overlay.setColorAt(1.0, QColor(22, 33, 62, 240))
        painter.fillRect(0, 0, w, h, QBrush(overlay))

        poster_x = 32
        poster_y = h - 195 - 24
        if self._poster_pixmap:
            painter.fillRect(poster_x + 3, poster_y + 3, 130, 195, QColor(0, 0, 0, 100))
            painter.drawPixmap(poster_x, poster_y, self._poster_pixmap)
            painter.setPen(QColor(255, 255, 255, 40))
            painter.drawRect(poster_x, poster_y, 130, 195)

        text_x = poster_x + 150 if self._poster_pixmap else 32
        text_y_base = h - 100

        painter.setPen(QColor("#eaeaea"))
        title_font = QFont("Segoe UI", 24, QFont.Bold)
        painter.setFont(title_font)
        painter.drawText(text_x, text_y_base, self._title)

        meta_parts = []
        if self._year:
            meta_parts.append(self._year)
        if self._duration:
            meta_parts.append(self._duration)
        if self._rating:
            meta_parts.append(f"★ {self._rating}")
        if self._genres:
            meta_parts.append(self._genres)

        if meta_parts:
            painter.setPen(QColor("#8892a0"))
            meta_font = QFont("Segoe UI", 12)
            painter.setFont(meta_font)
            painter.drawText(text_x, text_y_base + 28, "  ·  ".join(meta_parts))

        painter.end()


class EpisodeRow(QFrame):
    play_clicked = Signal(int)

    def __init__(self, media, parent=None):
        super().__init__(parent)
        self._media_id = media.id
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QFrame {
                background-color: #1e2a4a;
                border-radius: 6px;
                padding: 8px 12px;
            }
            QFrame:hover {
                background-color: #2a3a5c;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # episode number
        ep_num = ""
        if media.season_number and media.episode_number:
            ep_num = f"S{media.season_number:02d}E{media.episode_number:02d}"
        num_label = QLabel(ep_num)
        num_label.setStyleSheet(
            "color: #e94560; font-weight: 700; font-size: 13px; min-width: 65px;"
        )
        layout.addWidget(num_label)

        # title + overview
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        ep_title = media.episode_title or media.title or "Épisode"
        title_label = QLabel(ep_title)
        title_label.setStyleSheet("color: #eaeaea; font-weight: 600; font-size: 13px;")
        info_layout.addWidget(title_label)

        if media.overview:
            overview = (
                media.overview[:120] + "…"
                if len(media.overview) > 120
                else media.overview
            )
            ov_label = QLabel(overview)
            ov_label.setStyleSheet("color: #8892a0; font-size: 11px;")
            ov_label.setWordWrap(True)
            info_layout.addWidget(ov_label)

        layout.addLayout(info_layout, stretch=1)

        # duration
        if media.duration_sec:
            dur = QLabel(_format_duration(media.duration_sec))
            dur.setStyleSheet("color: #556070; font-size: 12px;")
            layout.addWidget(dur)

        # watched indicator
        if media.is_watched:
            watched = QLabel("✓ Vu")
            watched.setStyleSheet("color: #2ed573; font-size: 12px; font-weight: 600;")
            layout.addWidget(watched)
        elif media.resume_position and media.resume_position > 0:
            pos = QLabel(f"▶ {_format_resume(media.resume_position)}")
            pos.setStyleSheet("color: #ffa502; font-size: 12px;")
            layout.addWidget(pos)

        # play button
        btn = QPushButton("▶")
        btn.setObjectName("icon_button")
        btn.setFixedSize(32, 32)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #e94560;
                color: white;
                border-radius: 16px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #ff6b81; }
        """)
        btn.clicked.connect(lambda: self.play_clicked.emit(self._media_id))
        layout.addWidget(btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.play_clicked.emit(self._media_id)
        super().mousePressEvent(event)


class DetailView(QScrollArea):
    play_requested = Signal(int)
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)

        self._media = None
        self._media_service = None
        self._related_episodes = []

        self._container = QWidget()
        self._container.setObjectName("content_area")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 24)
        self._layout.setSpacing(0)

        self._header = BackdropHeader()
        self._layout.addWidget(self._header)

        btn_frame = QWidget()
        btn_frame.setStyleSheet("background-color: #16213e;")
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(32, 16, 32, 16)
        btn_layout.setSpacing(12)

        self._btn_back = QPushButton("← Retour")
        self._btn_back.setObjectName("secondary_button")
        self._btn_back.clicked.connect(self.back_requested.emit)
        btn_layout.addWidget(self._btn_back)

        self._btn_play = QPushButton("▶  Lire")
        self._btn_play.setObjectName("primary_button")
        self._btn_play.setMinimumWidth(160)
        self._btn_play.clicked.connect(self._on_play)
        btn_layout.addWidget(self._btn_play)

        self._btn_watched = QPushButton("Marquer comme vu")
        self._btn_watched.setObjectName("secondary_button")
        self._btn_watched.clicked.connect(self._toggle_watched)
        btn_layout.addWidget(self._btn_watched)

        btn_layout.addStretch()

        self._path_label = QLabel("")
        self._path_label.setStyleSheet("color: #556070; font-size: 11px;")
        self._path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        btn_layout.addWidget(self._path_label)

        self._layout.addWidget(btn_frame)

        body = QWidget()
        body.setStyleSheet("background-color: #16213e;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 0, 32, 24)
        body_layout.setSpacing(20)

        self._synopsis_header = QLabel("Synopsis")
        self._synopsis_header.setObjectName("section_title")
        body_layout.addWidget(self._synopsis_header)

        self._synopsis_label = QLabel("")
        self._synopsis_label.setWordWrap(True)
        self._synopsis_label.setStyleSheet(
            "color: #c0c8d4; font-size: 14px; line-height: 1.5;"
        )
        body_layout.addWidget(self._synopsis_label)

        self._subs_header = QLabel("Sous-titres détectés")
        self._subs_header.setObjectName("section_title")
        self._subs_header.setVisible(False)
        body_layout.addWidget(self._subs_header)

        self._subs_label = QLabel("")
        self._subs_label.setStyleSheet("color: #8892a0; font-size: 13px;")
        self._subs_label.setVisible(False)
        body_layout.addWidget(self._subs_label)

        self._episodes_header = QLabel("Épisodes")
        self._episodes_header.setObjectName("section_title")
        self._episodes_header.setVisible(False)
        body_layout.addWidget(self._episodes_header)

        self._episodes_container = QWidget()
        self._episodes_layout = QVBoxLayout(self._episodes_container)
        self._episodes_layout.setContentsMargins(0, 0, 0, 0)
        self._episodes_layout.setSpacing(6)
        self._episodes_container.setVisible(False)
        body_layout.addWidget(self._episodes_container)

        body_layout.addStretch()
        self._layout.addWidget(body, stretch=1)

        self.setWidget(self._container)

    def show_media(self, media, media_service):
        self._media = media
        self._media_service = media_service

        title = media.title or "Unknown"
        if media.media_type == "episode" and media.series_name:
            title = media.series_name

        self._header.set_data(
            title=title,
            year=str(media.year) if media.year else "",
            genres=media.genres or "",
            rating=media.rating or "",
            duration=_format_duration(media.duration_sec) if media.duration_sec else "",
            backdrop_path=_resolve_backdrop(media),
            poster_path=_resolve_poster(media),
        )

        if media.resume_position and media.resume_position > 0 and not media.is_watched:
            self._btn_play.setText("▶  Reprendre")
        else:
            self._btn_play.setText("▶  Lire")

        if media.is_watched:
            self._btn_watched.setText("Marquer comme non vu")
        else:
            self._btn_watched.setText("Marquer comme vu")

        self._path_label.setText(media.file_path or "")

        if media.overview:
            self._synopsis_label.setText(media.overview)
            self._synopsis_header.setVisible(True)
            self._synopsis_label.setVisible(True)
        else:
            self._synopsis_header.setVisible(False)
            self._synopsis_label.setVisible(False)

        self._detect_subtitles(media.file_path)
        self._show_episodes(media)
        self.verticalScrollBar().setValue(0)

    def _on_play(self):
        if self._media:
            self.play_requested.emit(self._media.id)

    def _toggle_watched(self):
        if not self._media or not self._media_service:
            return

        if self._media.is_watched:
            self._media_service.mark_as_unwatched(self._media.id)
        else:
            self._media_service.mark_as_watched(self._media.id)
        refreshed = self._media_service.get_media_by_id(self._media.id)
        if refreshed:
            self.show_media(refreshed, self._media_service)

    def _detect_subtitles(self, file_path: str):
        if not file_path:
            self._subs_header.setVisible(False)
            self._subs_label.setVisible(False)
            return

        from core.config import SUPPORTED_SUBTITLE_EXTENSIONS

        media_path = Path(file_path)
        parent = media_path.parent
        stem = media_path.stem

        found = []
        if parent.exists():
            for ext in SUPPORTED_SUBTITLE_EXTENSIONS:
                candidate = parent / f"{stem}{ext}"
                if candidate.exists():
                    found.append(candidate.name)

                for lang in ["fr", "en", "es", "de", "it", "pt", "ja", "zh"]:
                    candidate = parent / f"{stem}.{lang}{ext}"
                    if candidate.exists():
                        found.append(candidate.name)

        if found:
            self._subs_header.setVisible(True)
            self._subs_label.setVisible(True)
            self._subs_label.setText(
                "\n".join(f"  📄  {f}" for f in sorted(set(found)))
            )
        else:
            self._subs_header.setVisible(False)
            self._subs_label.setVisible(False)

    def _show_episodes(self, media):
        while self._episodes_layout.count():
            item = self._episodes_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if (
            media.media_type != "episode"
            or not media.series_name
            or not self._media_service
        ):
            self._episodes_header.setVisible(False)
            self._episodes_container.setVisible(False)
            return

        all_eps = self._media_service.search_media(media.series_name, limit=200)
        episodes = [
            e
            for e in all_eps
            if e.media_type == "episode" and e.series_name == media.series_name
        ]
        episodes.sort(key=lambda e: (e.season_number or 0, e.episode_number or 0))

        if not episodes:
            self._episodes_header.setVisible(False)
            self._episodes_container.setVisible(False)
            return

        from collections import defaultdict

        seasons = defaultdict(list)
        for ep in episodes:
            seasons[ep.season_number or 0].append(ep)

        self._episodes_header.setVisible(True)
        self._episodes_container.setVisible(True)

        for season_num in sorted(seasons.keys()):
            eps = seasons[season_num]

            season_label = QLabel(
                f"Saison {season_num}" if season_num > 0 else "Saison inconnue"
            )
            season_label.setStyleSheet(
                "color: #eaeaea; font-size: 15px; font-weight: 600; padding-top: 8px;"
            )
            self._episodes_layout.addWidget(season_label)

            for ep in eps:
                row = EpisodeRow(ep)
                row.play_clicked.connect(self.play_requested.emit)
                if ep.id == media.id:
                    row.setStyleSheet("""
                        QFrame {
                            background-color: #2a3a5c;
                            border: 1px solid #e94560;
                            border-radius: 6px;
                            padding: 8px 12px;
                        }
                    """)
                self._episodes_layout.addWidget(row)

    def get_subtitle_paths(self) -> list:
        if not self._media or not self._media.file_path:
            return []

        from core.config import SUPPORTED_SUBTITLE_EXTENSIONS

        media_path = Path(self._media.file_path)
        parent = media_path.parent
        stem = media_path.stem
        found = []

        if parent.exists():
            for ext in SUPPORTED_SUBTITLE_EXTENSIONS:
                candidate = parent / f"{stem}{ext}"
                if candidate.exists():
                    found.append(str(candidate))
                for lang in ["fr", "en", "es", "de", "it", "pt", "ja", "zh"]:
                    candidate = parent / f"{stem}.{lang}{ext}"
                    if candidate.exists():
                        found.append(str(candidate))

        return sorted(set(found))
