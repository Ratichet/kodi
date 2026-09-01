import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.power import KeepAwake
from ui.widgets.video_widget import VideoWidget

logger = logging.getLogger(__name__)


class PlayerView(QWidget):
    """Full-screen media player view with subtitle and audio support."""

    back_requested = Signal()
    media_ended = Signal()
    next_episode_requested = Signal()
    previous_episode_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("content_area")
        self._media_service = None
        self._current_media_id = None
        self._current_file_path = None
        self._title = ""
        self._is_user_seeking = False
        self._subtitle_paths = []
        self._keep_awake = KeepAwake()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Video Widget ---
        self.video_widget = VideoWidget()
        # Double clic pour basculer plein écran
        self.video_widget.mouseDoubleClickEvent = self._on_double_click
        layout.addWidget(self.video_widget, stretch=1)

        # --- Controls ---
        self._controls = QWidget()
        self._controls.setObjectName("player_controls")
        self._controls.setFixedHeight(85)
        controls_layout = QVBoxLayout(self._controls)
        controls_layout.setContentsMargins(12, 4, 12, 8)
        controls_layout.setSpacing(4)

        # Seek slider
        self._seek_slider = QSlider(Qt.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self._seek_slider.sliderReleased.connect(self._on_seek_released)
        self._seek_slider.sliderMoved.connect(self._on_seek_moved)
        controls_layout.addWidget(self._seek_slider)

        # Button row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        # Back
        self._btn_back = QPushButton("⏹︎")
        self._btn_back.setObjectName("icon_button")
        self._btn_back.setToolTip("Retour à la bibliothèque")
        self._btn_back.clicked.connect(self._on_back)
        btn_layout.addWidget(self._btn_back)

        # Épisode précédent (séries seulement)
        self._btn_prev_ep = QPushButton("⏮︎ Ép.")
        self._btn_prev_ep.setObjectName("icon_button")
        self._btn_prev_ep.setToolTip("Épisode précédent (P)")
        self._btn_prev_ep.setVisible(False)
        self._btn_prev_ep.clicked.connect(self.previous_episode_requested.emit)
        btn_layout.addWidget(self._btn_prev_ep)

        # Rewind
        btn_rw = QPushButton("⏮︎ 10s")
        btn_rw.setObjectName("icon_button")
        btn_rw.setToolTip("Reculer de 10 secondes")
        btn_rw.clicked.connect(lambda: self._seek_relative(-10000))
        btn_layout.addWidget(btn_rw)

        # Play/Pause
        self._btn_play = QPushButton("▶  Lecture")
        self._btn_play.setObjectName("primary_button")
        self._btn_play.setFixedWidth(120)
        self._btn_play.clicked.connect(self._toggle_play)
        btn_layout.addWidget(self._btn_play)

        # Forward
        btn_ff = QPushButton("10s ⏭︎")
        btn_ff.setObjectName("icon_button")
        btn_ff.setToolTip("Avancer de 10 secondes")
        btn_ff.clicked.connect(lambda: self._seek_relative(10000))
        btn_layout.addWidget(btn_ff)

        # Épisode suivant (séries seulement)
        self._btn_next_ep = QPushButton("Ép. ⏭︎")
        self._btn_next_ep.setObjectName("icon_button")
        self._btn_next_ep.setToolTip("Épisode suivant (N)")
        self._btn_next_ep.setVisible(False)
        self._btn_next_ep.clicked.connect(self.next_episode_requested.emit)
        btn_layout.addWidget(self._btn_next_ep)

        # Time
        self._time_label = QLabel("00:00:00 / 00:00:00")
        self._time_label.setStyleSheet(
            "color: #8892a0; font-family: monospace; font-size: 12px;"
        )
        btn_layout.addWidget(self._time_label)

        btn_layout.addStretch()

        # Title
        self._title_label = QLabel("")
        self._title_label.setStyleSheet(
            "color: #eaeaea; font-size: 13px; font-weight: 600;"
        )
        btn_layout.addWidget(self._title_label)

        btn_layout.addStretch()

        # --- Subtitle controls ---
        self._btn_subs = QPushButton("CC")
        self._btn_subs.setObjectName("icon_button")
        self._btn_subs.setToolTip("Sous-titres")
        self._btn_subs.setFixedWidth(36)
        self._btn_subs.clicked.connect(self._show_subtitle_menu)
        btn_layout.addWidget(self._btn_subs)

        # --- Audio Track controls ---
        self._btn_audio = QPushButton("🔊")
        self._btn_audio.setObjectName("icon_button")
        self._btn_audio.setToolTip("Pistes Audio")
        self._btn_audio.setFixedWidth(36)
        self._btn_audio.clicked.connect(self._show_audio_menu)
        btn_layout.addWidget(self._btn_audio)

        # Volume Slider
        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(70)
        self._vol_slider.setFixedWidth(80)
        self._vol_slider.valueChanged.connect(self._set_volume)
        btn_layout.addWidget(self._vol_slider)

        # --- Fullscreen Button ---
        self._btn_fs = QPushButton("⇱")  # Symbole plein écran
        self._btn_fs.setObjectName("icon_button")
        self._btn_fs.setToolTip("Plein écran (Double-clic ou F)")
        self._btn_fs.setFixedWidth(36)
        self._btn_fs.clicked.connect(self._toggle_fullscreen)
        btn_layout.addWidget(self._btn_fs)

        controls_layout.addLayout(btn_layout)
        layout.addWidget(self._controls)

        # --- Timers Standard ---
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._update_ui)

        self._save_timer = QTimer(self)
        self._save_timer.setInterval(10000)
        self._save_timer.timeout.connect(self._save_progress)

        # --- Timers pour UI Fullscreen ---
        # 1. Timer qui cache l'UI après 4 secondes d'inactivité
        self._inactivity_timer = QTimer(self)
        self._inactivity_timer.setInterval(4000)
        self._inactivity_timer.setSingleShot(True)
        self._inactivity_timer.timeout.connect(self._hide_ui)

        # 2. Timer qui surveille la position de la souris (POLLING)
        # C'est la seule méthode fiable avec VLC
        self._mouse_check_timer = QTimer(self)
        self._mouse_check_timer.setInterval(200)  # Vérifie 5 fois par seconde
        self._mouse_check_timer.timeout.connect(self._check_mouse_activity)
        self._last_mouse_pos = QPoint(0, 0)

        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

    # =================================================================
    # Playback
    # =================================================================

    def set_episode_navigation(self, has_previous: bool, has_next: bool):
        """Affiche les sauts d'épisode. Masqués pour un film."""
        for button, available in (
            (self._btn_prev_ep, has_previous),
            (self._btn_next_ep, has_next),
        ):
            button.setVisible(has_previous or has_next)
            button.setEnabled(available)

    def _new_media(self, file_path: str):
        """Média libVLC portant les préférences de langue de l'utilisateur.

        `audio-language` et `sub-language` sont des options d'entrée : posées sur
        le média, elles prennent effet dès la lecture suivante. Passées à
        `vlc.Instance()`, elles auraient demandé un redémarrage, l'instance libVLC
        étant unique pour tout le processus.
        """
        from core.config import get_audio_language, get_subtitle_language

        media = self.video_widget.instance.media_new(file_path)
        for option, language in (
            ("audio-language", get_audio_language()),
            ("sub-language", get_subtitle_language()),
        ):
            if language:
                media.add_option(f":{option}={language}")
        return media

    def play_media(self, media, media_service=None, subtitle_paths: list = None):
        """Start playing a media item."""
        if media_service:
            self._media_service = media_service

        # Enchaîner sur un autre épisode ne doit pas perdre la position courante :
        # le timer ne la sauvegarde que toutes les 10 s.
        if self._current_media_id is not None and self._current_media_id != media.id:
            try:
                self._save_progress()
            except Exception as e:
                logger.error(f"Failed to save progress before switching media: {e}")

        self._current_media_id = media.id
        self._current_file_path = media.file_path
        self._subtitle_paths = subtitle_paths or []

        if not Path(media.file_path).exists():
            logger.error(f"File not found: {media.file_path}")
            self._title_label.setText("⚠ Fichier introuvable")
            # Rien n'est chargé : ne pas proposer de « reprendre » ce média.
            self._current_media_id = None
            self._current_file_path = None
            self._title = ""
            return

        display = (
            media.display_title
            if hasattr(media, "display_title")
            else (media.title or "Unknown")
        )
        self._title = display
        self._title_label.setText(display)

        # stop() rend la fenêtre à Qt : sans ce rattachement, la lecture suivante
        # s'ouvrirait dans une fenêtre VLC séparée.
        self.video_widget.attach_surface()

        vlc_media = self._new_media(media.file_path)
        self.video_widget.player.set_media(vlc_media)
        self.video_widget.player.play()
        self.video_widget.player.audio_set_volume(self._vol_slider.value())
        self._keep_awake.acquire()

        if media.resume_position and media.resume_position > 0 and not media.is_watched:
            QTimer.singleShot(500, lambda: self._resume_at(media.resume_position))

        if not self._subtitle_paths:
            self._subtitle_paths = self._detect_subtitles(media.file_path)

        self._autoload_subtitle()

        self._btn_play.setText("⏸  Pause")
        self._timer.start()
        self._save_timer.start()
        self._update_subs_button()

        self.setFocus()
        self._show_ui()

    def current_media_id(self) -> int | None:
        return self._current_media_id

    def play_file(self, file_path: str):
        """Play a file directly."""
        self._current_media_id = None
        self._current_file_path = file_path
        self._title = Path(file_path).stem
        self._title_label.setText(self._title)
        self._subtitle_paths = self._detect_subtitles(file_path)

        self.video_widget.attach_surface()
        vlc_media = self._new_media(file_path)
        self.video_widget.player.set_media(vlc_media)
        self.video_widget.player.play()
        self.video_widget.player.audio_set_volume(self._vol_slider.value())
        self._keep_awake.acquire()

        self._autoload_subtitle()

        self._btn_play.setText("⏸  Pause")
        self._timer.start()
        self._update_subs_button()
        self.setFocus()
        self._show_ui()

    def stop(self):
        """Stop playback and save progress."""
        # 1. On arrête tous les timers
        self._timer.stop()
        self._save_timer.stop()
        self._inactivity_timer.stop()
        self._mouse_check_timer.stop()
        self._keep_awake.release()

        # 2. Sauvegarde de la progression
        try:
            self._save_progress()
        except Exception as e:
            logger.error(f"Failed to save progress on stop: {e}")

        # 3. CRITIQUE : On arrête VLC AVANT de toucher à l'interface graphique
        # Cela évite les erreurs "Direct3D" et "hardware acceleration"
        self._stop_vlc()

        # 4. Maintenant on peut modifier l'UI (quitter plein écran, etc.)
        if self.window().isFullScreen():
            self._toggle_fullscreen()

        self.setCursor(Qt.ArrowCursor)
        self._btn_play.setText("▶  Lecture")
        self._current_media_id = None
        self._current_file_path = None
        self._title = ""

    def _stop_vlc(self, timeout: float = 5.0) -> bool:
        """Arrête libVLC sans risquer de figer l'application.

        `libvlc_media_player_stop()` se bloque définitivement s'il est appelé
        depuis le thread graphique pendant que VLC monte sa sortie Direct3D sur la
        fenêtre : la sortie attend la boucle de messages, laquelle attend stop().
        On rend donc la fenêtre à Qt d'abord, on arrête depuis un thread annexe, et
        on continue de faire tourner la boucle de messages pendant l'attente.
        """
        if self.video_widget.is_released():
            # Toucher un lecteur libéré provoque une violation d'accès.
            return True

        self.video_widget.detach_surface()

        done = threading.Event()

        def _worker():
            try:
                self.video_widget.player.stop()
            except Exception as e:
                logger.error(f"VLC stop error: {e}")
            finally:
                done.set()

        threading.Thread(target=_worker, name="epikodi-vlc-stop", daemon=True).start()

        deadline = time.monotonic() + timeout
        while not done.wait(0.02):
            if time.monotonic() > deadline:
                logger.warning(
                    f"VLC did not stop within {timeout}s; carrying on without it."
                )
                return False
            # Indispensable : c'est ce qui permet à la sortie vidéo de se démonter.
            QCoreApplication.processEvents(QEventLoop.ExcludeUserInputEvents, 20)
        return True

    def shutdown(self):
        """Arrêt définitif, à la fermeture. Sans effet si déjà appelé."""
        if self.video_widget.is_released():
            return
        try:
            self.stop()
        except Exception as e:
            logger.error(f"Error while stopping the player: {e}")
        self.video_widget.release()

    # =================================================================
    # Mise en veille pendant qu'on navigue ailleurs
    # =================================================================

    def has_media(self) -> bool:
        """Un média est chargé et peut être repris."""
        return self._current_file_path is not None

    def current_title(self) -> str:
        return self._title

    def suspend(self):
        """Met la lecture en pause quand on quitte le lecteur pour une autre vue.

        Le média reste chargé : `resume()` reprend là où on s'est arrêté. Sans
        cela, le son continuait dans le dos de l'utilisateur.
        """
        if not self.has_media():
            return

        # Quitter le plein écran avant tout : sinon la fenêtre resterait en plein
        # écran sur une vue qui n'est plus le lecteur.
        if self.window().isFullScreen():
            self._toggle_fullscreen()

        try:
            self._save_progress()
        except Exception as e:
            logger.error(f"Failed to save progress on suspend: {e}")

        try:
            if self.video_widget.player.is_playing():
                self.video_widget.player.pause()
        except Exception as e:
            logger.error(f"VLC pause error: {e}")

        # La lecture est en pause : plus rien ne justifie de tenir l'écran éveillé.
        self._keep_awake.release()

        # Inutile d'interroger VLC 5 fois par seconde pour une vue masquée.
        self._timer.stop()
        self._save_timer.stop()
        self._inactivity_timer.stop()
        self._mouse_check_timer.stop()
        self._btn_play.setText("▶  Lecture")
        self.setCursor(Qt.ArrowCursor)

    def resume(self):
        """Reprend la lecture suspendue par `suspend()`."""
        if not self.has_media():
            return
        try:
            self.video_widget.player.play()
            self._btn_play.setText("⏸  Pause")
            self._keep_awake.acquire()
        except Exception as e:
            logger.error(f"VLC resume error: {e}")
        self._timer.start()
        self._save_timer.start()
        self.setFocus()
        self._show_ui()

    def _resume_at(self, position_ms: int):
        if self.video_widget.player.is_playing():
            self.video_widget.player.set_time(position_ms)

    def _toggle_play(self):
        try:
            if self.video_widget.player.is_playing():
                self.video_widget.player.pause()
                self._btn_play.setText("▶  Lecture")
                self._show_ui()  # En pause, on force l'affichage
            else:
                self.video_widget.player.play()
                self._btn_play.setText("⏸  Pause")
                # En lecture, on relance le compte à rebours pour cacher
                if self.window().isFullScreen():
                    self._inactivity_timer.start()
        except Exception as e:
            logger.error(f"Toggle play error: {e}")
        self._sync_keep_awake()

    def _set_volume(self, value):
        try:
            self.video_widget.player.audio_set_volume(value)
        except Exception:
            pass

    def _seek_relative(self, offset_ms: int):
        self._show_ui()
        try:
            current = self.video_widget.player.get_time()
            length = self.video_widget.player.get_length()
            if current is not None and current >= 0 and length and length > 0:
                new_time = max(0, min(current + offset_ms, length))
                self.video_widget.player.set_time(new_time)
        except Exception as e:
            logger.error(f"Seek error: {e}")

    def _toggle_fullscreen(self):
        main_win = self.window()
        sidebar = main_win.findChild(QWidget, "sidebar")

        if main_win.isFullScreen():
            main_win.showNormal()
            self._btn_fs.setText("⇱")

            self._controls.setVisible(True)
            if sidebar:
                sidebar.setVisible(True)
            self.setCursor(Qt.ArrowCursor)

            self._inactivity_timer.stop()
            self._mouse_check_timer.stop()
        else:
            main_win.showFullScreen()
            self._btn_fs.setText("⇲")
            if sidebar:
                sidebar.setVisible(False)

            self._last_mouse_pos = QCursor.pos()
            self._show_ui()
            self._mouse_check_timer.start()

    def _check_mouse_activity(self):
        current_pos = QCursor.pos()
        if (current_pos - self._last_mouse_pos).manhattanLength() > 2:
            self._last_mouse_pos = current_pos
            self._show_ui()

    def _hide_ui(self):
        if self.window().isFullScreen():
            self.setCursor(Qt.BlankCursor)
            self._controls.setVisible(False)

    def _show_ui(self):
        self.setCursor(Qt.ArrowCursor)
        self._controls.setVisible(True)
        if self.window().isFullScreen():
            self._inactivity_timer.start(4000)
        else:
            self._inactivity_timer.stop()

    def _on_double_click(self, event):
        self._toggle_fullscreen()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape and self.window().isFullScreen():
            self._toggle_fullscreen()
        elif key == Qt.Key_F:
            self._toggle_fullscreen()
        elif key == Qt.Key_Space:
            self._toggle_play()
        elif key == Qt.Key_Left:
            self._seek_relative(-10000)
        elif key == Qt.Key_Right:
            self._seek_relative(10000)
        elif key == Qt.Key_N and self._btn_next_ep.isEnabled():
            self._show_ui()
            self.next_episode_requested.emit()
        elif key == Qt.Key_P and self._btn_prev_ep.isEnabled():
            self._show_ui()
            self.previous_episode_requested.emit()
        else:
            super().keyPressEvent(event)

    def _show_audio_menu(self):
        self._show_ui()
        menu = self._create_popup_menu()

        tracks = self.video_widget.player.audio_get_track_description()
        current_track_id = self.video_widget.player.audio_get_track()

        if not tracks:
            action = menu.addAction("Aucune piste audio détectée")
            action.setEnabled(False)
        else:
            for track_id, name in tracks:
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="ignore")

                label = name
                if track_id == current_track_id:
                    label = f"✓ {name}"

                action = menu.addAction(label)
                action.triggered.connect(
                    lambda checked=False, tid=track_id: self._set_audio_track(tid)
                )

        menu.exec(self._btn_audio.mapToGlobal(self._btn_audio.rect().topLeft()))

    def _set_audio_track(self, track_id):
        try:
            self.video_widget.player.audio_set_track(track_id)
            logger.info(f"Audio track changed to {track_id}")
        except Exception as e:
            logger.error(f"Failed to set audio track: {e}")

    def _detect_subtitles(self, file_path: str) -> list:
        if not file_path:
            return []

        from core.config import (
            SUBTITLE_LANGUAGE_SUFFIXES,
            SUPPORTED_SUBTITLE_EXTENSIONS,
        )

        media_path = Path(file_path)
        parent = media_path.parent
        stem = media_path.stem
        found = []

        if not parent.exists():
            return []

        for ext in SUPPORTED_SUBTITLE_EXTENSIONS:
            candidate = parent / f"{stem}{ext}"
            if candidate.exists():
                found.append(str(candidate))
            for lang in SUBTITLE_LANGUAGE_SUFFIXES:
                candidate = parent / f"{stem}.{lang}{ext}"
                if candidate.exists():
                    found.append(str(candidate))

        return sorted(set(found))

    def _autoload_subtitle(self):
        """Charge le sous-titre externe correspondant à la langue préférée.

        Sans préférence — ou sans fichier dans cette langue — le premier trouvé est
        gardé, comme avant. Un fichier externe l'emporte sur la piste intégrée que
        `sub-language` aurait sélectionnée : c'est le choix le plus explicite des deux.
        """
        if not self._subtitle_paths:
            return

        from core.config import get_subtitle_language

        chosen = self._subtitle_paths[0]
        for code in get_subtitle_language().lower().split(","):
            code = code.strip()
            if not code:
                continue
            # Le code doit être un segment entier du nom : « Film.fr.srt » compte,
            # « Frozen.srt » non.
            match = next(
                (
                    path
                    for path in self._subtitle_paths
                    if code in Path(path).stem.lower().split(".")
                ),
                None,
            )
            if match:
                chosen = match
                break

        # 800 ms : VLC rejette un sous-titre tant que le média n'est pas ouvert.
        QTimer.singleShot(800, lambda: self._load_subtitle(chosen))

    def _load_subtitle(self, sub_path: str):
        if not Path(sub_path).exists():
            return
        try:
            self.video_widget.player.video_set_subtitle_file(sub_path)
        except Exception as e:
            logger.error(f"Failed to load subtitle: {e}")

    def _show_subtitle_menu(self):
        self._show_ui()
        menu = self._create_popup_menu()

        action_none = menu.addAction("Désactiver les sous-titres")
        action_none.triggered.connect(self._disable_subtitles)
        menu.addSeparator()

        if self._subtitle_paths:
            for sub_path in self._subtitle_paths:
                name = Path(sub_path).name
                action = menu.addAction(f"📄 {name}")
                action.triggered.connect(
                    lambda checked=False, p=sub_path: self._load_subtitle(p)
                )

        menu.addSeparator()
        action_browse = menu.addAction("📂 Charger un fichier...")
        action_browse.triggered.connect(self._browse_subtitle)

        try:
            spu_count = self.video_widget.player.video_get_spu_count()
            if spu_count and spu_count > 0:
                menu.addSeparator()
                spu_desc = self.video_widget.player.video_get_spu_description()
                if spu_desc:
                    for track_id, track_name in spu_desc:
                        if isinstance(track_name, bytes):
                            track_name = track_name.decode("utf-8", errors="ignore")
                        action = menu.addAction(f"🔤 {track_name}")
                        action.triggered.connect(
                            lambda checked=False, tid=track_id: (
                                self.video_widget.player.video_set_spu(tid)
                            )
                        )
        except Exception:
            pass

        menu.exec(self._btn_subs.mapToGlobal(self._btn_subs.rect().topLeft()))

    def _create_popup_menu(self):
        """Menu stylé, parenté à la fenêtre principale et non au lecteur.

        VLC réclame le `winId()` du widget vidéo, ce qui rend natifs tous ses
        ancêtres — dont cette vue. Un popup parenté ici recevrait donc comme
        parent transitoire une fenêtre qui n'est pas de premier niveau : Qt
        refuse (« must be a top level window ») et le menu peut alors passer
        sous la vidéo en plein écran.
        """
        menu = QMenu(self.window())
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e2a4a;
                color: #eaeaea;
                border: 1px solid #2a3450;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item { padding: 8px 16px; border-radius: 4px; }
            QMenu::item:selected { background-color: #e94560; }
        """)
        return menu

    def _disable_subtitles(self):
        try:
            self.video_widget.player.video_set_spu(-1)
        except Exception:
            pass

    def _browse_subtitle(self):
        start_dir = ""
        if self._current_file_path:
            start_dir = str(Path(self._current_file_path).parent)

        # Parent = la fenêtre principale, pour la même raison que
        # `_create_popup_menu` : la surface native de VLC.
        sub_path, _ = QFileDialog.getOpenFileName(
            self.window(),
            "Charger un fichier de sous-titres",
            start_dir,
            "Sous-titres (*.srt *.sub *.ass *.ssa *.vtt);;Tous (*)",
        )
        if sub_path:
            self._load_subtitle(sub_path)
            if sub_path not in self._subtitle_paths:
                self._subtitle_paths.append(sub_path)
            self._update_subs_button()

    def _update_subs_button(self):
        if self._subtitle_paths:
            self._btn_subs.setStyleSheet("""
                QPushButton {
                    background-color: #e94560; color: white; border: none;
                    border-radius: 4px; font-weight: 700; font-size: 11px;
                }
                QPushButton:hover { background-color: #ff6b81; }
            """)
        else:
            self._btn_subs.setStyleSheet("")

    def _on_seek_pressed(self):
        self._is_user_seeking = True

    def _on_seek_moved(self, value):
        s_time = self._format_time(value)
        length = self.video_widget.player.get_length()
        self._time_label.setText(f"{s_time} / {self._format_time(length)}")

    def _on_seek_released(self):
        try:
            self.video_widget.player.set_time(self._seek_slider.value())
        except Exception as e:
            logger.error(f"Seek release error: {e}")
        self._is_user_seeking = False

    def _sync_keep_awake(self):
        """Aligne l'inhibition de veille sur ce que fait réellement le lecteur.

        Piloté par le timer d'interface, ce rappel régulier repose aussi
        l'inhibition : Windows l'oublie après un verrouillage de session ou un
        changement de mode d'alimentation.
        """
        if self.video_widget.is_released():
            self._keep_awake.release()
            return
        try:
            playing = bool(self.video_widget.player.is_playing())
        except Exception:
            playing = False
        self._keep_awake.set_active(playing)

    def _update_ui(self):
        if self._is_user_seeking or self.video_widget.is_released():
            return

        self._sync_keep_awake()

        try:
            length = self.video_widget.player.get_length()
            time_pos = self.video_widget.player.get_time()
        except Exception:
            return

        if length and length > 0 and time_pos is not None:
            self._seek_slider.setMaximum(length)
            self._seek_slider.setValue(time_pos)
            self._time_label.setText(
                f"{self._format_time(time_pos)} / {self._format_time(length)}"
            )

        try:
            state = self.video_widget.player.get_state()
            if state is not None and state.value == 6:  # Ended
                self._on_playback_ended()
        except Exception:
            pass

    def _save_progress(self):
        if not self._media_service or not self._current_media_id:
            return
        if self.video_widget.is_released():
            return
        try:
            time_pos = self.video_widget.player.get_time()
            length = self.video_widget.player.get_length()
            if time_pos and time_pos > 0 and length and length > 0:
                self._media_service.update_progress(
                    self._current_media_id, time_pos, length
                )
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")

    def _on_playback_ended(self):
        self._save_progress()
        self._timer.stop()
        self._save_timer.stop()
        self._inactivity_timer.stop()
        self._mouse_check_timer.stop()
        self._keep_awake.release()
        self._btn_play.setText("▶  Lecture")

        if self.window().isFullScreen():
            self._toggle_fullscreen()

        self.media_ended.emit()  # ← notify MainWindow to advance queue

    def _on_back(self):
        self.stop()
        self.back_requested.emit()

    @staticmethod
    def _format_time(ms: int) -> str:
        if not ms or ms < 0:
            return "00:00:00"
        seconds = (ms // 1000) % 60
        minutes = (ms // 60000) % 60
        hours = ms // 3600000
        return f"{hours:02}:{minutes:02}:{seconds:02}"
