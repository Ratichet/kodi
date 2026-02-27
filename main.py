import os
import sys

def _patch_vlc_path():
    if not getattr(sys, "frozen", False):
        return 

    bundle_dir = sys._MEIPASS
    vlc_dir = os.path.join(bundle_dir, "vlc_libs")

    if not os.path.isdir(vlc_dir):
        return

    libvlc = os.path.join(vlc_dir, "libvlc.dll")
    if os.path.isfile(libvlc):
        os.environ["PYTHON_VLC_LIB_PATH"] = libvlc
    os.environ["PATH"] = vlc_dir + os.pathsep + os.environ.get("PATH", "")

_patch_vlc_path()

import logging
from PySide6.QtWidgets import QApplication

from core.database import init_db
from ui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Lancement de EpiKodi")

    logger.info("Initialisation de la base de données...")
    init_db()

    app = QApplication(sys.argv)
    app.setApplicationName("EpiKodi")
    app.setOrganizationName("EpiKodi")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
