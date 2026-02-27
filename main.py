import sys
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
