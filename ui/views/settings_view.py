import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QFrame,
    QProgressBar, QGroupBox, QGridLayout, QScrollArea, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QThread, QObject

logger = logging.getLogger(__name__)


class AutoScanWorker(QObject):
    progress = Signal(str, int, int)
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, media_service):
        super().__init__()
        self._media_service = media_service
    
    def run(self):
        try:
            self.progress.emit("Indexation des fichiers...", 0, 0)
            scanned_media = self._media_service.scan_all_directories()
            count = len(scanned_media)
            self.progress.emit(f"Enrichissement de {count} médias...", 0, 0)
            def on_progress(current, total, title):
                self.progress.emit(f"Metadonnées : {title}", current, total)

            stats = self._media_service.enrich_all_media(progress_callback=on_progress)

            self.progress.emit("Téléchargement des affiches...", 0, 0)
            self._media_service.download_all_posters()

            self.progress.emit("Téléchargement des fonds d'écran...", 0, 0)
            self._download_backdrops()

            result = {
                "scanned": count,
                "enriched": stats.get('success', 0),
                "failed": stats.get('failed', 0)
            }
            self.finished.emit(result)
            
        except Exception as e:
            logger.error(f"AutoScan process failed: {e}")
            self.error.emit(str(e))

    def _download_backdrops(self):
        try:
            from core.database import SessionLocal
            from core.models import Media
            from core.services.tmdb_service import TMDbService

            db = SessionLocal()
            service = TMDbService()

            media_list = db.query(Media).filter(Media.backdrop_path.isnot(None)).all()
            
            for media in media_list:
                service.download_backdrop(media.backdrop_path)
                
            db.close()
        except Exception as e:
            logger.error(f"Backdrop download error: {e}")

