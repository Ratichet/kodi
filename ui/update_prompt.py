"""Mise à jour au démarrage : vérifie, propose, télécharge puis relance."""

import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from core.config import APP_VERSION
from core.services import updater

logger = logging.getLogger(__name__)


class UpdatePrompt(QObject):
    # Émis depuis des threads annexes : la connexion différée ramène les slots
    # dans le thread Qt.
    _found = Signal(object)
    _progress = Signal("qint64", "qint64")
    _ready = Signal(object)
    _failed = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._dialog = None
        self._cancel = threading.Event()
        self._found.connect(self._ask)
        self._progress.connect(self._on_progress)
        self._ready.connect(self._install)
        self._failed.connect(self._on_failed)

    def check_in_background(self):
        if updater.install_dir() is None:
            return  # développement, autre système ou exécutable unique
        threading.Thread(target=self._check, name="epikodi-update", daemon=True).start()

    def _check(self):
        try:
            release = updater.check()
        except Exception as e:
            # Hors ligne, API indisponible : on retentera au prochain lancement.
            logger.info(f"Update check skipped: {e}")
            return
        if release is not None:
            self._found.emit(release)

    def _ask(self, release):
        reply = QMessageBox.question(
            self._window,
            "Mise à jour disponible",
            f"EpiKodi {release.version} est disponible "
            f"(version installée : {APP_VERSION}).\n\n"
            "L'installer maintenant ? L'application redémarrera.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self._cancel.clear()
        self._dialog = QProgressDialog(
            "Téléchargement de la mise à jour…", "Annuler", 0, 100, self._window
        )
        self._dialog.setWindowTitle("Mise à jour")
        self._dialog.setWindowModality(Qt.WindowModal)
        # Sinon la fenêtre se ferme à 100 %, avant la décompression.
        self._dialog.setAutoClose(False)
        self._dialog.setAutoReset(False)
        self._dialog.canceled.connect(self._cancel.set)
        self._dialog.show()
        threading.Thread(
            target=self._download, args=(release,), name="epikodi-update", daemon=True
        ).start()

    def _download(self, release):
        try:
            staging = updater.download(
                release, progress=self._progress.emit, cancelled=self._cancel.is_set
            )
        except updater.UpdateCancelled:
            return
        except Exception as e:
            self._failed.emit(str(e))
            return
        self._ready.emit(staging)

    def _on_progress(self, received: int, total: int):
        if self._dialog is None:
            return
        if total and received < total:
            self._dialog.setValue(int(received * 100 / total))
        else:
            self._dialog.setLabelText("Installation de la mise à jour…")
            self._dialog.setRange(0, 0)  # durée inconnue : barre animée

    def _install(self, staging):
        try:
            updater.install_and_restart(staging)
        except Exception as e:
            self._on_failed(str(e))
            return
        self._close_dialog()
        self._window.close()

    def _on_failed(self, message: str):
        self._close_dialog()
        logger.error(f"Update failed: {message}")
        QMessageBox.warning(
            self._window,
            "Mise à jour",
            f"La mise à jour a échoué :\n\n{message}\n\n"
            "EpiKodi continue avec la version actuelle.",
        )

    def _close_dialog(self):
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None
