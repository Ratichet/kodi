import sys
import logging
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def main():
    print("Lancement de epikodi")

    app = QApplication(sys.argv)
    app.setApplicationName("epikodi")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()