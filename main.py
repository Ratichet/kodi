import sys

from core.vlc_bootstrap import ensure_vlc_path

# Doit précéder tout import qui charge python-vlc (ui.main_window en charge un).
ensure_vlc_path()

import logging  # noqa: E402

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import ICON_FILE  # noqa: E402
from core.database import init_db  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _claim_windows_identity():
    """Déclare l'application auprès du shell Windows.

    Sans identité propre, la barre des tâches range la fenêtre sous le programme
    qui l'héberge — python.exe en développement — et affiche l'icône de celui-ci
    plutôt que la nôtre.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "EpiKodi.MediaCenter"
        )
    except (AttributeError, OSError) as e:  # pragma: no cover - dépend du système
        logger.debug(f"Could not set the Windows application id: {e}")


def main():
    logger.info("Lancement de EpiKodi")

    logger.info("Initialisation de la base de données...")
    init_db()

    _claim_windows_identity()

    app = QApplication(sys.argv)
    app.setApplicationName("EpiKodi")
    app.setOrganizationName("EpiKodi")
    # L'icône du .exe ne concerne que l'explorateur : la barre des tâches et les
    # boîtes de dialogue prennent celle de l'application Qt.
    app.setWindowIcon(QIcon(str(ICON_FILE)))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
