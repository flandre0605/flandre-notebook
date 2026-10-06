import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout
from app.services.mobile_inbox import InboxClient, InboxStore
from app.database import store
from app.ui.worker import Worker


class MobileInboxDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.worker = None
        self.setWindowTitle('手机待整理')
        self.resize(650, 460)
        self.setStyleSheet(window.styleSheet())
        self.local = InboxStore(window.cloud_directory, window.cloud_session.user_id)
        layout = QVBoxLayout(self)
        hint = QLabel('手机拍题后，在这里接收。打开图片生成草稿，核对后才会收录到题库。\n原图和裁剪图都会保留；关闭识题窗口可稍后继续。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton('接收手机图片')
        self.refresh_button.clicked.connect(self.receive)
        actions.addWidget(self.refresh_button)
        self.open_button = QPushButton('打开并整理')
        self.open_button.clicked.connect(self.open_image)
        actions.addWidget(self.open_button)
        deploy = QPushButton('复制手机待整理部署脚本')
        deploy.clicked.connect(self.copy_deployment)
        actions.addWidget(deploy)
        layout.addLayout(actions)
        self.list.itemDoubleClicked.connect(lambda _: self.open_image())
        self.refresh()

    def copy_deployment(self):
        path = Path(__file__).resolve().parents[2] / 'cloud/sql/005_mobile_inbox.sql'
        try:
            QApplication.clipboard().setText(path.read_text(encoding='utf-8'))
            self.status.setText('脚本已复制。已有 004 的环境只执行此 005 脚本一次，随后接收图片。')
        except OSError:
            self.status.setText('请使用完整源码中的 cloud/sql/005_mobile_inbox.sql。')

    def refresh(self):
        self.list.clear()
        self.rows = self.local.pending()
        for row in self.rows:
            payload = json.loads(row['payload'])
            self.list.addItem(payload['source_name'] + (' · 已有草稿' if row['recognition_key'] else '') +
                             ('\n' + payload['note'] if payload['note'] else ''))
        self.open_button.setEnabled(bool(self.rows) and self.worker is None)
        if self.rows:
            self.list.setCurrentRow(0)
        self.status.setText(f'本机待整理：{len(self.rows)} 张。收录回执在下次接收时发送。')

    def receive(self):
        if self.worker is not None:
            return
        client = InboxClient(self.window.cloud_session)
        self.worker = Worker(lambda: self.local.receive(client))
        self.refresh_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.status.setText('正在接收图片和确认收录回执……')
        self.worker.signals.succeeded.connect(self.completed)
        self.worker.signals.failed.connect(self.failed)
        QThreadPool.globalInstance().start(self.worker)

    def finish(self):
        self.worker.function = lambda: None
        self.worker = None
        self.refresh_button.setEnabled(True)
        self.refresh()

    def completed(self, count):
        self.finish()
        self.status.setText(f'接收完成：{count} 项变化，本机待整理 {len(self.rows)} 张。')

    def failed(self, error):
        self.finish()
        from app.services.cloud_sync import CloudSyncError
        self.status.setText(str(error) if isinstance(error,(CloudSyncError,ValueError)) else '接收未完成，本地图片和草稿已保留，请重试。')

    def open_image(self):
        if self.worker is not None or self.list.currentRow()<0:
            return
        try:
            key = self.local.draft(self.rows[self.list.currentRow()]['id'])
            self.window.start_image_recognition(resume_key=key)
            self.accept()
        except (OSError,ValueError,sqlite3.Error):
            self.status.setText('草稿未能打开，请检查本机图片和目录，接收记录仍保留。')

    def reject(self):
        if self.worker is not None:
            self.status.setText('正在接收图片，请结束后再关闭。')
            return
        super().reject()