class SettingsView(QScrollArea):
    
    library_changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self._media_service = None
        
        self._thread = None
        self._worker = None
        
        container = QWidget()
        container.setObjectName("content_area")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(20)
        
        title = QLabel("Paramètres")
        title.setObjectName("page_title")
        layout.addWidget(title)

        dir_group = QGroupBox("Dossiers médias")
        dir_group.setStyleSheet("""
            QGroupBox {
                color: #eaeaea;
                font-size: 15px;
                font-weight: 600;
                border: 1px solid #2a3450;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 20px;
            }
            QGroupBox::title { subcontrol-origin: margin; padding: 0 8px; }
        """)
        dir_layout = QVBoxLayout(dir_group)
        dir_layout.setSpacing(10)
        
        dir_desc = QLabel(
            "Ajoutez les dossiers contenant vos films et séries. "
            "EpiKodi les scannera automatiquement."
        )
        dir_desc.setObjectName("subtitle")
        dir_desc.setWordWrap(True)
        dir_layout.addWidget(dir_desc)
        
        self._dir_list = QListWidget()
        self._dir_list.setMinimumHeight(120)
        self._dir_list.setMaximumHeight(200)
        dir_layout.addWidget(self._dir_list)
        
        btn_row = QHBoxLayout()
        self._btn_add_dir = QPushButton("+ Ajouter un dossier")
        self._btn_add_dir.setObjectName("primary_button")
        self._btn_add_dir.clicked.connect(self._add_directory)
        btn_row.addWidget(self._btn_add_dir)
        
        self._btn_remove_dir = QPushButton("Supprimer")
        self._btn_remove_dir.setObjectName("secondary_button")
        self._btn_remove_dir.clicked.connect(self._remove_directory)
        btn_row.addWidget(self._btn_remove_dir)
        
        btn_row.addStretch()
        dir_layout.addLayout(btn_row)
        layout.addWidget(dir_group)

        scan_group = QGroupBox("Mise à jour de la bibliothèque")
        scan_group.setStyleSheet(dir_group.styleSheet())
        scan_layout = QVBoxLayout(scan_group)
        scan_layout.setSpacing(12)
        
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        scan_layout.addWidget(self._progress_bar)
        
        self._status_label = QLabel("")
        self._status_label.setObjectName("subtitle")
        self._status_label.setVisible(False)
        scan_layout.addWidget(self._status_label)
        
        self._btn_scan = QPushButton("🔄  Tout mettre à jour (Scan + Métadonnées)")
        self._btn_scan.setObjectName("primary_button")
        self._btn_scan.setMinimumHeight(45)
        self._btn_scan.clicked.connect(self._start_auto_scan)
        scan_layout.addWidget(self._btn_scan)
        
        layout.addWidget(scan_group)

        stats_group = QGroupBox("Statistiques")
        stats_group.setStyleSheet(dir_group.styleSheet())
        stats_layout = QGridLayout(stats_group)
        stats_layout.setSpacing(8)
        
        self._stat_labels = {}
        stats_def = [
            ("total_media", "Total médias", 0, 0),
            ("movies", "Films", 0, 1),
            ("episodes", "Épisodes", 1, 0),
            ("watched", "Vus", 1, 1),
        ]
        
        for key, label_text, row, col in stats_def:
            frame = QFrame()
            frame.setStyleSheet("background-color: #1e2a4a; border-radius: 6px; padding: 12px;")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(12, 8, 12, 8)
            
            value_label = QLabel("0")
            value_label.setStyleSheet("color: #e94560; font-size: 24px; font-weight: 700;")
            value_label.setAlignment(Qt.AlignCenter)
            fl.addWidget(value_label)
            
            desc_label = QLabel(label_text)
            desc_label.setObjectName("subtitle")
            desc_label.setAlignment(Qt.AlignCenter)
            fl.addWidget(desc_label)
            
            stats_layout.addWidget(frame, row, col)
            self._stat_labels[key] = value_label
        
        layout.addWidget(stats_group)

        danger_group = QGroupBox("Zone de danger")
        danger_group.setStyleSheet("""
            QGroupBox {
                color: #e94560; border: 1px solid #e94560; border-radius: 8px;
                margin-top: 12px; padding-top: 20px;
            }
            QGroupBox::title { subcontrol-origin: margin; padding: 0 8px; }
        """)
        danger_layout = QHBoxLayout(danger_group)
        
        lbl_danger = QLabel("Attention : ceci effacera toute votre bibliothèque.")
        lbl_danger.setStyleSheet("color: #8892a0;")
        danger_layout.addWidget(lbl_danger)
        danger_layout.addStretch()
        
        self._btn_reset = QPushButton("☢  Tout effacer")
        self._btn_reset.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #e94560; border: 1px solid #e94560;
                padding: 8px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #e94560; color: white; }
        """)
        self._btn_reset.clicked.connect(self._reset_library)
        danger_layout.addWidget(self._btn_reset)
        
        layout.addWidget(danger_group)
        
        layout.addStretch()
        self.setWidget(container)
    
    def refresh(self, media_service):
        self._media_service = media_service
        self._refresh_directories()
        self._refresh_stats()
    
    def _refresh_directories(self):
        if not self._media_service: return
        self._dir_list.clear()
        dirs = self._media_service.get_media_directories(active_only=False)
        for d in dirs:
            status = "✓" if d.is_active else "✗"
            item = QListWidgetItem(f"{status}  {d.path}")
            item.setData(Qt.UserRole, d.id)
            self._dir_list.addItem(item)
    
    def _refresh_stats(self):
        if not self._media_service: return
        try:
            stats = self._media_service.get_stats()
            for key, label in self._stat_labels.items():
                label.setText(str(stats.get(key, 0)))
        except Exception:
            pass
    
    def _add_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Sélectionner un dossier média", str(Path.home()))
        if directory and self._media_service:
            self._media_service.add_media_directory(directory, recursive=True)
            self._refresh_directories()
    
    def _remove_directory(self):
        current = self._dir_list.currentItem()
        if current and self._media_service:
            self._media_service.remove_media_directory(current.data(Qt.UserRole))
            self._refresh_directories()
            
    def _reset_library(self):
        reply = QMessageBox.question(self, "Réinitialiser ?", "Êtes-vous sûr de vouloir tout supprimer ?", 
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes and self._media_service:
            try:
                # Assuming reset_database exists in service, or call drop_all here
                from core.database import Base, engine
                Base.metadata.drop_all(bind=engine)
                Base.metadata.create_all(bind=engine)
                self._refresh_directories()
                self._refresh_stats()
                self.library_changed.emit()
                QMessageBox.information(self, "Succès", "Bibliothèque remise à zéro.")
            except Exception as e:
                QMessageBox.critical(self, "Erreur", str(e))


    def _start_auto_scan(self):
        if not self._media_service:
            return
            
        self._set_scanning(True, "Démarrage de l'indexation...")

        self._thread = QThread()
        self._worker = AutoScanWorker(self._media_service)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        
        self._thread.start()

    def _on_progress(self, msg, current, total):
        self._status_label.setText(msg)
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
        else:
            self._progress_bar.setRange(0, 0) # Indéterminé (ex: téléchargement images)

    def _on_finished(self, result):
        msg = (f"Terminé : {result['scanned']} scannés, "
               f"{result['enriched']} enrichis.")
        self._set_scanning(False, msg)
        self._refresh_stats()
        self.library_changed.emit()
        
    def _on_error(self, err_msg):
        self._set_scanning(False, f"Erreur : {err_msg}")

    def _set_scanning(self, active, msg=""):
        self._btn_scan.setEnabled(not active)
        self._btn_add_dir.setEnabled(not active)
        self._btn_remove_dir.setEnabled(not active)
        self._btn_reset.setEnabled(not active)
        self._progress_bar.setVisible(active)
        self._status_label.setVisible(True)
        self._status_label.setText(msg)
        
        if active:
            self._progress_bar.setRange(0, 0)  # Indeterminate
    
    def _update_progress(self, current: int, total: int, title: str):
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
        self._status_label.setText(f"[{current}/{total}] {title}")

    def _download_all_backdrops(self):
        try:
            from core.database import SessionLocal
            from core.models import Media
            from core.services.tmdb_service import TMDbService

            db = SessionLocal()
            service = TMDbService()
            media_list = db.query(Media).filter(Media.backdrop_path.isnot(None)).all()

            for media in media_list:
                service.download_backdrop(media.backdrop_path)

            db.close()
        except Exception as e:
            logger.error(f"Failed to download backdrops: {e}")
    
    def _reset_library(self):
        from PySide6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self, 
            "Réinitialiser la bibliothèque ?",
            "Êtes-vous sûr de vouloir tout supprimer ?\nCette action est irréversible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self._media_service.reset_database():
                self._refresh_directories()
                self._refresh_stats()
                self.library_changed.emit()
                QMessageBox.information(self, "Succès", "La bibliothèque a été remise à zéro.")
            else:
                QMessageBox.critical(self, "Erreur", "Impossible de réinitialiser la base de données.")