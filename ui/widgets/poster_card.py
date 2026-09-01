from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel, QVBoxLayout

from ui.widgets.artwork import gradient_placeholder, load_async

CARD_WIDTH = 155
POSTER_HEIGHT = 225
CARD_HEIGHT = POSTER_HEIGHT + 52


class PosterCard(QFrame):
    clicked = Signal(int)
    play_requested = Signal(int)

    def __init__(
        self,
        media_id: int,
        title: str,
        subtitle: str = "",
        poster_path: str = None,
        is_watched: bool = False,
        resume_pct: float = 0.0,
        badge: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.media_id = media_id
        self._is_watched = is_watched
        self._resume_pct = resume_pct
        self._badge = badge
        self._hovered = False

        self.setObjectName("poster_card")
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.poster_label = QLabel()
        self.poster_label.setFixedSize(CARD_WIDTH, POSTER_HEIGHT)
        self.poster_label.setAlignment(Qt.AlignCenter)
        self.poster_label.setStyleSheet("border-radius: 8px 8px 0px 0px;")
        layout.addWidget(self.poster_label)

        self.title_label = QLabel(self._truncate(title, 20))
        self.title_label.setObjectName("card_title")
        self.title_label.setToolTip(title)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("card_subtitle")
        layout.addWidget(self.subtitle_label)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        self._base_pixmap = gradient_placeholder(
            CARD_WIDTH,
            POSTER_HEIGHT,
            seed=title,
            caption=self._truncate(title, 22),
            glyph=(title[:1].upper() if title else "?"),
        )
        self._apply_pixmap()

        # L'affiche arrive de façon asynchrone : ouvrir une grille de plusieurs
        # centaines de cartes ne gèle plus l'interface.
        if poster_path:
            load_async(poster_path, CARD_WIDTH, POSTER_HEIGHT, self._on_poster_ready)

    # ── visuel ────────────────────────────────────────────────────────────────

    def _on_poster_ready(self, pixmap: QPixmap):
        try:
            self._base_pixmap = pixmap
            self._apply_pixmap()
        except RuntimeError:
            # Carte détruite pendant le décodage (grille rechargée entre-temps).
            pass

    def _apply_pixmap(self):
        canvas = QPixmap(self._base_pixmap)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._hovered:
            painter.fillRect(canvas.rect(), QColor(0, 0, 0, 80))
            painter.setBrush(QColor(233, 69, 96))
            painter.setPen(Qt.NoPen)
            radius = 22
            cx, cy = CARD_WIDTH // 2, POSTER_HEIGHT // 2
            painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
            triangle = QPainterPath()
            triangle.moveTo(cx - 6, cy - 11)
            triangle.lineTo(cx + 12, cy)
            triangle.lineTo(cx - 6, cy + 11)
            triangle.closeSubpath()
            painter.fillPath(triangle, QColor("white"))

        if self._badge:
            painter.setBrush(QColor(18, 22, 41, 215))
            painter.setPen(Qt.NoPen)
            width = 14 + 7 * len(self._badge)
            painter.drawRoundedRect(6, 6, width, 20, 10, 10)
            painter.setPen(QColor("#eaeaea"))
            painter.drawText(QRectF(6, 6, width, 20), Qt.AlignCenter, self._badge)

        if self._is_watched:
            painter.setBrush(QColor(46, 213, 115))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(CARD_WIDTH - 28, 6, 22, 22)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawLine(CARD_WIDTH - 22, 17, CARD_WIDTH - 17, 22)
            painter.drawLine(CARD_WIDTH - 17, 22, CARD_WIDTH - 11, 12)
        elif self._resume_pct > 0:
            bar_height = 4
            top = POSTER_HEIGHT - bar_height
            painter.fillRect(0, top, CARD_WIDTH, bar_height, QColor(0, 0, 0, 150))
            painter.fillRect(
                QRectF(0, top, CARD_WIDTH * min(self._resume_pct, 1.0), bar_height),
                QColor(233, 69, 96),
            )

        painter.end()
        self.poster_label.setPixmap(canvas)

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if not text:
            return ""
        return text if len(text) <= max_len else text[: max_len - 1] + "…"

    # ── interactions ──────────────────────────────────────────────────────────

    def enterEvent(self, event):
        self._hovered = True
        self._apply_pixmap()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_pixmap()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.media_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.play_requested.emit(self.media_id)
        super().mouseDoubleClickEvent(event)

    def sizeHint(self):
        return QSize(CARD_WIDTH, CARD_HEIGHT)
