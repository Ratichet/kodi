import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class _Cancelled(Exception):
    """Levée depuis un callback de progression pour interrompre une tâche."""


class _LibraryWorker(QObject):
    """Base des tâches de bibliothèque exécutées dans un QThread.

    Le worker crée son propre MediaService : une Session SQLAlchemy n'est pas
    thread-safe et celle de la fenêtre principale reste utilisée par l'UI pendant
    toute la durée du scan.
    """

    progress = Signal(str, int, int)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False

    def request_stop(self):
        """Demande l'arrêt (appelé depuis le thread UI à la fermeture)."""
        self._stop_requested = True

    def run(self):
        from core.services.media_service import MediaService

        service = MediaService()
        try:
            self.finished.emit(self._execute(service))
        except _Cancelled:
            logger.info(f"{type(self).__name__} cancelled.")
            self.error.emit("Tâche annulée.")
        except Exception as e:
            logger.error(f"{type(self).__name__} failed: {e}", exc_info=True)
            self.error.emit(str(e))
        finally:
            service.close()

    def _execute(self, service) -> dict:
        raise NotImplementedError

    def _emit_step(self, message: str):
        if self._stop_requested:
            raise _Cancelled
        self.progress.emit(message, 0, 0)

    def _on_progress(self, prefix):
        def callback(current, total, title):
            if self._stop_requested:
                raise _Cancelled
            self.progress.emit(f"{prefix} : {title}", current, total)

        return callback


class AutoScanWorker(_LibraryWorker):
    def _execute(self, service) -> dict:
        self._emit_step("Indexation des fichiers...")
        count = len(service.scan_all_directories())
        self._emit_step(f"Enrichissement de {count} médias...")

        stats = service.enrich_all_media(
            progress_callback=self._on_progress("Metadonnées")
        )

        # Un média déjà enrichi n'est pas repassé par l'étape précédente : cette
        # passe va chercher ce qui manque encore à sa fiche (casting, titre
        # d'épisode), sans quoi une ancienne bibliothèque ne se compléterait jamais.
        self._emit_step("Complément des fiches...")
        service.fill_missing_details(progress_callback=self._on_progress("Fiches"))

        self._emit_step("Téléchargement des images...")
        service.download_all_artwork(progress_callback=self._on_progress("Images"))

        return {
            "scanned": count,
            "enriched": stats.get("success", 0),
            "failed": stats.get("failed", 0),
        }


