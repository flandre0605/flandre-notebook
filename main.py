import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.database.store import initialize
from app.ui.main_window import MainWindow


def main() -> int:
    initialize()
    app = QApplication(sys.argv)
    app.setApplicationName("AI 错题本")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
