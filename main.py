import sys
from pathlib import Path
import sqlite3
import os

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.storage import initialize_storage
from app.ui.main_window import MainWindow


def main() -> int:
    verify_output = None
    if "--verify-package" in sys.argv:
        index = sys.argv.index("--verify-package")
        if index + 1 >= len(sys.argv) or not os.environ.get("FLANDRE_DATA_DIR"):
            return 2
        verify_output = sys.argv[index + 1]
    app = QApplication(sys.argv)
    app.setOrganizationName("FlandreNotebook")
    app.setApplicationName("AI 错题本")
    if verify_output:
        app.setApplicationName(f"FlandreRuntimeCheck-{os.getpid()}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    icon_path = Path(__file__).resolve().parent / "assets" / "flandre_icon.ico"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    try:
        startup_notice = initialize_storage()
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        QMessageBox.critical(None, "无法打开学习数据", f"{error}\n\n请检查数据目录或备份后再启动。")
        return 1
    window = MainWindow()
    window.show()
    if startup_notice:
        window.statusBar().showMessage(startup_notice, 15000)
    if verify_output:
        from app.services.runtime_check import verify_package
        return verify_package(app, window, verify_output)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
