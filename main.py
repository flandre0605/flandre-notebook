import sys
from pathlib import Path

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from app.database.store import initialize
from app.ui.main_window import MainWindow


def main() -> int:
    initialize()
    app = QApplication(sys.argv)
    app.setOrganizationName("FlandreNotebook")
    app.setApplicationName("AI 错题本")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    icon_path = Path(__file__).resolve().parent / "assets" / "flandre_icon.ico"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
