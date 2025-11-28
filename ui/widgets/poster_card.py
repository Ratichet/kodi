from pathlib import Path
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QLinearGradient, QBrush, QPen


CARD_WIDTH = 155
POSTER_HEIGHT = 225
CARD_HEIGHT = POSTER_HEIGHT + 52


class PosterCard(QFrame):
    
    clicked = Signal(int)
    play_requested = Signal(int)
    
    def __init__(self, media_id: int, title: str, subtitle: str = "",
                 poster_path: str = None, is_watched: bool = False,
                 resume_pct: float = 0.0, parent=None):
        super().__init__(parent)
        self.media_id = media_id
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
        
        pixmap = self._load_poster(poster_path, title)

        if is_watched or resume_pct > 0:
            pixmap = self._draw_overlay(pixmap, is_watched, resume_pct)
        
        self.poster_label.setPixmap(pixmap)
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
    
    def _load_poster(self, poster_path: str, title: str) -> QPixmap:
        if poster_path and Path(poster_path).exists():
            pixmap = QPixmap(poster_path)
            return pixmap.scaled(
                CARD_WIDTH, POSTER_HEIGHT,
                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            ).copy(0, 0, CARD_WIDTH, POSTER_HEIGHT)
        return self._generate_placeholder(title)
    
    def _generate_placeholder(self, title: str) -> QPixmap:
        pixmap = QPixmap(CARD_WIDTH, POSTER_HEIGHT)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        h = hash(title) % 360
        color1 = QColor.fromHsv(h, 120, 70)
        color2 = QColor.fromHsv((h + 40) % 360, 100, 50)
        
        gradient = QLinearGradient(0, 0, CARD_WIDTH, POSTER_HEIGHT)
        gradient.setColorAt(0, color1)
        gradient.setColorAt(1, color2)
        painter.fillRect(pixmap.rect(), QBrush(gradient))

        painter.setPen(QPen(QColor(255, 255, 255, 30), 2))
        icon_y = POSTER_HEIGHT // 2 - 30
        painter.drawRect(CARD_WIDTH // 2 - 25, icon_y, 50, 40)
        for i in range(5):
            x = CARD_WIDTH // 2 - 25 + i * 12
            painter.drawLine(x, icon_y - 12, x + 8, icon_y)
        painter.drawRect(CARD_WIDTH // 2 - 25, icon_y - 12, 50, 12)

        painter.setPen(QColor(255, 255, 255, 180))
        font = QFont("Segoe UI", 36, QFont.Bold)
        painter.setFont(font)
        initial = title[0].upper() if title else "?"
        painter.drawText(pixmap.rect().adjusted(0, 20, 0, 0), Qt.AlignCenter, initial)

        overlay = QLinearGradient(0, POSTER_HEIGHT - 60, 0, POSTER_HEIGHT)
        overlay.setColorAt(0, QColor(0, 0, 0, 0))
        overlay.setColorAt(1, QColor(0, 0, 0, 160))
        painter.fillRect(0, POSTER_HEIGHT - 60, CARD_WIDTH, 60, QBrush(overlay))
        
        painter.setPen(QColor(255, 255, 255, 220))
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        text_rect = pixmap.rect().adjusted(8, 0, -8, -8)
        painter.drawText(text_rect, Qt.AlignBottom | Qt.AlignLeft,
                         self._truncate(title, 22))
        
        painter.end()
        return pixmap
    
    def _draw_overlay(self, pixmap: QPixmap, is_watched: bool, resume_pct: float) -> QPixmap:
        result = QPixmap(pixmap)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)

        if is_watched:
            painter.setBrush(QColor(46, 213, 115))  # green
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(CARD_WIDTH - 28, 6, 22, 22)
            
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawLine(CARD_WIDTH - 22, 17, CARD_WIDTH - 17, 22)
            painter.drawLine(CARD_WIDTH - 17, 22, CARD_WIDTH - 11, 12)

        if resume_pct > 0 and not is_watched:
            bar_h = 3
            bar_y = POSTER_HEIGHT - bar_h
            painter.fillRect(0, bar_y, CARD_WIDTH, bar_h, QColor(0, 0, 0, 150))
            fill_w = int(CARD_WIDTH * min(resume_pct, 1.0))
            painter.fillRect(0, bar_y, fill_w, bar_h, QColor(233, 69, 96))  # accent
        
        painter.end()
        return result
    
    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if not text:
            return ""
        return text if len(text) <= max_len else text[:max_len - 1] + "…"
    
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