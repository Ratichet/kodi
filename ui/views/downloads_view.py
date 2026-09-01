import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.models import DownloadStatus
from core.services.download_service import DownloadService

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    DownloadStatus.QUEUED.value: ("En attente", "#8892a0"),
    DownloadStatus.DOWNLOADING.value: ("Téléchargement", "#e94560"),
    DownloadStatus.PAUSED.value: ("En pause", "#8892a0"),
    DownloadStatus.DONE.value: ("Terminé", "#4ade80"),
    DownloadStatus.ERROR.value: ("Échec", "#e94560"),
}


def _human_size(num_bytes: int) -> str:
    if not num_bytes:
        return "—"
    size = float(num_bytes)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if size < 1024 or unit == "To":
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} To"


class _QueueWorker(QObject):
    """Vide la file d'attente, un téléchargement après l'autre.

    Un seul transfert à la fois : le débit est de toute façon partagé, et une file
    séquentielle évite d'avoir à arbitrer plusieurs écritures concurrentes en base.
    Le worker crée son propre `DownloadService`, une Session SQLAlchemy n'étant pas
    partageable entre threads.
    """

    # Une taille de fichier ne tient pas dans un Signal(int) : PySide le mappe sur
    # un int C++ 32 bits, qui déborde à 2,1 Gio — soit à peu près tous les films.
    progress = Signal(int, "qint64", "qint64")  # id, octets reçus, total
    item_finished = Signal(int, bool)  # id, succès
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False

    def request_stop(self):
        """Demandé depuis le thread graphique : coupe le transfert en cours."""
        self._stop_requested = True

    def run(self):
        service = DownloadService()
        try:
            while not self._stop_requested:
                download = service.next_queued()
                if download is None:
                    break

                download_id = download.id
                ok = service.run(
                    download_id,
                    on_progress=lambda received, total: self.progress.emit(
                        download_id, received, total
                    ),
                    should_stop=lambda: self._stop_requested,
                )
                self.item_finished.emit(download_id, ok)
        except Exception as e:
            logger.error(f"Download queue crashed: {e}", exc_info=True)
        finally:
            service.close()
            self.finished.emit()


