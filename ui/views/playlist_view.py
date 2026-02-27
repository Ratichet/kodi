"""
PlaylistView – Gestion de playlists mixtes (audio + vidéo).

Layout :
  ┌───────────────┬────────────────────────────────────────────────┐
  │ Mes playlists │  En-tête playlist  (nom · stats · ▶ Tout lire) │
  │               ├────────────────────────────────────────────────┤
  │  [+ Nouvelle] │  Table des items   (# · type · titre · durée · ✕)│
  │               │                                                │
  │               │  [+ Ajouter des médias…]                      │
  └───────────────┴────────────────────────────────────────────────┘
"""

import logging
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
    QFrame,
    QLineEdit,
    QInputDialog,
    QMessageBox,
    QMenu,
    QAbstractItemView,
    QHeaderView,
    QDialog,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QAction

from core.services.media_service import MediaService
from core.models import Media
from ui.styles import (
    ACCENT,
    BG_DARK,
    BG_MID,
    BG_PANEL,
    BG_ROW,
    BG_ROW_SEL,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_MUTED,
)

# short aliases used throughout this file
TEXT_PRI = TEXT_PRIMARY
TEXT_SEC = TEXT_SECONDARY
TEXT_MUT = TEXT_MUTED

logger = logging.getLogger(__name__)

TYPE_ICONS = {
    "music": "🎵",
    "movie": "🎬",
    "episode": "📺",
}


