import os
import platform
from PySide6.QtWidgets import QFrame

project_dir = os.getcwd()
vlc_local_path = os.path.join(project_dir, "vlc_libs")

if os.path.exists(vlc_local_path):
    os.environ["PYTHON_VLC_MODULE_PATH"] = vlc_local_path

    if platform.system() == "Windows":  # Windows
        os.environ["PATH"] = vlc_local_path + ";" + os.environ.get("PATH", "")
    else:  # UNIX systems
        os.environ["LD_LIBRARY_PATH"] = (
            vlc_local_path + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        )

import vlc


class VideoWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: black;")
        self.instance = vlc.Instance("--input-repeat=1")
        self.player = self.instance.media_player_new()

    def attach_surface(self):
        win_id = int(self.winId())

        if platform.system() == "Windows":
            self.player.set_hwnd(win_id)
        elif platform.system() == "Linux":
            self.player.set_xwindow(win_id)
        elif platform.system() == "Darwin":
            self.player.set_nsobject(win_id)

    def showEvent(self, event):
        self.attach_surface()
        super().showEvent(event)
