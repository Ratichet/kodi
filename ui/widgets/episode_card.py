"""Carte d'épisode : vignette 16:9, avancement de lecture et résumé."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ui.widgets.artwork import gradient_placeholder, load_async

STILL_WIDTH = 288
STILL_HEIGHT = 162  # 16:9
CARD_WIDTH = STILL_WIDTH
CARD_HEIGHT = STILL_HEIGHT + 96


def _format_runtime(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return ""
    minutes = seconds // 60
    if minutes >= 60:
        return f"{minutes // 60}h{minutes % 60:02d}"
    return f"{minutes} min"


class EpisodeCard(QFrame):
    """Une carte par épisode, avec l'image propre à l'épisode quand TMDb en fournit une."""

    clicked = Signal(int)  # media_id — lecture / reprise
    details_requested = Signal(int)
    watched_toggled = Signal(int, bool)  # media_id, nouvel état

    def __init__(self, media, series_prefix: str = "", parent=None):
        """`series_prefix` nomme la série : indispensable hors du contexte d'une
        série, par exemple dans les rangées de l'Accueil qui en mélangent plusieurs."""
        super().__init__(parent)
        self.media_id = media.id
        self._is_watched = bool(media.is_watched)
        self._progress = media.progress_ratio
        self._hovered = False

        self.setObjectName("episode_card")
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._still = QLabel()
        self._still.setFixedSize(STILL_WIDTH, STILL_HEIGHT)
        self._still.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._still)

        code = media.episode_code or "—"
        title = media.episode_title or media.title or "Épisode"
        self._title_label = QLabel(f"{code}  ·  {title}")
        self._title_label.setObjectName("episode_title")
        self._title_label.setWordWrap(True)
        self._title_label.setToolTip(title)
        self._title_label.setFixedHeight(38)
        layout.addWidget(self._title_label)

        meta = []
        if series_prefix:
            meta.append(series_prefix)
        runtime = _format_runtime(media.duration_sec)
        if runtime:
            meta.append(runtime)
        if self._is_watched:
            meta.append("✓ Vu")
        elif self._progress > 0:
            meta.append(f"{int(self._progress * 100)} % vu")
        self._meta_label = QLabel("  ·  ".join(meta))
        self._meta_label.setObjectName("episode_meta")
        layout.addWidget(self._meta_label)

        overview = " ".join((media.overview or "").split())
        self._overview_label = QLabel(self._shorten(overview, 95))
        self._overview_label.setObjectName("episode_overview")
        self._overview_label.setWordWrap(True)
        self._overview_label.setFixedHeight(32)
        if overview:
            self._overview_label.setToolTip(overview)
        layout.addWidget(self._overview_label)

        self._base_pixmap = gradient_placeholder(
            STILL_WIDTH, STILL_HEIGHT, seed=title, glyph=code
        )
        self._apply_pixmap()

        from core.services.tmdb_service import local_still

        still_path = local_still(media)
        if still_path:
            load_async(still_path, STILL_WIDTH, STILL_HEIGHT, self._on_still_ready)

    # ── visuel ────────────────────────────────────────────────────────────────

    def _on_still_ready(self, pixmap: QPixmap):
        try:
            self._base_pixmap = pixmap
            self._apply_pixmap()
        except RuntimeError:
            # La carte a été détruite pendant le décodage (changement de saison).
            pass

    def _apply_pixmap(self):
        canvas = QPixmap(self._base_pixmap)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._is_watched:
            painter.fillRect(canvas.rect(), QColor(10, 14, 26, 110))

        if self._hovered:
            painter.fillRect(canvas.rect(), QColor(0, 0, 0, 90))
            painter.setBrush(QColor(233, 69, 96))
            painter.setPen(Qt.NoPen)
            radius = 22
            cx, cy = STILL_WIDTH // 2, STILL_HEIGHT // 2
            painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
            triangle = QPainterPath()
            triangle.moveTo(cx - 6, cy - 11)
            triangle.lineTo(cx + 12, cy)
            triangle.lineTo(cx - 6, cy + 11)
            triangle.closeSubpath()
            painter.fillPath(triangle, QColor("white"))

        if self._is_watched:
            painter.setBrush(QColor(46, 213, 115))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(STILL_WIDTH - 32, 8, 22, 22)
            painter.setPen(QColor("white"))
            check = QPainterPath()
            check.moveTo(STILL_WIDTH - 26, 19)
            check.lineTo(STILL_WIDTH - 22, 24)
            check.lineTo(STILL_WIDTH - 15, 13)
            painter.strokePath(check, painter.pen())
        elif self._progress > 0:
            bar_height = 4
            top = STILL_HEIGHT - bar_height
            painter.fillRect(0, top, STILL_WIDTH, bar_height, QColor(0, 0, 0, 150))
            painter.fillRect(
                QRectF(0, top, STILL_WIDTH * self._progress, bar_height),
                QColor(233, 69, 96),
            )

        painter.end()
        self._still.setPixmap(canvas)

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        if not text:
            return "Aucun résumé disponible."
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    # ── interactions ──────────────────────────────────────────────────────────

    def enterEvent(self, event):
        self._hovered = True
        self._apply_pixmap()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_pixmap()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.media_id)
        super().mouseReleaseEvent(event)

    def _show_menu(self, pos):
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e2a4a; color: #eaeaea;
                border: 1px solid #2a3450; border-radius: 6px; padding: 4px;
            }
            QMenu::item { padding: 8px 16px; border-radius: 4px; }
            QMenu::item:selected { background-color: #e94560; }
        """)
        play = menu.addAction("▶  Lire")
        toggle = menu.addAction(
            "Marquer comme non vu" if self._is_watched else "Marquer comme vu"
        )
        menu.addSeparator()
        details = menu.addAction("Détails de l'épisode")

        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen == play:
            self.clicked.emit(self.media_id)
        elif chosen == toggle:
            self.watched_toggled.emit(self.media_id, not self._is_watched)
        elif chosen == details:
            self.details_requested.emit(self.media_id)
