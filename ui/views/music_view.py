
import logging
import random
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QSlider,
    QFrame,
    QLineEdit,
    QInputDialog,
    QMessageBox,
    QMenu,
    QAbstractItemView,
    QHeaderView,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QPixmap,
    QColor,
    QFont,
    QPainter,
    QLinearGradient,
    QBrush,
    QAction,
)

import vlc

from core.models import Media
from core.services.media_service import MediaService
from ui.styles import (
    ACCENT,
    BG_DARK,
    BG_MID,
    BG_PANEL,
    BG_ROW,
    BG_ROW_ALT,
    BG_ROW_SEL,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_MUTED,
)

logger = logging.getLogger(__name__)

def _fmt_duration(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _make_art_placeholder(size: int, text: str = "♫") -> QPixmap:
    px = QPixmap(size, size)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    h = abs(hash(text)) % 360
    c1 = QColor.fromHsv(h, 110, 70)
    c2 = QColor.fromHsv((h + 50) % 360, 90, 45)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, c1)
    grad.setColorAt(1, c2)
    painter.fillRect(0, 0, size, size, QBrush(grad))
    painter.setPen(QColor(255, 255, 255, 180))
    font = QFont("Segoe UI", size // 3, QFont.Bold)
    painter.setFont(font)
    painter.drawText(px.rect(), Qt.AlignCenter, text)
    painter.end()
    return px


class AudioPlayerBar(QFrame):

    track_changed = Signal(int)
    queue_exhausted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("audio_player_bar")
        self.setFixedHeight(86)
        self.setStyleSheet(f"""
            #audio_player_bar {{
                background-color: {BG_DARK};
                border-top: 1px solid #2a3450;
            }}
        """)

        self._vlc_instance = vlc.Instance("--no-video")
        self._player = self._vlc_instance.media_player_new()
        self._media_list: List[Media] = []
        self._current_index: int = -1
        self._shuffle: bool = False
        self._repeat: bool = False 
        self._is_user_seeking = False
        self._media_service: Optional[MediaService] = None

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(12)

        self._art_label = QLabel()
        self._art_label.setFixedSize(60, 60)
        self._art_label.setScaledContents(True)
        self._art_label.setPixmap(_make_art_placeholder(60))
        self._art_label.setStyleSheet("border-radius: 4px;")
        root.addWidget(self._art_label)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self._title_lbl = QLabel("—")
        self._title_lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-weight: 700; font-size: 13px;"
        )
        self._artist_lbl = QLabel("")
        self._artist_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        info_col.addStretch()
        info_col.addWidget(self._title_lbl)
        info_col.addWidget(self._artist_lbl)
        info_col.addStretch()
        root.addLayout(info_col, stretch=0)
        root.addSpacing(8)

        centre = QVBoxLayout()
        centre.setSpacing(4)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)
        ctrl_row.setAlignment(Qt.AlignCenter)

        def _icon_btn(symbol: str, size: int = 30, accent: bool = False) -> QPushButton:
            b = QPushButton(symbol)
            b.setFixedSize(size, size)
            bg = ACCENT if accent else BG_ROW
            hover = "#ff6b81" if accent else BG_ROW_SEL
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg};
                    color: {TEXT_PRIMARY};
                    border-radius: {size // 2}px;
                    font-size: {size // 2 - 2}px;
                    border: none;
                }}
                QPushButton:hover {{ background-color: {hover}; }}
                QPushButton:pressed {{ background-color: #cc3a52; }}
            """)
            return b

        self._btn_shuffle = _icon_btn("⇀", 26)
        self._btn_prev = _icon_btn("⏮", 30)
        self._btn_play = _icon_btn("▶", 38, accent=True)
        self._btn_next = _icon_btn("⏭", 30)
        self._btn_repeat = _icon_btn("↺", 26)

        self._btn_shuffle.setToolTip("Lecture aléatoire")
        self._btn_prev.setToolTip("Précédent")
        self._btn_play.setToolTip("Lecture / Pause")
        self._btn_next.setToolTip("Suivant")
        self._btn_repeat.setToolTip("Répéter")

        for b in (
            self._btn_shuffle,
            self._btn_prev,
            self._btn_play,
            self._btn_next,
            self._btn_repeat,
        ):
            ctrl_row.addWidget(b)

        centre.addLayout(ctrl_row)

        seek_row = QHBoxLayout()
        seek_row.setSpacing(6)
        self._pos_lbl = QLabel("0:00")
        self._pos_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; min-width: 36px;"
        )
        self._pos_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._seek_bar = QSlider(Qt.Horizontal)
        self._seek_bar.setRange(0, 1000)
        self._seek_bar.setValue(0)
        self._seek_bar.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: #2a3450; height: 4px; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT}; height: 4px; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: white; width: 10px; height: 10px;
                margin: -3px 0; border-radius: 5px;
            }}
        """)
        self._dur_lbl = QLabel("0:00")
        self._dur_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; min-width: 36px;"
        )
        seek_row.addWidget(self._pos_lbl)
        seek_row.addWidget(self._seek_bar, stretch=1)
        seek_row.addWidget(self._dur_lbl)
        centre.addLayout(seek_row)
        root.addLayout(centre, stretch=1)

        vol_col = QVBoxLayout()
        vol_col.setAlignment(Qt.AlignCenter)
        vol_lbl = QLabel("🔊")
        vol_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(80)
        self._vol_slider.setFixedWidth(90)
        self._vol_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #2a3450; height: 3px; border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #4a6aaa; height: 3px; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: white; width: 10px; height: 10px;
                margin: -4px 0; border-radius: 5px;
            }
        """)
        vol_col.addWidget(vol_lbl, alignment=Qt.AlignCenter)
        vol_col.addWidget(self._vol_slider)
        root.addLayout(vol_col)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

        self._btn_play.clicked.connect(self._toggle_play)
        self._btn_prev.clicked.connect(self.prev_track)
        self._btn_next.clicked.connect(self.next_track)
        self._btn_shuffle.clicked.connect(self._toggle_shuffle)
        self._btn_repeat.clicked.connect(self._toggle_repeat)
        self._seek_bar.sliderPressed.connect(
            lambda: setattr(self, "_is_user_seeking", True)
        )
        self._seek_bar.sliderReleased.connect(self._on_seek_released)
        self._vol_slider.valueChanged.connect(self._on_volume_changed)

        self._player.audio_set_volume(80)

    def set_media_service(self, svc: MediaService):
        self._media_service = svc

    def load_queue(self, tracks: List[Media], start_index: int = 0):
        self._media_list = tracks
        self._play_index(start_index)

    def play_single(self, media: Media):
        self._media_list = [media]
        self._play_index(0)

    def stop(self):
        self._player.stop()
        self._btn_play.setText("▶")

    def is_playing(self) -> bool:
        return self._player.is_playing()

    @property
    def current_track(self) -> Optional[Media]:
        if 0 <= self._current_index < len(self._media_list):
            return self._media_list[self._current_index]
        return None

    def _play_index(self, index: int):
        if not self._media_list:
            return
        index = max(0, min(index, len(self._media_list) - 1))
        self._current_index = index
        media = self._media_list[index]
        self._load_media(media)
        self.track_changed.emit(media.id)

    def _load_media(self, media: Media):
        vlc_media = self._vlc_instance.media_new(media.file_path)
        self._player.set_media(vlc_media)
        self._player.play()
        self._btn_play.setText("⏸")
        self._title_lbl.setText(media.title or Path(media.file_path).stem)
        self._artist_lbl.setText(
            " · ".join(filter(None, [media.artist, media.album])) or ""
        )
        if media.album_art_path and Path(media.album_art_path).exists():
            px = (
                QPixmap(media.album_art_path)
                .scaled(60, 60, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                .copy(0, 0, 60, 60)
            )
        else:
            px = _make_art_placeholder(60, (media.artist or media.album or "♫")[:2])
        self._art_label.setPixmap(px)

    def _toggle_play(self):
        state = self._player.get_state()
        if state == vlc.State.Playing:
            self._player.pause()
            self._btn_play.setText("▶")
        elif state in (vlc.State.Paused, vlc.State.Stopped, vlc.State.Ended):
            if state == vlc.State.Stopped and self.current_track:
                self._load_media(self.current_track)
            else:
                self._player.play()
            self._btn_play.setText("⏸")
        elif not self._media_list and self._current_index == -1:
            return

    def prev_track(self):
        if not self._media_list:
            return
        pos = self._player.get_time()
        if pos > 3000:
            self._player.set_time(0)
        else:
            new_idx = (self._current_index - 1) % len(self._media_list)
            self._play_index(new_idx)

    def next_track(self):
        if not self._media_list:
            return
        if self._shuffle:
            indices = list(range(len(self._media_list)))
            if self._current_index in indices:
                indices.remove(self._current_index)
            if indices:
                self._play_index(random.choice(indices))
            else:
                self.stop()
                self.queue_exhausted.emit()
        else:
            new_idx = self._current_index + 1
            if new_idx >= len(self._media_list):
                if self._repeat:
                    self._play_index(0)
                else:
                    self.stop()
                    self.queue_exhausted.emit()
            else:
                self._play_index(new_idx)

    def _toggle_shuffle(self):
        self._shuffle = not self._shuffle
        self._btn_shuffle.setStyleSheet(
            self._btn_shuffle.styleSheet().replace(
                ACCENT if not self._shuffle else BG_ROW,
                BG_ROW if not self._shuffle else ACCENT,
            )
        )
        self._refresh_toggle_btn(self._btn_shuffle, self._shuffle)

    def _toggle_repeat(self):
        self._repeat = not self._repeat
        self._refresh_toggle_btn(self._btn_repeat, self._repeat)

    def _refresh_toggle_btn(self, btn: QPushButton, active: bool):
        bg = ACCENT if active else BG_ROW
        hover = "#ff6b81" if active else BG_ROW_SEL
        size = btn.width()
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {TEXT_PRIMARY};
                border-radius: {size // 2}px;
                font-size: {size // 2 - 2}px;
                border: none;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
        """)

    def _on_tick(self):
        try:
            state = self._player.get_state()
            if state == vlc.State.Ended:
                self._btn_play.setText("▶")
                if self._media_service and self.current_track:
                    dur = self._player.get_length()
                    self._media_service.update_progress(self.current_track.id, dur, dur)
                self.next_track()
                return

            if self._is_user_seeking:
                return

            length = self._player.get_length()
            position = self._player.get_time()
            if length > 0:
                self._seek_bar.blockSignals(True)
                self._seek_bar.setValue(int(position / length * 1000))
                self._seek_bar.blockSignals(False)
                self._pos_lbl.setText(_fmt_duration(position // 1000))
                self._dur_lbl.setText(_fmt_duration(length // 1000))
                if self._media_service and self.current_track and position % 5000 < 600:
                    self._media_service.update_progress(
                        self.current_track.id, position, length
                    )
        except Exception:
            pass

    def _on_seek_released(self):
        self._is_user_seeking = False
        length = self._player.get_length()
        if length > 0:
            target = int(self._seek_bar.value() / 1000 * length)
            self._player.set_time(target)

    def _on_volume_changed(self, value: int):
        self._player.audio_set_volume(value)

class PlaylistPanel(QWidget):

    selection_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(210)
        self.setStyleSheet(f"background-color: {BG_PANEL};")
        self._media_service: Optional[MediaService] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(6)

        title = QLabel("Bibliothèque")
        title.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        )
        layout.addWidget(title)

        self._all_btn = QPushButton("♫  Tous les morceaux")
        self._all_btn.setStyleSheet(self._btn_style(active=True))
        self._all_btn.clicked.connect(lambda: self._select_all())
        layout.addWidget(self._all_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a3450; margin: 4px 0;")
        layout.addWidget(sep)

        pl_header = QHBoxLayout()
        pl_label = QLabel("PLAYLISTS")
        pl_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        )
        pl_header.addWidget(pl_label)
        pl_header.addStretch()
        btn_new = QPushButton("+")
        btn_new.setFixedSize(20, 20)
        btn_new.setToolTip("Nouvelle playlist")
        btn_new.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_SECONDARY};
                border: 1px solid #2a3450; border-radius: 10px; font-size: 14px;
            }}
            QPushButton:hover {{ color: {ACCENT}; border-color: {ACCENT}; }}
        """)
        btn_new.clicked.connect(self._create_playlist)
        pl_header.addWidget(btn_new)
        layout.addLayout(pl_header)

        self._pl_list = QListWidget()
        self._pl_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent; border: none;
                color: {TEXT_PRIMARY}; font-size: 13px;
            }}
            QListWidget::item {{
                padding: 6px 8px; border-radius: 4px;
            }}
            QListWidget::item:hover {{ background: {BG_ROW_SEL}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
        """)
        self._pl_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._pl_list.customContextMenuRequested.connect(self._playlist_context_menu)
        self._pl_list.currentItemChanged.connect(self._on_playlist_selected)
        layout.addWidget(self._pl_list, stretch=1)

    def refresh(self, media_service: MediaService):
        self._media_service = media_service
        self._pl_list.clear()
        playlists = media_service.get_playlists()
        for pl in playlists:
            item = QListWidgetItem(f"  {pl.name}  ({pl.track_count})")
            item.setData(Qt.UserRole, pl.id)
            self._pl_list.addItem(item)

    def _select_all(self):
        self._pl_list.clearSelection()
        self._all_btn.setStyleSheet(self._btn_style(active=True))
        self.selection_changed.emit(None)

    def _on_playlist_selected(self, current, previous):
        if current:
            self._all_btn.setStyleSheet(self._btn_style(active=False))
            pl_id = current.data(Qt.UserRole)
            if self._media_service:
                pl = self._media_service.get_playlist(pl_id)
                self.selection_changed.emit(pl)

    def _create_playlist(self):
        if not self._media_service:
            return
        name, ok = QInputDialog.getText(self, "Nouvelle playlist", "Nom :")
        if ok and name.strip():
            self._media_service.create_playlist(name.strip())
            self.refresh(self._media_service)

    def _playlist_context_menu(self, pos):
        item = self._pl_list.itemAt(pos)
        if not item:
            return
        pl_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {BG_MID}; color: {TEXT_PRIMARY}; border: 1px solid #2a3450; }}
            QMenu::item:selected {{ background: {BG_ROW_SEL}; }}
        """)
        rename_act = QAction("Renommer", self)
        delete_act = QAction("Supprimer", self)
        menu.addAction(rename_act)
        menu.addAction(delete_act)
        action = menu.exec(self._pl_list.mapToGlobal(pos))
        if action == rename_act:
            name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :")
            if ok and name.strip():
                self._media_service.rename_playlist(pl_id, name.strip())
                self.refresh(self._media_service)
        elif action == delete_act:
            if (
                QMessageBox.question(
                    self,
                    "Supprimer",
                    "Supprimer cette playlist ?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                == QMessageBox.Yes
            ):
                self._media_service.delete_playlist(pl_id)
                self.refresh(self._media_service)
                self._select_all()

    @staticmethod
    def _btn_style(active: bool) -> str:
        bg = BG_ROW_SEL if active else "transparent"
        return f"""
            QPushButton {{
                background: {bg};
                color: {TEXT_PRIMARY};
                border: none;
                border-radius: 4px;
                text-align: left;
                padding: 6px 8px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background: {BG_ROW_SEL}; }}
        """

COL_NUM = 0
COL_TITLE = 1
COL_ARTIST = 2
COL_ALBUM = 3
COL_DUR = 4

HEADERS = ["#", "Titre", "Artiste", "Album", "Durée"]

class TrackTable(QTableWidget):

    play_requested = Signal(int)
    add_to_playlist = Signal(int)

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(HEADERS)
        self.horizontalHeader().setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(
            COL_ARTIST, QHeaderView.ResizeToContents
        )
        self.horizontalHeader().setSectionResizeMode(
            COL_ALBUM, QHeaderView.ResizeToContents
        )
        self.horizontalHeader().setSectionResizeMode(
            COL_DUR, QHeaderView.ResizeToContents
        )
        self.setColumnWidth(COL_NUM, 36)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.doubleClicked.connect(lambda idx: self.play_requested.emit(idx.row()))
        self.setStyleSheet(f"""
            QTableWidget {{
                background-color: {BG_MID};
                gridline-color: #1e2a40;
                color: {TEXT_PRIMARY};
                border: none;
                font-size: 13px;
            }}
            QTableWidget::item {{
                padding: 4px 8px;
                border-bottom: 1px solid #1e2a40;
            }}
            QTableWidget::item:selected {{
                background: {BG_ROW_SEL};
                color: white;
            }}
            QTableWidget::item:alternate {{
                background: {BG_ROW_ALT};
            }}
            QHeaderView::section {{
                background-color: {BG_DARK};
                color: {TEXT_MUTED};
                padding: 6px 8px;
                border: none;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
        """)
        self._tracks: List[Media] = []

    def load_tracks(self, tracks: List[Media]):
        self._tracks = tracks
        self.setSortingEnabled(False)
        self.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            num = str(track.track_number) if track.track_number else str(row + 1)
            self._set_cell(row, COL_NUM, num, align=Qt.AlignCenter, color=TEXT_MUTED)
            self._set_cell(row, COL_TITLE, track.title or Path(track.file_path).stem)
            self._set_cell(row, COL_ARTIST, track.artist or "", color=TEXT_SECONDARY)
            self._set_cell(row, COL_ALBUM, track.album or "", color=TEXT_SECONDARY)
            self._set_cell(
                row,
                COL_DUR,
                _fmt_duration(track.duration_sec or 0),
                align=Qt.AlignRight | Qt.AlignVCenter,
                color=TEXT_MUTED,
            )
            self.item(row, COL_TITLE).setData(Qt.UserRole, track.id)
        self.setSortingEnabled(True)

    def track_at_row(self, row: int) -> Optional[Media]:

        try:
            mid = self.item(row, COL_TITLE).data(Qt.UserRole)
            return next((t for t in self._tracks if t.id == mid), None)
        except Exception:
            return None

    def tracks_in_visual_order(self) -> List[Media]:
        result = []
        for row in range(self.rowCount()):
            t = self.track_at_row(row)
            if t:
                result.append(t)
        return result

    def highlight_track(self, media_id: int):
        for row in range(self.rowCount()):
            item = self.item(row, COL_TITLE)
            if item and item.data(Qt.UserRole) == media_id:
                for col in range(self.columnCount()):
                    cell = self.item(row, col)
                    if cell:
                        cell.setForeground(QColor(ACCENT))
            else:
                for col in range(self.columnCount()):
                    cell = self.item(row, col)
                    if cell:
                        if col in (COL_ARTIST, COL_ALBUM, COL_NUM, COL_DUR):
                            cell.setForeground(
                                QColor(TEXT_MUTED if col == COL_DUR else TEXT_SECONDARY)
                            )
                        else:
                            cell.setForeground(QColor(TEXT_PRIMARY))

    def _set_cell(
        self, row, col, text, align=Qt.AlignLeft | Qt.AlignVCenter, color=None
    ):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align)
        if color:
            item.setForeground(QColor(color))
        self.setItem(row, col, item)

    def _on_context_menu(self, pos):
        row = self.rowAt(pos.y())
        if row < 0:
            return
        media = self.track_at_row(row)
        if not media:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {BG_MID}; color: {TEXT_PRIMARY}; border: 1px solid #2a3450; }}
            QMenu::item:selected {{ background: {BG_ROW_SEL}; }}
        """)
        play_act = QAction(f"▶  Lire « {media.title or '?'} »", self)
        add_act = QAction("➕  Ajouter à une playlist…", self)
        menu.addAction(play_act)
        menu.addAction(add_act)
        action = menu.exec(self.mapToGlobal(pos))
        if action == play_act:
            self.play_requested.emit(row)
        elif action == add_act:
            self.add_to_playlist.emit(media.id)



class MusicView(QWidget):

    media_clicked = Signal(int)
    media_play = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("content_area")
        self._media_service: Optional[MediaService] = None
        self._player_bar: Optional[AudioPlayerBar] = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setStyleSheet(f"background-color: {BG_MID};")
        top_bar.setFixedHeight(54)
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 0, 16, 0)
        top_bar_layout.setSpacing(12)

        self._page_title = QLabel("Musique")
        self._page_title.setObjectName("page_title")
        top_bar_layout.addWidget(self._page_title)
        top_bar_layout.addStretch()

        self._search_bar = QLineEdit()
        self._search_bar.setObjectName("search_bar")
        self._search_bar.setPlaceholderText("Rechercher…")
        self._search_bar.setFixedWidth(240)
        self._search_bar.setClearButtonEnabled(True)
        top_bar_layout.addWidget(self._search_bar)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        top_bar_layout.addWidget(self._count_label)
        root_layout.addWidget(top_bar)

        self._track_table = TrackTable()
        self._track_table.play_requested.connect(self._on_play_row)
        root_layout.addWidget(self._track_table, stretch=1)
        # NOTE: AudioPlayerBar is NOT added here — it lives in MainWindow

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(280)
        self._search_timer.timeout.connect(self._apply_search)
        self._search_bar.textChanged.connect(lambda: self._search_timer.start())

        self._all_tracks: List[Media] = []
        self._visible_tracks: List[Media] = []

    def set_player_bar(self, bar: AudioPlayerBar):
        """Called by MainWindow once after construction."""
        self._player_bar = bar
        bar.track_changed.connect(self._on_track_changed)

    def refresh(self, media_service: MediaService):
        """Refresh library data WITHOUT touching the player bar."""
        self._media_service = media_service
        self._load_all_tracks()

    def _load_all_tracks(self):
        self._all_tracks = (
            self._media_service.get_music() if self._media_service else []
        )
        self._apply_search()
        self._page_title.setText("Musique")

    def _on_track_changed(self, media_id: int):
        self._track_table.highlight_track(media_id)
        q = self._search_bar.text().strip().lower()
        if not q:
            self._visible_tracks = list(self._all_tracks)
        else:
            self._visible_tracks = [
                t
                for t in self._all_tracks
                if q in (t.title or "").lower()
                or q in (t.artist or "").lower()
                or q in (t.album or "").lower()
            ]
        self._track_table.load_tracks(self._visible_tracks)
        n = len(self._visible_tracks)
        self._count_label.setText(f"{n} morceau{'x' if n > 1 else ''}")
        if self._player_bar and self._player_bar.current_track:
            self._track_table.highlight_track(self._player_bar.current_track.id)

    def _on_play_row(self, row: int):
        if not self._visible_tracks or not self._player_bar:
            return
        track = self._track_table.track_at_row(row)
        if not track:
            return
        visual_queue = self._track_table.tracks_in_visual_order()
        try:
            idx = visual_queue.index(track)
        except ValueError:
            idx = 0
        self._player_bar.load_queue(visual_queue, start_index=idx)

    def _on_track_changed(self, media_id: int):
        self._track_table.highlight_track(media_id)

    def _apply_search(self):
        q = self._search_bar.text().strip().lower()
        if not q:
            self._visible_tracks = list(self._all_tracks)
        else:
            self._visible_tracks = [
                t
                for t in self._all_tracks
                if q in (t.title or "").lower()
                or q in (t.artist or "").lower()
                or q in (t.album or "").lower()
            ]
        self._track_table.load_tracks(self._visible_tracks)
        n = len(self._visible_tracks)
        self._count_label.setText(f"{n} morceau{'x' if n > 1 else ''}")
        if self._player_bar and self._player_bar.current_track:
            self._track_table.highlight_track(self._player_bar.current_track.id)
