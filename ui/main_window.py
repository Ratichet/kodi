import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import ICON_FILE
from core.services.media_service import MediaService
from ui.styles import get_dark_theme
from ui.views.detail_view import DetailView
from ui.views.downloads_view import DownloadsView
from ui.views.home_view import HomeView
from ui.views.movies_view import MoviesView
from ui.views.player_view import PlayerView
from ui.views.series_view import SeriesView
from ui.views.settings_view import SettingsView

logger = logging.getLogger(__name__)

VIEW_HOME = 0
VIEW_MOVIES = 1
VIEW_SERIES = 2
VIEW_DETAIL = 3
VIEW_PLAYER = 4
VIEW_SETTINGS = 5
VIEW_DOWNLOADS = 6


class MainWindow(QMainWindow):
    # Émis depuis le thread de surveillance ; la connexion automatique devient
    # une connexion différée, le slot s'exécute donc bien dans le thread Qt.
    library_changed_on_disk = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EpiKodi")
        # Posée aussi sur la fenêtre : main() la donne à l'application, mais une
        # fenêtre créée autrement (tests, outils) resterait sans icône.
        self.setWindowIcon(QIcon(str(ICON_FILE)))
        self.resize(1280, 800)
        self.setMinimumSize(960, 580)

        self.setStyleSheet(get_dark_theme())

        self._media_service = MediaService()
        self._player_shut_down = False

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(4)

        logo = QLabel("⬡ EpiKodi")
        logo.setObjectName("logo_label")
        logo.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(logo)
        sidebar_layout.addSpacing(24)

        self._nav_buttons = []
        nav_items = [
            ("🏠  Accueil", VIEW_HOME),
            ("🎬  Films", VIEW_MOVIES),
            ("📺  Séries", VIEW_SERIES),
            ("⬇  Téléchargements", VIEW_DOWNLOADS),
            ("⚙  Paramètres", VIEW_SETTINGS),
        ]

        for text, view_idx in nav_items:
            btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.clicked.connect(lambda checked=False, idx=view_idx: self._navigate(idx))
            sidebar_layout.addWidget(btn)
            self._nav_buttons.append((btn, view_idx))

        sidebar_layout.addStretch()

        # Quitter le lecteur pour une autre vue met la lecture en pause ; sans ce
        # bouton il n'existait aucun moyen d'y revenir.
        self._btn_resume_player = QPushButton()
        self._btn_resume_player.setObjectName("resume_player_button")
        self._btn_resume_player.setVisible(False)
        self._btn_resume_player.setCursor(Qt.PointingHandCursor)
        self._btn_resume_player.clicked.connect(self._return_to_player)
        sidebar_layout.addWidget(self._btn_resume_player)
        sidebar_layout.addSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a3450;")
        sidebar_layout.addWidget(sep)
        sidebar_layout.addSpacing(8)

        btn_open = QPushButton("📂  Ouvrir un fichier")
        btn_open.setObjectName("secondary_button")
        btn_open.clicked.connect(self._open_file)
        sidebar_layout.addWidget(btn_open)
        sidebar_layout.addSpacing(4)

        self._stats_label = QLabel("Bibliothèque vide")
        self._stats_label.setObjectName("subtitle")
        self._stats_label.setAlignment(Qt.AlignCenter)
        self._stats_label.setWordWrap(True)
        sidebar_layout.addWidget(self._stats_label)

        main_layout.addWidget(sidebar)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setObjectName("content_area")
        right_layout.addWidget(self._stack, stretch=1)

        main_layout.addWidget(right_widget, stretch=1)

        self._home_view = HomeView()
        self._home_view.media_clicked.connect(self._on_media_clicked)
        self._home_view.media_play.connect(self._on_media_play)
        self._home_view.watched_toggled.connect(self._on_watched_toggled)

        self._movies_view = MoviesView()
        self._movies_view.media_clicked.connect(self._on_media_clicked)
        self._movies_view.media_play.connect(self._on_media_play)

        self._series_view = SeriesView()
        self._series_view.media_clicked.connect(self._on_media_clicked)
        self._series_view.media_play.connect(self._on_media_play)
        self._series_view.watched_toggled.connect(self._on_watched_toggled)
        self._series_view.delete_requested.connect(self._on_delete_requested)

        self._detail_view = DetailView()
        self._detail_view.play_requested.connect(self._on_media_play)
        self._detail_view.back_requested.connect(self._on_detail_back)
        self._detail_view.delete_requested.connect(self._on_delete_requested)

        self._player_view = PlayerView()
        self._player_view.back_requested.connect(self._on_player_back)
        self._player_view.media_ended.connect(self._on_playback_finished)
        self._player_view.next_episode_requested.connect(
            lambda: self._play_adjacent_episode(1)
        )
        self._player_view.previous_episode_requested.connect(
            lambda: self._play_adjacent_episode(-1)
        )

        self._settings_view = SettingsView()
        self._settings_view.library_changed.connect(self._refresh_all_views)

        self._downloads_view = DownloadsView()
        self._downloads_view.library_changed.connect(self._refresh_all_views)

        # L'ordre d'ajout fixe les index : il doit suivre les constantes VIEW_*.
        self._stack.addWidget(self._home_view)
        self._stack.addWidget(self._movies_view)
        self._stack.addWidget(self._series_view)
        self._stack.addWidget(self._detail_view)
        self._stack.addWidget(self._player_view)
        self._stack.addWidget(self._settings_view)
        self._stack.addWidget(self._downloads_view)

        self._current_view = VIEW_HOME
        self._previous_view = VIEW_HOME
        self._view_before_detail = VIEW_HOME
        self._navigate(VIEW_HOME)
        self._refresh_all_views()

        # Copier une saison entière déclenche une rafale d'événements : on ne
        # rafraîchit qu'une fois le calme revenu.
        self._watch_refresh_timer = QTimer(self)
        self._watch_refresh_timer.setSingleShot(True)
        self._watch_refresh_timer.setInterval(1000)
        self._watch_refresh_timer.timeout.connect(self._refresh_all_views)
        self.library_changed_on_disk.connect(self._watch_refresh_timer.start)
        self._start_watching()

        # closeEvent n'est pas garanti : QApplication.quit(), une fin de session ou
        # un dernier widget fermé autrement sortent de la boucle sans lui. Or laisser
        # libVLC tourner pendant l'arrêt de l'interpréteur fait planter le processus.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown_player)

        logger.info("MainWindow initialized")

    def _shutdown_player(self):
        """Coupe libVLC. Idempotent : closeEvent et aboutToQuit y passent tous deux."""
        if self._player_shut_down:
            return
        self._player_shut_down = True
        try:
            self._player_view.shutdown()
        except Exception as e:
            logger.warning(f"Error while shutting the player down: {e}")

    def _start_watching(self):
        try:
            started = self._media_service.start_watching(
                on_change=self.library_changed_on_disk.emit
            )
        except Exception as e:
            logger.error(f"Could not start the media watcher: {e}")
            return
        if started:
            logger.info("Real-time library watching enabled")
        else:
            logger.info("No media directory to watch yet")

    def _navigate(self, view_index: int):
        if view_index in (VIEW_PLAYER, VIEW_DETAIL):
            return

        # On quitte le lecteur : suspendre la lecture plutôt que la laisser
        # tourner derrière une vue qui ne la montre plus.
        if self._current_view == VIEW_PLAYER:
            self._player_view.suspend()

        self._previous_view = self._current_view
        self._current_view = view_index
        self._stack.setCurrentIndex(view_index)
        self._update_nav_highlight(view_index)
        self._refresh_view(view_index)
        self._update_resume_button()

    def _update_resume_button(self):
        """Affiche « Reprendre » tant qu'un média reste chargé hors du lecteur."""
        show = self._current_view != VIEW_PLAYER and self._player_view.has_media()
        if show:
            title = self._player_view.current_title() or "la lecture"
            if len(title) > 22:
                title = title[:21].rstrip() + "…"
            self._btn_resume_player.setText(f"▶  Reprendre\n{title}")
            self._btn_resume_player.setToolTip(
                f"Revenir au lecteur — {self._player_view.current_title()}"
            )
        self._btn_resume_player.setVisible(show)

    def _return_to_player(self):
        if not self._player_view.has_media():
            self._update_resume_button()
            return

        self._previous_view = self._current_view
        self._current_view = VIEW_PLAYER
        self._stack.setCurrentIndex(VIEW_PLAYER)
        self._update_nav_highlight(-1)
        self._player_view.resume()
        self._update_resume_button()

    def _update_nav_highlight(self, active_index: int):
        for btn, idx in self._nav_buttons:
            btn.setProperty("active", idx == active_index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _refresh_view(self, view_index: int):
        try:
            if view_index == VIEW_HOME:
                self._home_view.refresh(self._media_service)
            elif view_index == VIEW_MOVIES:
                self._movies_view.refresh(self._media_service)
            elif view_index == VIEW_SERIES:
                self._series_view.refresh(self._media_service)
            elif view_index == VIEW_SETTINGS:
                self._settings_view.refresh(self._media_service)
            elif view_index == VIEW_DOWNLOADS:
                self._downloads_view.refresh(self._media_service)
        except Exception as e:
            logger.error(f"Failed to refresh view {view_index}: {e}")

    def _refresh_all_views(self):
        self._refresh_view(self._current_view)
        self._update_stats_label()

    def _update_stats_label(self):
        try:
            stats = self._media_service.get_stats()
            total = stats["total_media"]
            if total == 0:
                self._stats_label.setText(
                    "Bibliothèque vide\nAjoutez des dossiers\ndans les paramètres"
                )
            else:
                self._stats_label.setText(
                    f"{stats['movies']} films · {stats['episodes']} épisodes\n"
                    f"{stats['watched']} vus · {stats['in_progress']} en cours"
                )
        except Exception:
            self._stats_label.setText("Bibliothèque")

    def _on_watched_toggled(self, media_id: int, watched: bool):
        if watched:
            self._media_service.mark_as_watched(media_id)
        else:
            self._media_service.mark_as_unwatched(media_id)
        self._refresh_view(self._current_view)
        self._update_stats_label()

    def _on_delete_requested(self, media_ids: list, label: str):
        what = f"ses {len(media_ids)} fichiers" if len(media_ids) > 1 else "le fichier"
        reply = QMessageBox.question(
            self,
            "Supprimer",
            f"Supprimer définitivement « {label} » ?\n\n"
            f"{what.capitalize()} et les sous-titres associés seront effacés du "
            "disque. Cette action est irréversible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # VLC garde le fichier ouvert, même en pause : Windows refuserait de l'effacer.
        if self._player_view.current_media_id() in media_ids:
            self._player_view.stop()

        failed = self._media_service.delete_media(media_ids)
        if failed:
            QMessageBox.warning(
                self,
                "Suppression incomplète",
                "Ces fichiers n'ont pas pu être supprimés :\n\n" + "\n".join(failed),
            )

        if self._current_view == VIEW_DETAIL:
            self._on_detail_back()
        else:
            self._refresh_view(self._current_view)
        self._update_resume_button()
        self._update_stats_label()

    def _on_playback_finished(self):
        """Fin d'un épisode : enchaîne sur le suivant de la même série."""
        nxt = self._sibling_episode(self._player_view.current_media_id(), 1)
        if nxt is not None:
            self._start_playback(nxt)
            return
        # Rien à enchaîner : décharger le média, sinon on proposerait de
        # « reprendre » un titre déjà terminé.
        self._player_view.stop()
        self._on_player_back()

    def _play_adjacent_episode(self, offset: int):
        """Saut manuel d'un épisode depuis le lecteur (boutons Ép. ⏭ / ⏮, touches N/P)."""
        target = self._sibling_episode(self._player_view.current_media_id(), offset)
        if target is None:
            return
        self._start_playback(target)

    def _start_playback(self, media):
        self._player_view.play_media(media, self._media_service)
        self._update_episode_navigation(media)

    def _update_episode_navigation(self, media):
        self._player_view.set_episode_navigation(
            has_previous=self._sibling_episode(media.id, -1) is not None,
            has_next=self._sibling_episode(media.id, 1) is not None,
        )

    def _sibling_episode(self, media_id: int, offset: int):
        """Épisode voisin dans la série, toutes saisons confondues.

        L'ordre suit (saison, numéro) : passer le dernier épisode d'une saison
        enchaîne donc sur la première de la suivante.
        """
        if media_id is None:
            return None
        media = self._media_service.get_media_by_id(media_id)
        if media is None or media.media_type != "episode" or not media.series_name:
            return None

        episodes = self._media_service.get_series_episodes(media.series_name)
        for index, episode in enumerate(episodes):
            if episode.id == media_id:
                target = index + offset
                return episodes[target] if 0 <= target < len(episodes) else None
        return None

    def _on_media_clicked(self, media_id: int):
        media = self._media_service.get_media_by_id(media_id)
        if not media:
            return

        self._view_before_detail = self._current_view
        self._previous_view = self._current_view
        self._current_view = VIEW_DETAIL
        self._detail_view.show_media(media, self._media_service)
        self._stack.setCurrentIndex(VIEW_DETAIL)
        self._update_nav_highlight(-1)
        self._update_resume_button()

    def _on_media_play(self, media_id: int):
        media = self._media_service.get_media_by_id(media_id)
        if not media:
            return

        # Lancer un autre média depuis une vue de navigation remplace celui qui
        # était en pause dans le lecteur.
        if self._current_view != VIEW_PLAYER:
            self._previous_view = self._current_view
        self._current_view = VIEW_PLAYER

        # Les sous-titres de la vue détail ne valent que pour le média qu'elle
        # affiche : les réutiliser tels quels chargeait ceux du média précédent
        # dès qu'on lançait une lecture depuis une grille.
        subtitle_paths = []
        detail_media = getattr(self._detail_view, "_media", None)
        if detail_media is not None and detail_media.id == media_id:
            subtitle_paths = self._detail_view.get_subtitle_paths()

        self._stack.setCurrentIndex(VIEW_PLAYER)
        self._player_view.play_media(media, self._media_service, subtitle_paths)
        self._update_episode_navigation(media)
        self._update_nav_highlight(-1)
        self._update_resume_button()

    def _on_detail_back(self):
        target = self._view_before_detail
        self._current_view = target
        self._stack.setCurrentIndex(target)
        self._update_nav_highlight(target)
        self._refresh_view(target)
        self._update_resume_button()

    def _on_player_back(self):
        if self._previous_view == VIEW_DETAIL:
            self._current_view = VIEW_DETAIL
            self._stack.setCurrentIndex(VIEW_DETAIL)
            self._update_nav_highlight(-1)
            if self._detail_view._media:
                refreshed = self._media_service.get_media_by_id(
                    self._detail_view._media.id
                )
                if refreshed:
                    self._detail_view.show_media(refreshed, self._media_service)
        else:
            target = (
                self._previous_view
                if self._previous_view not in (VIEW_DETAIL, VIEW_PLAYER)
                else VIEW_HOME
            )
            self._navigate(target)
        # stop() a été appelé par le lecteur : plus rien à reprendre.
        self._update_resume_button()

    def _open_file(self):
        from core.config import SUPPORTED_VIDEO_EXTENSIONS

        ext_filter = (
            "Vidéos ("
            + " ".join(f"*{e}" for e in sorted(SUPPORTED_VIDEO_EXTENSIONS))
            + ")"
        )
        start_dir = str(Path.home() / "Videos")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un fichier", start_dir, ext_filter
        )
        if not file_path:
            return

        media = self._media_service.get_media_by_path(file_path)
        if not media:
            from core.services.scanner import MediaIndexer, MediaParser

            parsed = MediaParser.parse(file_path)
            if parsed:
                media = MediaIndexer().index_media(parsed)
        if not media:
            logger.error(f"Could not open file: {file_path}")
            return

        self._on_media_play(media.id)

    def closeEvent(self, event):
        # La surveillance d'abord : plus aucun signal ne doit viser des widgets
        # en cours de destruction.
        self._watch_refresh_timer.stop()
        try:
            self._media_service.stop_watching()
        except Exception as e:
            logger.warning(f"Error while stopping the media watcher: {e}")

        # Couper VLC avant de détruire les widgets : sinon le rendu vidéo continue
        # d'écrire dans une fenêtre en cours de destruction.
        self._shutdown_player()

        # Les décodages d'affiches en cours renverraient vers des cartes détruites.
        from ui.widgets.artwork import wait_for_pending

        wait_for_pending()

        try:
            self._settings_view.wait_for_worker()
        except Exception as e:
            logger.warning(f"Error while stopping background task: {e}")
        # Un transfert en cours écrit dans un thread : le laisser tourner pendant
        # la destruction des widgets ferait remonter des signaux dans le vide.
        try:
            self._downloads_view.shutdown()
        except Exception as e:
            logger.warning(f"Error while stopping downloads: {e}")
        try:
            self._media_service.close()
        except Exception as e:
            logger.warning(f"Error while closing media service: {e}")
        super().closeEvent(event)
