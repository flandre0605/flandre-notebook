import sys
from pathlib import Path
import sqlite3
import os

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

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
    from app.paths import user_data_dir
    guest_root = user_data_dir()
    session = None
    workspace_lock = None
    if '--cloud' in sys.argv:
        if '--workspace-root' in sys.argv:
            index = sys.argv.index('--workspace-root')
            if index + 1 >= len(sys.argv) or not Path(sys.argv[index + 1]).is_absolute():
                return 2
            guest_root = Path(sys.argv[index + 1]).resolve()
        from app.ui.cloud_account_dialog import CloudSignInDialog
        from app.services.cloud_accounts import account_directory
        from PySide6.QtCore import QLockFile
        from PySide6.QtWidgets import QDialog
        login = CloudSignInDialog()
        if '--foreground' in sys.argv:
            from PySide6.QtCore import Qt
            # Keep only this requested modal login above the older probe window.
            # Changing its window flags during exec() would end the modal loop.
            login.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            login.show()
            login.raise_()
            login.activateWindow()
        if login.exec() != QDialog.DialogCode.Accepted:
            return 0
        session = login.session
        try:
            directory = account_directory(guest_root, session.user_id)
            directory.mkdir(parents=True, exist_ok=True)
            workspace_lock = QLockFile(str(directory / '.workspace.lock'))
            if not workspace_lock.tryLock(0):
                QMessageBox.information(None, '账号题库已打开', '此账号的题库窗口已打开，请从任务栏切换到该窗口。')
                session.close()
                return 0
            # Set paths before importing any store/attachment/UI services.
            os.environ['FLANDRE_DATA_DIR'] = str(directory)
            from app import paths
            paths.DATA_DIR = directory
            app.setApplicationName('FlandreAccount-' + directory.name[:16])
        except (OSError, ValueError) as error:
            session.close()
            QMessageBox.critical(None, '无法打开账号题库', str(error))
            return 1
    from app.services.storage import initialize_storage
    from app.ui.main_window import MainWindow
    try:
        startup_notice = initialize_storage()
        if session:
            from app.database import store
            from app.services.cloud_sync_store import SyncStore
            from app.services.cloud_sync import ENVIRONMENT_ID
            SyncStore(store.DATA_DIR, session.user_id, ENVIRONMENT_ID).bind()
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        if session:
            session.close()
        QMessageBox.critical(None, "无法打开学习数据", f"{error}\n\n请检查数据目录或备份后再启动。")
        return 1
    window = MainWindow(cloud_session=session, cloud_root=guest_root)
    window.show()
    if startup_notice:
        window.statusBar().showMessage(startup_notice, 15000)
    if verify_output:
        from app.services.runtime_check import verify_package
        return verify_package(app, window, verify_output)
    result = app.exec()
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone()
    if session:
        window.cloud_session.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