def _fmt_dur(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _btn(text: str, accent: bool = False, small: bool = False) -> QPushButton:
    b = QPushButton(text)
    if accent:
        b.setObjectName("primary_button")
    else:
        b.setObjectName("secondary_button")
    if small:
        b.setFixedHeight(28)
        b.setStyleSheet(b.styleSheet() + "font-size: 12px; padding: 2px 10px;")
    return b


# ── Media search dialog ────────────────────────────────────────────────────────


class AddMediaDialog(QDialog):
    """
    Modal dialog to search the library and pick items to add to a playlist.
    Returns the list of selected Media objects via .selected_media.
    """

    def __init__(self, media_service: MediaService, exclude_ids: set, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajouter des médias")
        self.setMinimumSize(620, 480)
        self.selected_media: List[Media] = []
        self._media_service = media_service
        self._exclude_ids = exclude_ids
        self._all_results: List[Media] = []

        self.setStyleSheet(f"""
            QDialog {{ background: {BG_MID}; color: {TEXT_PRI}; }}
            QLabel {{ color: {TEXT_PRI}; }}
            QLineEdit {{
                background: {BG_DARK}; color: {TEXT_PRI};
                border: 1px solid #2a3450; border-radius: 4px; padding: 6px 10px;
            }}
            QTableWidget {{
                background: {BG_DARK}; color: {TEXT_PRI};
                border: none; gridline-color: #1e2a40;
            }}
            QTableWidget::item {{ padding: 4px 8px; }}
            QTableWidget::item:selected {{ background: {BG_ROW_SEL}; }}
            QHeaderView::section {{
                background: {BG_PANEL}; color: {TEXT_MUT};
                padding: 5px 8px; border: none;
                font-size: 11px; font-weight: 700; letter-spacing: 1px;
            }}
            QDialogButtonBox QPushButton {{
                background: {BG_ROW}; color: {TEXT_PRI};
                border: none; border-radius: 4px; padding: 6px 18px;
            }}
            QDialogButtonBox QPushButton:hover {{ background: {BG_ROW_SEL}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # search bar
        hint = QLabel("Recherchez un film, une série, un morceau…")
        hint.setStyleSheet(f"color: {TEXT_MUT}; font-size: 12px;")
        layout.addWidget(hint)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Titre, artiste, album…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        layout.addWidget(self._search)

        # results table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["", "Titre", "Info", "Durée"])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self._table.setColumnWidth(0, 30)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self._table, stretch=1)

        self._count_lbl = QLabel("Tapez pour rechercher")
        self._count_lbl.setStyleSheet(f"color: {TEXT_MUT}; font-size: 11px;")
        layout.addWidget(self._count_lbl)

        # buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Ajouter la sélection")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # load all on open
        self._load_results(media_service.get_all_media(limit=200))

    def _on_search(self, text: str):
        q = text.strip()
        if not q:
            results = self._media_service.get_all_media(limit=200)
        else:
            results = self._media_service.search_media(q, limit=100)
        self._load_results(results)

    def _load_results(self, media_list: List[Media]):
        self._all_results = [m for m in media_list if m.id not in self._exclude_ids]
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._all_results))
        for row, m in enumerate(self._all_results):
            icon = TYPE_ICONS.get(m.media_type, "?")
            self._set_cell(row, 0, icon, align=Qt.AlignCenter)
            self._set_cell(row, 1, m.title or Path(m.file_path).stem)
            # info col
            if m.media_type == "music":
                info = " · ".join(filter(None, [m.artist, m.album])) or ""
            elif m.media_type == "episode":
                info = m.series_name or ""
            else:
                info = str(m.year) if m.year else ""
            self._set_cell(row, 2, info, color=TEXT_SEC)
            self._set_cell(
                row,
                3,
                _fmt_dur(m.duration_sec or 0),
                align=Qt.AlignRight | Qt.AlignVCenter,
                color=TEXT_MUT,
            )
            self._table.item(row, 1).setData(Qt.UserRole, m.id)
        self._table.setSortingEnabled(True)
        n = len(self._all_results)
        self._count_lbl.setText(f"{n} résultat{'s' if n > 1 else ''}")

    def _on_accept(self):
        selected_rows = {idx.row() for idx in self._table.selectedIndexes()}
        id_map = {m.id: m for m in self._all_results}
        self.selected_media = []
        for row in sorted(selected_rows):
            try:
                mid = self._table.item(row, 1).data(Qt.UserRole)
                if mid in id_map:
                    self.selected_media.append(id_map[mid])
            except Exception:
                pass
        self.accept()

    def _set_cell(
        self, row, col, text, align=Qt.AlignLeft | Qt.AlignVCenter, color=None
    ):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align)
        if color:
            item.setForeground(QColor(color))
        self._table.setItem(row, col, item)


# ── Playlist sidebar ───────────────────────────────────────────────────────────


class PlaylistSidebar(QWidget):
    """Left panel listing all playlists."""

    playlist_selected = Signal(int)  # playlist_id
    playlist_created = Signal()
    selection_cleared = Signal()  # no playlist selected (e.g. after last one deleted)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet(f"background: {BG_PANEL};")
        self._media_service: Optional[MediaService] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(8)

        hdr = QHBoxLayout()
        lbl = QLabel("MES PLAYLISTS")
        lbl.setStyleSheet(
            f"color: {TEXT_MUT}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        )
        hdr.addWidget(lbl)
        hdr.addStretch()
        btn_new = QPushButton("+  Nouvelle")
        btn_new.setFixedHeight(24)
        btn_new.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: white;
                border: none; border-radius: 4px; font-size: 11px; padding: 0 8px;
            }}
            QPushButton:hover {{ background: #ff6b81; }}
        """)
        btn_new.clicked.connect(self._create_playlist)
        hdr.addWidget(btn_new)
        layout.addLayout(hdr)

        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background: transparent; border: none;
                color: {TEXT_PRI}; font-size: 13px;
            }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 4px; }}
            QListWidget::item:hover {{ background: {BG_ROW_SEL}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
        """)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._ctx_menu)
        self._list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, stretch=1)

        self._empty_lbl = QLabel("Aucune playlist.\nCliquez sur « + Nouvelle ».")
        self._empty_lbl.setStyleSheet(f"color: {TEXT_MUT}; font-size: 12px;")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        layout.addWidget(self._empty_lbl)

    def refresh(self, svc: MediaService):
        self._media_service = svc
        current_id = None
        cur = self._list.currentItem()
        if cur:
            current_id = cur.data(Qt.UserRole)

        self._list.blockSignals(True)
        self._list.clear()
        playlists = svc.get_playlists()
        found_current = False
        for pl in playlists:
            n = pl.track_count
            item = QListWidgetItem(f"  {pl.name}\n  {n} item{'s' if n != 1 else ''}")
            item.setData(Qt.UserRole, pl.id)
            self._list.addItem(item)
            if pl.id == current_id:
                self._list.setCurrentItem(item)
                found_current = True
        self._list.blockSignals(False)

        has = self._list.count() > 0
        self._list.setVisible(has)
        self._empty_lbl.setVisible(not has)

        if not has:
            # List is empty: the active playlist was the last one → clear right pane
            self.selection_cleared.emit()
        elif not found_current:
            # Active playlist was deleted but others remain → auto-select first
            # setCurrentRow fires currentItemChanged → playlist_selected
            self._list.setCurrentRow(0)

    def select_playlist(self, pl_id: int):
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.UserRole) == pl_id:
                self._list.setCurrentRow(i)
                break

    def _on_item_changed(self, cur, _prev):
        if cur:
            self.playlist_selected.emit(cur.data(Qt.UserRole))

    def _create_playlist(self):
        if not self._media_service:
            return
        name, ok = QInputDialog.getText(self, "Nouvelle playlist", "Nom :")
        if ok and name.strip():
            pl = self._media_service.create_playlist(name.strip())
            self.refresh(self._media_service)
            self.select_playlist(pl.id)
            self.playlist_created.emit()

    def _ctx_menu(self, pos):
        item = self._list.itemAt(pos)
        if not item:
            return
        pl_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {BG_MID}; color: {TEXT_PRI}; border: 1px solid #2a3450; }}
            QMenu::item:selected {{ background: {BG_ROW_SEL}; }}
        """)
        ren = QAction("✏  Renommer", self)
        dup = QAction("⧉  Dupliquer", self)
        delete = QAction("🗑  Supprimer", self)
        menu.addAction(ren)
        menu.addAction(dup)
        menu.addSeparator()
        menu.addAction(delete)
        act = menu.exec(self._list.mapToGlobal(pos))
        if act == ren:
            name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :")
            if ok and name.strip():
                self._media_service.rename_playlist(pl_id, name.strip())
                self.refresh(self._media_service)
        elif act == dup:
            src_pl = self._media_service.get_playlist(pl_id)
            if src_pl:
                new_pl = self._media_service.create_playlist(f"{src_pl.name} (copie)")
                for item_obj in src_pl.items:
                    self._media_service.add_to_playlist(new_pl.id, item_obj.media_id)
                self.refresh(self._media_service)
        elif act == delete:
            pl = self._media_service.get_playlist(pl_id)
            name = pl.name if pl else "?"
            if (
                QMessageBox.question(
                    self,
                    "Supprimer",
                    f"Supprimer la playlist « {name} » et tous ses items ?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                == QMessageBox.Yes
            ):
                self._media_service.delete_playlist(pl_id)
                self.refresh(self._media_service)


# ── Playlist item table ────────────────────────────────────────────────────────

PC_NUM = 0
PC_TYPE = 1
PC_TITLE = 2
PC_INFO = 3
PC_DUR = 4
PC_DEL = 5

PL_HEADERS = ["#", "", "Titre", "Info", "Durée", ""]


class PlaylistItemTable(QTableWidget):
    """Table showing the contents of one playlist."""

    play_item = Signal(int)  # media_id
    remove_item = Signal(int)  # media_id

    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.setHorizontalHeaderLabels(PL_HEADERS)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(PC_TITLE, QHeaderView.Stretch)
        hh.setSectionResizeMode(PC_INFO, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(PC_DUR, QHeaderView.ResizeToContents)
        self.setColumnWidth(PC_NUM, 36)
        self.setColumnWidth(PC_TYPE, 28)
        self.setColumnWidth(PC_DEL, 32)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setStyleSheet(f"""
            QTableWidget {{
                background: {BG_MID}; color: {TEXT_PRI};
                border: none; font-size: 13px;
            }}
            QTableWidget::item {{
                padding: 4px 6px;
                border-bottom: 1px solid #1a2340;
            }}
            QTableWidget::item:selected {{ background: {BG_ROW_SEL}; color: white; }}
            QTableWidget::item:alternate {{ background: #192036; }}
            QHeaderView::section {{
                background: {BG_DARK}; color: {TEXT_MUT};
                padding: 6px 8px; border: none;
                font-size: 11px; font-weight: 700; letter-spacing: 1px;
            }}
        """)
        self._tracks: List[Media] = []
        self.doubleClicked.connect(lambda idx: self._play_row(idx.row()))

    def load(self, tracks: List[Media]):
        self._tracks = tracks
        self.setRowCount(len(tracks))
        for row, m in enumerate(tracks):
            self._fill_row(row, m, row + 1)
        self.resizeRowsToContents()

    def media_at_row(self, row: int) -> Optional[Media]:
        """Always resolve via UserRole – sort-safe."""
        try:
            mid = self.item(row, PC_TITLE).data(Qt.UserRole)
            return next((t for t in self._tracks if t.id == mid), None)
        except Exception:
            return None

    def _fill_row(self, row: int, m: Media, position: int):
        # #
        num_item = QTableWidgetItem(str(position))
        num_item.setTextAlignment(Qt.AlignCenter)
        num_item.setForeground(QColor(TEXT_MUT))
        self.setItem(row, PC_NUM, num_item)

        # type icon
        icon_item = QTableWidgetItem(TYPE_ICONS.get(m.media_type, "?"))
        icon_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, PC_TYPE, icon_item)

        # title
        title_item = QTableWidgetItem(m.title or Path(m.file_path).stem)
        title_item.setData(Qt.UserRole, m.id)
        self.setItem(row, PC_TITLE, title_item)

        # info
        if m.media_type == "music":
            info = " · ".join(filter(None, [m.artist, m.album])) or ""
        elif m.media_type == "episode":
            ep = (
                f"S{m.season_number:02d}E{m.episode_number:02d}"
                if m.season_number and m.episode_number
                else ""
            )
            info = f"{m.series_name or ''} {ep}".strip()
        else:
            info = str(m.year) if m.year else ""
        info_item = QTableWidgetItem(info)
        info_item.setForeground(QColor(TEXT_SEC))
        self.setItem(row, PC_INFO, info_item)

        # duration
        dur_item = QTableWidgetItem(_fmt_dur(m.duration_sec or 0))
        dur_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        dur_item.setForeground(QColor(TEXT_MUT))
        self.setItem(row, PC_DUR, dur_item)

        # delete button
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_MUT};
                border: none; border-radius: 4px; font-size: 13px;
            }}
            QPushButton:hover {{ color: {ACCENT}; background: #2a1a20; }}
        """)
        del_btn.clicked.connect(lambda _, mid=m.id: self.remove_item.emit(mid))
        self.setCellWidget(row, PC_DEL, del_btn)

    def _play_row(self, row: int):
        m = self.media_at_row(row)
        if m:
            self.play_item.emit(m.id)


# ── Main PlaylistView ──────────────────────────────────────────────────────────


class PlaylistView(QWidget):
    """
    Full playlist management tab wired into MainWindow.
    Emits play_media(media_id) for the main window to dispatch correctly
    (audio → MusicView player, video → PlayerView).
    """

    play_queue = Signal(object)  # List[Media] – full queue for sequential playback
    play_media = Signal(int)  # single media_id (double-click on a row)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("content_area")
        self._media_service: Optional[MediaService] = None
        self._current_pl_id: Optional[int] = None
        self._current_tracks: List[Media] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── top bar ───────────────────────────────────────────────────────────
        top = QWidget()
        top.setStyleSheet(f"background: {BG_MID};")
        top.setFixedHeight(54)
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(16, 0, 16, 0)
        top_l.setSpacing(12)

        page_title = QLabel("Playlists")
        page_title.setObjectName("page_title")
        top_l.addWidget(page_title)
        top_l.addStretch()

        root.addWidget(top)

        # ── body ──────────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet(f"background: {BG_MID};")
        body_l = QHBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)

        # sidebar
        self._sidebar = PlaylistSidebar()
        self._sidebar.playlist_selected.connect(self._on_playlist_selected)
        self._sidebar.selection_cleared.connect(self._clear_pane)  # ← NEW
        self._sidebar.playlist_created.connect(lambda: None)
        body_l.addWidget(self._sidebar)

        # separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #2a3450;")
        body_l.addWidget(sep)

        # right pane
        right = QWidget()
        right.setStyleSheet(f"background: {BG_MID};")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(20, 16, 20, 16)
        right_l.setSpacing(12)

        # playlist header
        self._pl_header = QWidget()
        self._pl_header.setStyleSheet(f"""
            background: {BG_PANEL};
            border-radius: 8px;
            padding: 4px;
        """)
        ph_l = QHBoxLayout(self._pl_header)
        ph_l.setContentsMargins(16, 12, 16, 12)
        ph_l.setSpacing(16)

        pl_info = QVBoxLayout()
        self._pl_name_lbl = QLabel("Sélectionnez une playlist")
        self._pl_name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; font-size: 18px; font-weight: 700;"
        )
        self._pl_stats_lbl = QLabel("")
        self._pl_stats_lbl.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px;")
        pl_info.addWidget(self._pl_name_lbl)
        pl_info.addWidget(self._pl_stats_lbl)
        ph_l.addLayout(pl_info, stretch=1)

        self._btn_play_all = QPushButton("▶  Tout lire")
        self._btn_play_all.setObjectName("primary_button")
        self._btn_play_all.setMinimumWidth(120)
        self._btn_play_all.clicked.connect(self._play_all)
        self._btn_play_all.setEnabled(False)

        self._btn_add = QPushButton("➕  Ajouter des médias…")
        self._btn_add.setObjectName("secondary_button")
        self._btn_add.setMinimumWidth(160)
        self._btn_add.clicked.connect(self._add_media)
        self._btn_add.setEnabled(False)

        ph_l.addWidget(self._btn_play_all)
        ph_l.addWidget(self._btn_add)
        right_l.addWidget(self._pl_header)

        # empty state
        self._empty_lbl = QLabel(
            "Créez une playlist dans le panneau gauche,\n"
            "puis ajoutez films, séries et musiques en les mélangeant."
        )
        self._empty_lbl.setObjectName("empty_state")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setVisible(True)
        right_l.addWidget(self._empty_lbl, stretch=1)

        # items table
        self._item_table = PlaylistItemTable()
        self._item_table.play_item.connect(self._on_play_item)
        self._item_table.remove_item.connect(self._on_remove_item)
        self._item_table.setVisible(False)
        right_l.addWidget(self._item_table, stretch=1)

        body_l.addWidget(right, stretch=1)
        root.addWidget(body, stretch=1)

    # ── public ────────────────────────────────────────────────────────────────

    def refresh(self, media_service: MediaService):
        self._media_service = media_service
        self._sidebar.refresh(media_service)
        # reload current playlist if one was selected
        if self._current_pl_id:
            self._load_playlist(self._current_pl_id)

    # ── private ───────────────────────────────────────────────────────────────

    def _on_playlist_selected(self, pl_id: int):
        self._current_pl_id = pl_id
        self._load_playlist(pl_id)

    def _clear_pane(self):
        """Reset the right pane when no playlist is selected (e.g. after last deletion)."""
        self._current_pl_id = None
        self._current_tracks = []
        self._pl_name_lbl.setText("Sélectionnez une playlist")
        self._pl_stats_lbl.setText("")
        self._item_table.setRowCount(0)
        self._item_table.setVisible(False)
        self._empty_lbl.setText(
            "Créez une playlist dans le panneau gauche,\n"
            "puis ajoutez films, séries et musiques en les mélangeant."
        )
        self._empty_lbl.setVisible(True)
        self._btn_play_all.setEnabled(False)
        self._btn_add.setEnabled(False)

    def _load_playlist(self, pl_id: int):
        if not self._media_service:
            return
        pl = self._media_service.get_playlist(pl_id)
        if not pl:
            return

        self._current_tracks = self._media_service.get_playlist_tracks(pl_id)

        # update header
        self._pl_name_lbl.setText(pl.name)
        n = len(self._current_tracks)
        total_s = sum(m.duration_sec or 0 for m in self._current_tracks)
        stats_parts = [f"{n} item{'s' if n != 1 else ''}"]
        if total_s > 0:
            stats_parts.append(_fmt_dur(total_s))
        # count by type
        type_counts: dict = {}
        for m in self._current_tracks:
            type_counts[m.media_type] = type_counts.get(m.media_type, 0) + 1
        type_str = "  ·  ".join(
            f"{TYPE_ICONS[k]} {v}" for k, v in type_counts.items() if k in TYPE_ICONS
        )
        if type_str:
            stats_parts.append(type_str)
        self._pl_stats_lbl.setText("  ·  ".join(stats_parts))

        # toggle widgets
        has = n > 0
        self._item_table.setVisible(has)
        self._empty_lbl.setVisible(not has)
        self._btn_play_all.setEnabled(has)
        self._btn_add.setEnabled(True)

        # load table
        self._item_table.load(self._current_tracks)

    def _play_all(self):
        if self._current_tracks:
            self.play_queue.emit(list(self._current_tracks))

    def _add_media(self):
        if not self._media_service or not self._current_pl_id:
            return
        existing_ids = {m.id for m in self._current_tracks}
        dlg = AddMediaDialog(self._media_service, existing_ids, self)
        if dlg.exec() == QDialog.Accepted and dlg.selected_media:
            for m in dlg.selected_media:
                self._media_service.add_to_playlist(self._current_pl_id, m.id)
            self._sidebar.refresh(self._media_service)
            self._load_playlist(self._current_pl_id)

    def _on_play_item(self, media_id: int):
        self.play_media.emit(media_id)

    def _on_remove_item(self, media_id: int):
        if not self._media_service or not self._current_pl_id:
            return
        self._media_service.remove_from_playlist(self._current_pl_id, media_id)
        self._sidebar.refresh(self._media_service)
        self._load_playlist(self._current_pl_id)