class _DownloadRow(QFrame):
    remove_requested = Signal(int)
    retry_requested = Signal(int)

    def __init__(self, download, parent=None):
        super().__init__(parent)
        self.download_id = download.id
        self.setStyleSheet("background-color: #1e2a4a; border-radius: 6px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self._name = QLabel(download.filename)
        self._name.setStyleSheet("color: #eaeaea; font-size: 13px; font-weight: 600;")
        self._name.setWordWrap(True)
        top.addWidget(self._name, stretch=1)

        self._status = QLabel()
        self._status.setStyleSheet("font-size: 12px;")
        top.addWidget(self._status)

        self._btn_retry = QPushButton("↻")
        self._btn_retry.setObjectName("icon_button")
        self._btn_retry.setToolTip("Relancer")
        self._btn_retry.setFixedWidth(30)
        self._btn_retry.clicked.connect(
            lambda: self.retry_requested.emit(self.download_id)
        )
        top.addWidget(self._btn_retry)

        btn_remove = QPushButton("✕")
        btn_remove.setObjectName("icon_button")
        btn_remove.setToolTip("Retirer de la liste")
        btn_remove.setFixedWidth(30)
        btn_remove.clicked.connect(
            lambda: self.remove_requested.emit(self.download_id)
        )
        top.addWidget(btn_remove)
        layout.addLayout(top)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        layout.addWidget(self._bar)

        self._detail = QLabel()
        self._detail.setObjectName("subtitle")
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

        self.update_from(download)

    def update_from(self, download):
        self._name.setText(download.filename)
        label, color = _STATUS_LABELS.get(download.status, (download.status, "#8892a0"))
        self._status.setText(label)
        self._status.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._btn_retry.setVisible(
            download.status in (DownloadStatus.PAUSED.value, DownloadStatus.ERROR.value)
        )
        self.set_progress(download.received_bytes or 0, download.total_bytes or 0)

        if download.error:
            # Une archive qui refuse de s'ouvrir laisse un message sur un
            # téléchargement pourtant terminé : il doit rester visible.
            self._detail.setText(download.error)
        elif download.extracted_to:
            self._detail.setText(f"Archive extraite dans {download.extracted_to}")
        elif download.is_finished:
            self._detail.setText(download.file_path)

    def set_progress(self, received: int, total: int):
        if total:
            # Une taille en octets dépasse la plage d'un QProgressBar (int 32 bits) :
            # on travaille en pour mille.
            self._bar.setRange(0, 1000)
            self._bar.setValue(int(min(received / total, 1.0) * 1000))
            self._detail.setText(f"{_human_size(received)} / {_human_size(total)}")
        else:
            self._bar.setRange(0, 0)  # taille inconnue : barre indéterminée
            self._detail.setText(_human_size(received))


class DownloadsView(QScrollArea):
    """Écran Téléchargements : une file d'URL vers un dossier de la bibliothèque."""

    library_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)

        self._service = DownloadService()
        self._thread = None
        self._worker = None
        self._rows = {}

        container = QWidget()
        container.setObjectName("content_area")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Téléchargements")
        title.setObjectName("page_title")
        layout.addWidget(title)

        add_row = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("Collez un lien http(s) puis Entrée…")
        self._url_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e2a4a; color: #eaeaea; border: 1px solid #2a3450;
                border-radius: 4px; padding: 8px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #e94560; }
        """)
        self._url_input.returnPressed.connect(self._add_from_input)
        add_row.addWidget(self._url_input, stretch=1)

        btn_add = QPushButton("+ Ajouter")
        btn_add.setObjectName("primary_button")
        btn_add.clicked.connect(self._add_from_input)
        add_row.addWidget(btn_add)
        layout.addLayout(add_row)

        self._destination_label = QLabel()
        self._destination_label.setObjectName("subtitle")
        self._destination_label.setWordWrap(True)
        layout.addWidget(self._destination_label)

        controls = QHBoxLayout()
        self._btn_pause = QPushButton("⏸  Mettre en pause")
        self._btn_pause.setObjectName("secondary_button")
        self._btn_pause.clicked.connect(self._pause)
        controls.addWidget(self._btn_pause)

        btn_clear = QPushButton("Nettoyer les terminés")
        btn_clear.setObjectName("secondary_button")
        btn_clear.clicked.connect(self._clear_finished)
        controls.addWidget(btn_clear)
        controls.addStretch()
        layout.addLayout(controls)

        self._empty_label = QLabel("Aucun téléchargement.")
        self._empty_label.setObjectName("subtitle")
        layout.addWidget(self._empty_label)

        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(8)
        layout.addLayout(self._list_layout)

        layout.addStretch()
        self.setWidget(container)

    # =================================================================
    # Affichage
    # =================================================================

    def refresh(self, media_service=None):
        downloads = self._service.get_all()

        seen = set()
        for index, download in enumerate(downloads):
            seen.add(download.id)
            row = self._rows.get(download.id)
            if row is None:
                row = _DownloadRow(download)
                row.remove_requested.connect(self._remove)
                row.retry_requested.connect(self._retry)
                self._rows[download.id] = row
                self._list_layout.insertWidget(index, row)
            else:
                row.update_from(download)

        for download_id in list(self._rows):
            if download_id not in seen:
                self._rows.pop(download_id).deleteLater()

        self._empty_label.setVisible(not downloads)
        self._refresh_destination()
        self._btn_pause.setEnabled(self._thread is not None)

    def _refresh_destination(self):
        destination = self._service.download_dir()
        if self._service.destination_is_watched():
            self._destination_label.setStyleSheet("color: #8892a0; font-size: 12px;")
            self._destination_label.setText(
                f"Destination : {destination} — dossier surveillé, "
                "les fichiers terminés rejoignent la bibliothèque tout seuls."
            )
        else:
            self._destination_label.setStyleSheet("color: #e94560; font-size: 12px;")
            self._destination_label.setText(
                f"Destination : {destination} — ce dossier n'est pas surveillé, "
                "les fichiers n'apparaîtront pas dans la bibliothèque. "
                "Ajoutez-le dans les Paramètres."
            )

    # =================================================================
    # Actions
    # =================================================================

    def _add_from_input(self):
        url = self._url_input.text().strip()
        if not url:
            return

        if self._service.add(url) is None:
            self._destination_label.setStyleSheet("color: #e94560; font-size: 12px;")
            self._destination_label.setText(
                "Lien inutilisable : seules les URL http(s) directes sont acceptées."
            )
            return

        self._url_input.clear()
        self.refresh()
        self._start_queue()

    def _remove(self, download_id: int):
        # Le transfert en cours tient le fichier ouvert : on arrête la file avant
        # de supprimer quoi que ce soit.
        download = self._service.get(download_id)
        if download and download.status == DownloadStatus.DOWNLOADING.value:
            self._stop_queue()
        self._service.remove(download_id)
        self.refresh()

    def _retry(self, download_id: int):
        if self._service.requeue(download_id):
            self.refresh()
            self._start_queue()

    def _pause(self):
        self._service.pause_all()
        self._stop_queue()
        self.refresh()

    def _clear_finished(self):
        self._service.clear_finished()
        self.refresh()

    # =================================================================
    # File d'attente
    # =================================================================

    def is_busy(self) -> bool:
        return self._thread is not None

    def _start_queue(self):
        if self._thread is not None or not self._service.has_pending():
            return

        self._thread = QThread()
        self._worker = _QueueWorker()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.item_finished.connect(self._on_item_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_queue_finished)

        self._thread.start()
        self._btn_pause.setEnabled(True)

    def _stop_queue(self):
        if self._worker is not None:
            self._worker.request_stop()
        if self._thread is not None:
            self._thread.quit()
            # Le transfert s'arrête au bloc suivant : l'attente reste courte.
            if not self._thread.wait(10000):
                logger.warning("The download thread did not stop in time.")
            self._thread = None
            self._worker = None

    def _on_progress(self, download_id: int, received: int, total: int):
        row = self._rows.get(download_id)
        if row is not None:
            row.set_progress(received, total)

    def _on_item_finished(self, download_id: int, ok: bool):
        download = self._service.get(download_id)
        row = self._rows.get(download_id)
        if download is not None and row is not None:
            # La session de la vue a lu cette ligne avant le worker : sans
            # rafraîchissement, elle afficherait encore « en attente ».
            self._service.db.refresh(download)
            row.update_from(download)
        if ok:
            # Le fichier est complet : la surveillance de dossier l'indexe, mais
            # rien ne garantit que l'utilisateur est sur une vue qui se rafraîchit.
            self.library_changed.emit()

    def _on_queue_finished(self):
        self._thread = None
        self._worker = None
        self._btn_pause.setEnabled(False)
        self.refresh()

    def shutdown(self):
        """Arrête la file et rend la session. Appelé à la fermeture."""
        self._stop_queue()
        self._service.close()
