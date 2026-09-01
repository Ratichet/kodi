"""Chargement des visuels hors du thread d'interface.

Décoder un JPEG coûte quelques millisecondes ; multiplié par le nombre de cartes
d'une grille, cela gelait visiblement la fenêtre à chaque changement de vue. Ici
le décodage se fait dans un pool de threads (QImage y est autorisé, pas QPixmap)
et seule la conversion finale revient au thread Qt.
"""

import itertools
import logging
import threading
import zlib

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPixmap,
)

logger = logging.getLogger(__name__)


class _Dispatcher(QObject):
    """Point de rendez-vous unique entre le pool de threads et le thread Qt.

    Un QObject par tâche ne fonctionne pas : QThreadPool détruit le QRunnable dès
    que run() se termine, et le signal en file d'attente part avec lui — les images
    n'arrivaient jamais. Ce dispatcher vit aussi longtemps que l'application.
    """

    ready = Signal(int, QImage)


_dispatcher: _Dispatcher | None = None
_callbacks: dict[int, object] = {}
_lock = threading.Lock()
_tokens = itertools.count()


def _get_dispatcher() -> _Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()
        _dispatcher.ready.connect(_deliver)
    return _dispatcher


def _deliver(token: int, image: QImage):
    """Exécuté dans le thread Qt : c'est ici, et seulement ici, qu'on crée un QPixmap."""
    with _lock:
        entry = _callbacks.pop(token, None)
    if entry is None:
        return
    on_ready, width, height = entry
    pixmap = QPixmap.fromImage(image)
    if pixmap.isNull():
        return
    try:
        on_ready(pixmap.copy(0, 0, width, height))
    except RuntimeError:
        # Le widget destinataire a été détruit entre-temps (grille rechargée).
        pass


class _LoadTask(QRunnable):
    def __init__(self, token: int, path: str, width: int, height: int):
        super().__init__()
        self._token = token
        self._path = path
        self._width = width
        self._height = height
        self.setAutoDelete(True)

    def run(self):
        try:
            image = QImage(self._path)
            if image.isNull():
                raise ValueError("unreadable image")
            image = image.scaled(
                self._width,
                self._height,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
        except Exception as e:
            logger.debug(f"Could not load artwork {self._path}: {e}")
            with _lock:
                _callbacks.pop(self._token, None)
            return
        _get_dispatcher().ready.emit(self._token, image)


def load_async(path: str, width: int, height: int, on_ready) -> None:
    """Décode `path` en tâche de fond puis appelle `on_ready(QPixmap)`.

    `on_ready` s'exécute dans le thread Qt.
    """
    _get_dispatcher()  # créé dans le thread appelant, avant la tâche
    token = next(_tokens)
    with _lock:
        _callbacks[token] = (on_ready, width, height)
    QThreadPool.globalInstance().start(_LoadTask(token, path, width, height))


def wait_for_pending(timeout_ms: int = 3000) -> bool:
    """Attend la fin des décodages en cours (fermeture de l'application, tests)."""
    return QThreadPool.globalInstance().waitForDone(timeout_ms)


def gradient_placeholder(
    width: int, height: int, seed: str, caption: str = "", glyph: str = ""
) -> QPixmap:
    """Visuel de repli. La couleur est dérivée d'un CRC32, pas de hash() : ce dernier
    est randomisé à chaque démarrage de Python et la bibliothèque changeait de
    couleurs à chaque lancement."""
    pixmap = QPixmap(width, height)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    hue = zlib.crc32((seed or "?").encode("utf-8")) % 360
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor.fromHsv(hue, 120, 70))
    gradient.setColorAt(1, QColor.fromHsv((hue + 40) % 360, 100, 45))
    painter.fillRect(0, 0, width, height, QBrush(gradient))

    if glyph:
        painter.setPen(QColor(255, 255, 255, 60))
        painter.setFont(QFont("Segoe UI", max(height // 3, 12), QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, glyph)

    if caption:
        shade = QLinearGradient(0, height - 56, 0, height)
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        shade.setColorAt(1, QColor(0, 0, 0, 170))
        painter.fillRect(0, height - 56, width, 56, QBrush(shade))

        painter.setPen(QColor(255, 255, 255, 220))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            pixmap.rect().adjusted(8, 0, -8, -8),
            Qt.AlignBottom | Qt.AlignLeft,
            caption,
        )

    painter.end()
    return pixmap
