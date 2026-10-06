"""Run from source to verify the test account without saving passwords/tokens."""
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFormLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QVBoxLayout

from app.services.cloudbase_login import LoginCheckError, validate_login
from app.services.cloudbase_probe import ProbeError, verify_database
from app.services.cloudbase_storage_probe import StorageProbeError, verify_storage, BUCKET_ID
from app.ui.worker import Worker


ENVIRONMENT_ID = "flandre-d5gtb0c714184017a"


class LoginCheckDialog(QDialog):
    def __init__(self, database=False, storage=False):
        super().__init__()
        self.storage = storage
        self.database = database and not storage
        database = self.database
        self.has_second = database or storage
        self.setWindowTitle("Flandre · 私有图片验证" if storage else
                            "Flandre · 云端数据验证" if database else "Flandre · 云端登录验证")
        self.setMinimumWidth(480)
        self.worker = None
        settings = QSettings("FlandreNotebook", "CloudLoginCheck")
        self.device_id = settings.value("device_id", "")
        if not isinstance(self.device_id, str) or not self.device_id:
            self.device_id = str(uuid4())
            settings.setValue("device_id", self.device_id)
        layout = QVBoxLayout(self)
        intro = QLabel("上海 · CloudBase PostgreSQL 体验环境\n密码和登录凭据不保存。" +
                       ("先检查存储，再执行私有测试桶脚本一次。只上传自动生成的小图片。" if storage else
                        "先复制建表脚本到控制台执行一次，再验证专用测试表。" if database else "验证账号登录。"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.addRow("环境", QLabel(ENVIRONMENT_ID))
        if storage:
            form.addRow("测试桶", QLabel(BUCKET_ID))
        self.username = QLineEdit("tes_1")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("用户名", self.username)
        form.addRow("密码", self.password)
        layout.addLayout(form)
        if self.has_second:
            self.second = QGroupBox("可选：使用第二个普通账号验证多用户隔离")
            self.second.setCheckable(True)
            self.second.setChecked(storage)
            second_form = QFormLayout(self.second)
            self.second_username = QLineEdit("tes_2" if storage else "")
            self.second_password = QLineEdit()
            self.second_password.setEchoMode(QLineEdit.EchoMode.Password)
            second_form.addRow("第二个用户名", self.second_username)
            second_form.addRow("第二个密码", self.second_password)
            layout.addWidget(self.second)
        self.button = QPushButton("验证私有图片" if storage else "验证云端读写" if database else "验证登录")
        self.button.clicked.connect(self.check_login)
        self.password.returnPressed.connect(self.check_login)
        layout.addWidget(self.button)
        if self.has_second:
            copy_environment = QPushButton("复制存储只读检查" if storage else "复制只读环境检查")
            copy_environment.clicked.connect(self.copy_environment)
            layout.addWidget(copy_environment)
            copy_script = QPushButton("复制私有测试桶脚本" if storage else "复制建表与权限脚本")
            copy_script.clicked.connect(self.copy_script)
            layout.addWidget(copy_script)
        self.status = QLabel("先运行存储只读检查，确认后执行测试桶脚本；填写两个账号的密码验证。" if storage else
                             "先执行建表脚本，再输入密码验证。第二个账号可以稍后补测。" if database
                             else "输入刚创建的测试账号密码，然后点击验证。")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.password.setFocus()

    def copy_environment(self):
        path = Path(__file__).resolve().parents[1] / ("cloud/sql/002_check_storage.sql" if self.storage
                                                     else "cloud/sql/000_check_environment.sql")
        try:
            QApplication.clipboard().setText(path.read_text(encoding="utf-8"))
            self.status.setText("存储只读检查已复制。请在 SQL 编辑器执行，将结果发来核对后再创建测试桶。" if self.storage
                                else "只读检查已复制。在 SQL 编辑器执行后核对函数、角色和测试表；未确认前先不执行建表。")
        except OSError:
            self.status.setText("无法读取环境检查脚本，请检查项目文件是否完整。")

    def copy_script(self):
        path = Path(__file__).resolve().parents[1] / ("cloud/sql/003_image_probe.sql" if self.storage
                                                     else "cloud/sql/001_connection_probe.sql")
        try:
            QApplication.clipboard().setText(path.read_text(encoding="utf-8"))
            self.status.setText("私有测试桶脚本已复制。确认只读检查通过后，在 SQL 编辑器执行一次；"
                                "已存在的桶不要删除或重建。" if self.storage else
                                "脚本已复制。到 CloudBase 的 SQL 型数据库 → SQL 编辑器粘贴并执行一次。")
        except OSError:
            self.status.setText("无法读取建表脚本，请检查项目文件是否完整。")

    def check_login(self):
        if self.worker is not None:
            return
        username, password = self.username.text().strip(), self.password.text()
        if not username or not password:
            self.status.setText("请填写用户名和密码。")
            return
        second_username, second_password = "", ""
        if self.has_second and self.second.isChecked():
            second_username = self.second_username.text().strip()
            second_password = self.second_password.text()
            if not second_username or not second_password:
                self.status.setText("请填写第二个账号的用户名和密码，或取消第二账号验证选项。")
                return
        if self.has_second:
            self.second_password.clear()
            self.second.setEnabled(False)
        self.password.clear()
        self.button.setEnabled(False)
        self.username.setEnabled(False)
        self.password.setEnabled(False)
        self.status.setText("正在连接云端，请稍候……")
        if self.storage:
            self.worker = Worker(lambda: verify_storage(ENVIRONMENT_ID, username, password, self.device_id,
                                                       second_username, second_password))
        elif self.database:
            self.worker = Worker(lambda: verify_database(ENVIRONMENT_ID, username, password, self.device_id,
                                                        second_username, second_password))
        else:
            self.worker = Worker(lambda: validate_login(ENVIRONMENT_ID, username, password, self.device_id))
        self.worker.signals.succeeded.connect(self.succeeded)
        self.worker.signals.failed.connect(self.failed)
        QThreadPool.globalInstance().start(self.worker)

    def finish(self):
        self.worker.function = lambda: None
        self.worker = None
        self.button.setEnabled(True)
        self.username.setEnabled(True)
        self.password.setEnabled(True)
        if self.has_second:
            self.second.setEnabled(True)

    def succeeded(self, summary):
        self.finish()
        if self.storage:
            self.status.setText(f"私有图片验证完成\n用户编号：{summary['user_id']}\n" +
                                "\n".join(summary["checks"]) +
                                "\n本轮图片已确认清理；仅验证小型 PNG，正式附件与手机同步仍待接入。")
            return
        if self.database:
            self.status.setText(f"测试表验证完成\n用户编号：{summary['user_id']}\n" +
                                "\n".join(summary["checks"]) +
                                "\n本轮已尝试清理测试记录；图片、正式题库和同步仍待验证。")
            return
        self.status.setText(f"登录成功\n用户编号：{summary['user_id']}\n"
                            f"凭据有效期：{summary['expires_in']} 秒（本工具不保存凭据）\n"
                            "本次仅验证登录；题库、图片同步与账号隔离仍待验证。")

    def failed(self, error):
        self.finish()
        self.status.setText(str(error) if isinstance(error, (LoginCheckError, ProbeError, StorageProbeError))
                            else "验证未完成，请检查本地环境后再试。")

    def closeEvent(self, event):
        if self.worker is not None:
            self.status.setText("验证正在进行，请结束后再关闭（单次请求超时约 20 秒）。")
            event.ignore()
        else:
            super().closeEvent(event)


if __name__ == "__main__":
    application = QApplication(sys.argv)
    dialog = LoginCheckDialog(database="--database" in sys.argv, storage="--storage" in sys.argv)
    if "--foreground" in sys.argv:
        # Briefly show the requested tool above the older validation window.
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        def release_topmost():
            dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        QTimer.singleShot(8000, release_topmost)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    result = application.exec()
    QThreadPool.globalInstance().waitForDone()
    sys.exit(result)