class ReEnrichWorker(_LibraryWorker):
    def _execute(self, service) -> dict:
        self._emit_step("Mise à jour des métadonnées...")

        stats = service.re_enrich_all_media(
            progress_callback=self._on_progress("Mise à jour")
        )

        self._emit_step("Téléchargement des images...")
        service.download_all_artwork(progress_callback=self._on_progress("Images"))

        return {
            "scanned": 0,
            "enriched": stats.get("success", 0),
            "failed": stats.get("failed", 0),
        }


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

        # --- TMDB API Settings ---
        tmdb_group = QGroupBox("Configuration TMDB")
        tmdb_group.setStyleSheet(dir_group.styleSheet())
        tmdb_layout = QVBoxLayout(tmdb_group)
        tmdb_layout.setSpacing(10)

        tmdb_desc = QLabel(
            "Entrez votre clé API TMDB pour enrichir vos médias avec les métadonnées. "
            "Obtenez-en une sur themoviedb.org/settings/api"
        )
        tmdb_desc.setObjectName("subtitle")
        tmdb_desc.setWordWrap(True)
        tmdb_layout.addWidget(tmdb_desc)

        key_row = QHBoxLayout()
        key_label = QLabel("Clé API :")
        key_label.setStyleSheet("color: #eaeaea; font-size: 13px;")
        key_label.setFixedWidth(80)
        key_row.addWidget(key_label)

        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("Votre clé API TMDB...")
        self._api_key_input.setEchoMode(QLineEdit.Password)
        self._api_key_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e2a4a; color: #eaeaea; border: 1px solid #2a3450;
                border-radius: 4px; padding: 8px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #e94560; }
        """)
        key_row.addWidget(self._api_key_input)

        self._btn_toggle_key = QPushButton("Voir")
        self._btn_toggle_key.setFixedWidth(50)
        self._btn_toggle_key.setStyleSheet("""
            QPushButton {
                background-color: #1e2a4a; color: #8892a0; border: 1px solid #2a3450;
                border-radius: 4px; padding: 8px;
            }
            QPushButton:hover { color: #eaeaea; border-color: #e94560; }
        """)
        self._btn_toggle_key.clicked.connect(self._toggle_key_visibility)
        key_row.addWidget(self._btn_toggle_key)
        tmdb_layout.addLayout(key_row)

        lang_row = QHBoxLayout()
        lang_label = QLabel("Langue :")
        lang_label.setStyleSheet("color: #eaeaea; font-size: 13px;")
        lang_label.setFixedWidth(80)
        lang_row.addWidget(lang_label)

        self._lang_combo = QComboBox()
        self._lang_combo.setStyleSheet("""
            QComboBox {
                background-color: #1e2a4a; color: #eaeaea; border: 1px solid #2a3450;
                border-radius: 4px; padding: 8px; font-size: 13px;
            }
            QComboBox:focus { border-color: #e94560; }
            QComboBox QAbstractItemView {
                background-color: #1e2a4a; color: #eaeaea; selection-background-color: #e94560;
            }
        """)
        self._lang_combo.addItem("Français", "fr-FR")
        self._lang_combo.addItem("English", "en-US")
        self._lang_combo.addItem("Español", "es-ES")
        self._lang_combo.addItem("Deutsch", "de-DE")
        self._lang_combo.addItem("Italiano", "it-IT")
        self._lang_combo.addItem("Português", "pt-BR")
        self._lang_combo.addItem("日本語", "ja-JP")
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()
        tmdb_layout.addLayout(lang_row)

        self._btn_save_tmdb = QPushButton("Sauvegarder la configuration TMDB")
        self._btn_save_tmdb.setObjectName("primary_button")
        self._btn_save_tmdb.clicked.connect(self._save_tmdb_settings)
        tmdb_layout.addWidget(self._btn_save_tmdb)

        self._tmdb_status_label = QLabel("")
        self._tmdb_status_label.setStyleSheet("color: #8892a0; font-size: 12px;")
        tmdb_layout.addWidget(self._tmdb_status_label)

        layout.addWidget(tmdb_group)

        # --- Lecture ---
        playback_group = QGroupBox("Lecture")
        playback_group.setStyleSheet(dir_group.styleSheet())
        playback_layout = QVBoxLayout(playback_group)
        playback_layout.setSpacing(10)

        playback_desc = QLabel(
            "Sur un fichier multilingue, EpiKodi sélectionne à l'ouverture la piste "
            "audio et les sous-titres de ces langues, quand le fichier en propose. "
            "Le choix s'applique à la lecture suivante."
        )
        playback_desc.setObjectName("subtitle")
        playback_desc.setWordWrap(True)
        playback_layout.addWidget(playback_desc)

        self._audio_lang_combo = self._new_language_combo()
        # Connecté après le remplissage : sinon le premier addItem, qui fait
        # passer l'index de -1 à 0, déclencherait déjà une écriture.
        self._audio_lang_combo.currentIndexChanged.connect(self._save_audio_language)
        playback_layout.addLayout(
            self._language_row("Audio :", self._audio_lang_combo)
        )

        self._sub_lang_combo = self._new_language_combo()
        self._sub_lang_combo.currentIndexChanged.connect(self._save_subtitle_language)
        playback_layout.addLayout(
            self._language_row("Sous-titres :", self._sub_lang_combo)
        )

        self._playback_status_label = QLabel("")
        self._playback_status_label.setStyleSheet("color: #8892a0; font-size: 12px;")
        playback_layout.addWidget(self._playback_status_label)

        layout.addWidget(playback_group)

        # --- Téléchargements ---
        dl_group = QGroupBox("Téléchargements")
        dl_group.setStyleSheet(dir_group.styleSheet())
        dl_layout = QVBoxLayout(dl_group)
        dl_layout.setSpacing(10)

        dl_desc = QLabel(
            "Dossier d'arrivée des téléchargements. Vide, EpiKodi utilise le premier "
            "dossier surveillé, pour que les fichiers terminés rejoignent la "
            "bibliothèque tout seuls."
        )
        dl_desc.setObjectName("subtitle")
        dl_desc.setWordWrap(True)
        dl_layout.addWidget(dl_desc)

        dest_row = QHBoxLayout()
        dest_label = QLabel("Dossier :")
        dest_label.setStyleSheet("color: #eaeaea; font-size: 13px;")
        dest_label.setFixedWidth(95)
        dest_row.addWidget(dest_label)

        self._download_dir_input = QLineEdit()
        self._download_dir_input.setReadOnly(True)
        self._download_dir_input.setPlaceholderText("Premier dossier surveillé")
        self._download_dir_input.setStyleSheet(self._api_key_input.styleSheet())
        dest_row.addWidget(self._download_dir_input)

        btn_browse_dl = QPushButton("Parcourir")
        btn_browse_dl.setObjectName("secondary_button")
        btn_browse_dl.clicked.connect(self._choose_download_dir)
        dest_row.addWidget(btn_browse_dl)

        btn_reset_dl = QPushButton("Défaut")
        btn_reset_dl.setObjectName("secondary_button")
        btn_reset_dl.clicked.connect(self._reset_download_dir)
        dest_row.addWidget(btn_reset_dl)
        dl_layout.addLayout(dest_row)

        dl_key_desc = QLabel(
            "Un lien 1fichier pointe vers une page, pas vers le fichier : il faut une "
            "clé API (compte payant) pour obtenir le lien direct. Elle est enregistrée "
            "dans settings.json, qui n'est pas versionné."
        )
        dl_key_desc.setObjectName("subtitle")
        dl_key_desc.setWordWrap(True)
        dl_layout.addWidget(dl_key_desc)

        key_row_1f = QHBoxLayout()
        key_label_1f = QLabel("1fichier :")
        key_label_1f.setStyleSheet("color: #eaeaea; font-size: 13px;")
        key_label_1f.setFixedWidth(95)
        key_row_1f.addWidget(key_label_1f)

        self._onefichier_key_input = QLineEdit()
        self._onefichier_key_input.setPlaceholderText("Clé API 1fichier…")
        self._onefichier_key_input.setEchoMode(QLineEdit.Password)
        self._onefichier_key_input.setStyleSheet(self._api_key_input.styleSheet())
        key_row_1f.addWidget(self._onefichier_key_input)

        self._btn_toggle_1f = QPushButton("Voir")
        self._btn_toggle_1f.setFixedWidth(50)
        self._btn_toggle_1f.setStyleSheet(self._btn_toggle_key.styleSheet())
        self._btn_toggle_1f.clicked.connect(self._toggle_onefichier_visibility)
        key_row_1f.addWidget(self._btn_toggle_1f)

        btn_save_1f = QPushButton("Enregistrer")
        btn_save_1f.setObjectName("primary_button")
        btn_save_1f.clicked.connect(self._save_onefichier_key)
        key_row_1f.addWidget(btn_save_1f)
        dl_layout.addLayout(key_row_1f)

        self._download_status_label = QLabel("")
        self._download_status_label.setStyleSheet("color: #8892a0; font-size: 12px;")
        self._download_status_label.setWordWrap(True)
        dl_layout.addWidget(self._download_status_label)

        layout.addWidget(dl_group)

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
            frame.setStyleSheet(
                "background-color: #1e2a4a; border-radius: 6px; padding: 12px;"
            )
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(12, 8, 12, 8)

            value_label = QLabel("0")
            value_label.setStyleSheet(
                "color: #e94560; font-size: 24px; font-weight: 700;"
            )
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
        self._refresh_tmdb_settings()
        self._refresh_playback_languages()
        self._refresh_download_settings()

    def _refresh_directories(self):
        if not self._media_service:
            return
        self._dir_list.clear()
        dirs = self._media_service.get_media_directories(active_only=False)
        for d in dirs:
            status = "✓" if d.is_active else "✗"
            item = QListWidgetItem(f"{status}  {d.path}")
            item.setData(Qt.UserRole, d.id)
            self._dir_list.addItem(item)

    def _refresh_stats(self):
        if not self._media_service:
            return
        try:
            stats = self._media_service.get_stats()
            for key, label in self._stat_labels.items():
                label.setText(str(stats.get(key, 0)))
        except Exception:
            pass

    def _add_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Sélectionner un dossier média", str(Path.home())
        )
        if directory and self._media_service:
            self._media_service.add_media_directory(directory, recursive=True)
            self._refresh_directories()

    def _remove_directory(self):
        current = self._dir_list.currentItem()
        if current and self._media_service:
            self._media_service.remove_media_directory(current.data(Qt.UserRole))
            self._refresh_directories()

    def _refresh_tmdb_settings(self):
        from core.config import get_tmdb_api_key, get_tmdb_language

        self._api_key_input.setText(get_tmdb_api_key())

        lang = get_tmdb_language()
        idx = self._lang_combo.findData(lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

        if get_tmdb_api_key():
            self._tmdb_status_label.setText("Clé API configurée.")
            self._tmdb_status_label.setStyleSheet("color: #4ade80; font-size: 12px;")
        else:
            self._tmdb_status_label.setText("Aucune clé API configurée.")
            self._tmdb_status_label.setStyleSheet("color: #e94560; font-size: 12px;")

    def _save_tmdb_settings(self):
        from core.config import SETTINGS_FILE, get_tmdb_language, set_setting

        api_key = self._api_key_input.text().strip()
        language = self._lang_combo.currentData()

        old_language = get_tmdb_language()
        language_changed = api_key and old_language != language

        saved = set_setting("tmdb_api_key", api_key)
        saved = set_setting("tmdb_language", language) and saved

        self._refresh_tmdb_settings()

        if not saved:
            QMessageBox.critical(
                self,
                "Erreur",
                f"Impossible d'écrire les réglages dans :\n{SETTINGS_FILE}",
            )
            return

        if not api_key:
            QMessageBox.warning(
                self, "Attention",
                "Clé API vide. L'enrichissement des métadonnées ne fonctionnera pas."
            )
            return

        if language_changed and self._media_service:
            reply = QMessageBox.question(
                self,
                "Langue modifiée",
                "La langue a été modifiée. Voulez-vous mettre à jour "
                "les titres et descriptions de vos médias ?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self._start_re_enrich()
                return

        QMessageBox.information(
            self, "Succès", "Configuration TMDB sauvegardée."
        )

    def _refresh_download_settings(self):
        from core.config import get_onefichier_api_key, get_setting

        self._download_dir_input.setText(get_setting("download_dir"))
        self._onefichier_key_input.setText(get_onefichier_api_key())
        self._download_status_label.setText("")

    def _choose_download_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Dossier de téléchargement", str(Path.home())
        )
        if directory:
            self._save_download_setting("download_dir", directory, f"Dossier : {directory}")

    def _reset_download_dir(self):
        self._save_download_setting(
            "download_dir", "", "Dossier : le premier dossier surveillé."
        )

    def _toggle_onefichier_visibility(self):
        hidden = self._onefichier_key_input.echoMode() == QLineEdit.Password
        self._onefichier_key_input.setEchoMode(
            QLineEdit.Normal if hidden else QLineEdit.Password
        )
        self._btn_toggle_1f.setText("Cacher" if hidden else "Voir")

    def _save_onefichier_key(self):
        key = self._onefichier_key_input.text().strip()
        self._save_download_setting(
            "onefichier_api_key",
            key,
            "Clé 1fichier enregistrée." if key else "Clé 1fichier effacée.",
        )

    def _save_download_setting(self, key: str, value: str, message: str):
        from core.config import SETTINGS_FILE, set_setting

        if not set_setting(key, value):
            QMessageBox.critical(
                self,
                "Erreur",
                f"Impossible d'écrire les réglages dans :\n{SETTINGS_FILE}",
            )
            return
        self._refresh_download_settings()
        self._download_status_label.setText(message)

    def _new_language_combo(self) -> QComboBox:
        """Combo de langue pour la lecture.

        Chaque entrée porte toutes les variantes d'une même langue : les conteneurs
        étiquettent leurs pistes tantôt en ISO 639-1 ou 639-2, tantôt en clair.
        """
        combo = QComboBox()
        combo.setStyleSheet(self._lang_combo.styleSheet())
        combo.addItem("Aucune préférence", "")
        for label, codes in (
            ("Français", "fre,fra,fr,french"),
            ("English", "eng,en,english"),
            ("Español", "spa,es,spanish"),
            ("Deutsch", "ger,deu,de,german"),
            ("Italiano", "ita,it,italian"),
            ("Português", "por,pt,portuguese"),
            ("日本語", "jpn,ja,japanese"),
        ):
            combo.addItem(label, codes)
        return combo

    def _language_row(self, text: str, combo: QComboBox) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel(text)
        label.setStyleSheet("color: #eaeaea; font-size: 13px;")
        label.setFixedWidth(95)
        row.addWidget(label)
        row.addWidget(combo)
        row.addStretch()
        return row

    def _refresh_playback_languages(self):
        from core.config import get_audio_language, get_subtitle_language

        for combo, language in (
            (self._audio_lang_combo, get_audio_language()),
            (self._sub_lang_combo, get_subtitle_language()),
        ):
            index = combo.findData(language)
            if index >= 0:
                # Sans blocage, réafficher l'écran réécrirait le réglage qu'il lit.
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
        self._playback_status_label.setText("")

    def _save_audio_language(self):
        self._save_playback_language(
            "audio_language", self._audio_lang_combo, "Piste audio"
        )

    def _save_subtitle_language(self):
        self._save_playback_language(
            "subtitle_language", self._sub_lang_combo, "Sous-titres"
        )

    def _save_playback_language(self, key: str, combo: QComboBox, label: str):
        from core.config import SETTINGS_FILE, set_setting

        language = combo.currentData()
        if not set_setting(key, language):
            QMessageBox.critical(
                self,
                "Erreur",
                f"Impossible d'écrire les réglages dans :\n{SETTINGS_FILE}",
            )
            return

        self._playback_status_label.setText(
            f"{label} : {combo.currentText()} à la prochaine lecture."
            if language
            else f"{label} : aucune préférence, le fichier décide."
        )

    def _start_re_enrich(self):
        self._start_worker(ReEnrichWorker(), "Mise à jour des métadonnées...")

    def _start_auto_scan(self):
        self._start_worker(AutoScanWorker(), "Démarrage de l'indexation...")

    def _start_worker(self, worker, message: str):
        if self.is_busy():
            logger.warning("A library task is already running, ignoring request.")
            return

        self._set_scanning(True, message)

        self._thread = QThread()
        self._worker = worker
        worker.moveToThread(self._thread)

        self._thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)

        # error doit aussi arrêter le thread, sinon il reste vivant indéfiniment.
        worker.finished.connect(self._thread.quit)
        worker.error.connect(self._thread.quit)
        self._thread.finished.connect(worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_worker)

        self._thread.start()

    def _clear_worker(self):
        self._thread = None
        self._worker = None

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def wait_for_worker(self, timeout_ms: int = 5000):
        """Interrompt la tâche de fond et l'attend (appelé à la fermeture).

        Sans cela, fermer l'application pendant un scan détruisait cette vue alors
        que le worker continuait d'émettre des signaux vers elle.
        """
        if self._thread is None or not self._thread.isRunning():
            return
        if self._worker is not None:
            self._worker.request_stop()
        self._thread.quit()
        if not self._thread.wait(timeout_ms):
            logger.warning("Background library task did not stop within the timeout.")

    def _toggle_key_visibility(self):
        if self._api_key_input.echoMode() == QLineEdit.Password:
            self._api_key_input.setEchoMode(QLineEdit.Normal)
            self._btn_toggle_key.setText("Cacher")
        else:
            self._api_key_input.setEchoMode(QLineEdit.Password)
            self._btn_toggle_key.setText("Voir")

    def _on_progress(self, msg, current, total):
        self._status_label.setText(msg)
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
        else:
            self._progress_bar.setRange(0, 0)  # Indéterminé (ex: téléchargement images)

    def _on_finished(self, result):
        if result.get("scanned", 0) > 0:
            msg = f"Terminé : {result['scanned']} scannés, {result['enriched']} enrichis."
        else:
            msg = f"Terminé : {result['enriched']} médias mis à jour, {result['failed']} échoués."
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

    def _reset_library(self):
        if not self._media_service:
            return

        reply = QMessageBox.question(
            self,
            "Réinitialiser la bibliothèque ?",
            "Êtes-vous sûr de vouloir tout supprimer ?\nCette action est irréversible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            if self._media_service.reset_database():
                self._refresh_directories()
                self._refresh_stats()
                self.library_changed.emit()
                QMessageBox.information(
                    self, "Succès", "La bibliothèque a été remise à zéro."
                )
            else:
                QMessageBox.critical(
                    self, "Erreur", "Impossible de réinitialiser la base de données."
                )
