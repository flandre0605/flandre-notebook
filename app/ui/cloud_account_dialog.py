"""Account sign-in and reviewable sync controls, separate from probe tools."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from uuid import uuid4

from PySide6.QtCore import QSettings, QThreadPool, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QTextEdit, QVBoxLayout)

from app.services.cloudbase_login import LoginCheckError, login_session
from app.services.cloud_sync import CloudClient, CloudSession, CloudSyncError, ENVIRONMENT_ID, synchronize
from app.services.cloud_accounts import open_account
from app.ui.worker import Worker
from app.ui.theme import STYLE


def copy_deployment(status):
    try:
        path = Path(__file__).resolve().parents[2] / 'cloud/sql/004_desktop_sync.sql'
        QApplication.clipboard().setText(path.read_text(encoding='utf-8'))
        status.setText('部署脚本已复制。在 CloudBase 的 SQL 编辑器执行一次；已部署时无需重复执行。')
    except OSError:
        status.setText('部署脚本未包含在此版本中，请使用完整源码版本。')


class CloudSignInDialog(QDialog):
    def __init__(self, parent=None, username='tes_1', expected_user=None):
        super().__init__(parent)
        self.setWindowTitle('Flandre · 登录账号题库')
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(480)
        self.expected_user = expected_user
        self.session = None
        self.worker = None
        settings = QSettings('FlandreNotebook', 'CloudLoginCheck')
        self.device_id = settings.value('device_id', '')
        if not self.device_id:
            self.device_id = uuid4().hex
            settings.setValue('device_id', self.device_id)
        layout = QVBoxLayout(self)
        hint = QLabel('登录后打开此账号独立的题库和图片目录。\n本地题库可继续使用，导入和云同步都有独立入口。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.username = QLineEdit(username)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('用户名', self.username)
        form.addRow('密码', self.password)
        layout.addLayout(form)
        self.login_button = QPushButton('登录并打开题库')
        self.login_button.clicked.connect(self.sign_in)
        self.password.returnPressed.connect(self.sign_in)
        layout.addWidget(self.login_button)
        deploy = QPushButton('复制电脑端同步部署脚本')
        deploy.clicked.connect(lambda: copy_deployment(self.status))
        layout.addWidget(deploy)
        self.status = QLabel('上海体验环境 · 密码和登录凭据不保存。')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

    def sign_in(self):
        if self.worker is not None:
            return
        username, password = self.username.text().strip(), self.password.text()
        if not username or not password:
            self.status.setText('请填写用户名和密码。')
            return
        self.password.clear()
        self.username.setEnabled(False)
        self.password.setEnabled(False)
        self.login_button.setEnabled(False)
        self.status.setText('正在登录，请稍候……')
        self.worker = Worker(lambda: login_session(ENVIRONMENT_ID, username, password, self.device_id))
        self.worker.signals.succeeded.connect(lambda result: self._logged_in(result, username))
        self.worker.signals.failed.connect(self._failed)
        QThreadPool.globalInstance().start(self.worker)

    def _finish(self):
        self.worker.function = lambda: None
        self.worker = None
        self.username.setEnabled(True)
        self.password.setEnabled(True)
        self.login_button.setEnabled(True)

    def _logged_in(self, result, username):
        self._finish()
        if self.expected_user is not None and result.get('user_id') != self.expected_user:
            result.clear()
            self.status.setText('这是其他账号。请登录当前账号；使用“打开另一个账号”切换题库。')
            return
        try:
            self.session = CloudSession(result, username)
        except CloudSyncError as error:
            result.clear()
            self.status.setText(str(error))
            return
        self.accept()

    def _failed(self, error):
        self._finish()
        self.status.setText(str(error) if isinstance(error, LoginCheckError) else '登录未完成，请重试。')

    def reject(self):
        if self.worker is not None:
            self.status.setText('正在登录，请结束后再关闭。')
            return
        super().reject()


class CloudAccountDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('账号与同步')
        self.setMinimumSize(620, 440)
        self.worker = None
        self.controls = []
        layout = QVBoxLayout(self)
        session = window.cloud_session
        self.heading = QLabel('本地学习空间' if session is None else f'当前账号：{session.username}')
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.heading)
        hint = QLabel('账号题库在独立窗口中打开。登录不会自动上传原来的本地题库。' if session is None else
                      '同步题目、笔记、掌握状态和原图。断网时继续本地保存，恢复网络后可手动同步。\n'
                      '单词、逐次练习历史和编辑草稿保存在此账号的本机目录。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        def button(text, callback):
            value = QPushButton(text)
            value.clicked.connect(callback)
            self.controls.append(value)
            actions.addWidget(value)
            return value
        button('登录账号' if session is None else '打开另一个账号', lambda: open_account(window.cloud_root))
        if session:
            button('立即同步', self.sync)
            button('重新登录', self.renew)
            button('退出账号', self.logout)
        layout.addLayout(actions)
        if session:
            row = QHBoxLayout()
            self.import_button = QPushButton('导入原来的本地题库')
            self.import_button.clicked.connect(self.import_local)
            self.controls.append(self.import_button)
            row.addWidget(self.import_button)
            self.conflict_button = QPushButton('处理同步冲突')
            self.conflict_button.clicked.connect(self.conflicts)
            self.controls.append(self.conflict_button)
            row.addWidget(self.conflict_button)
            layout.addLayout(row)
        deploy = QPushButton('复制电脑端同步部署脚本')
        deploy.clicked.connect(lambda: copy_deployment(self.status))
        layout.addWidget(deploy)
        self.details = QLabel('首次使用需部署云端业务表和私有图片桶。已有的登录、测试表及测试桶继续保留。')
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        layout.addStretch()
        self.refresh()

    def local(self):
        from app.services.cloud_sync_store import SyncStore
        return SyncStore(self.window.cloud_directory, self.window.cloud_session.user_id, ENVIRONMENT_ID)

    def refresh(self):
        if self.window.cloud_session is None:
            self.status.setText('当前内容只保存在本地。点击“登录账号”打开账号题库。')
            return
        state = self.local().status()
        self.status.setText(f"待同步：{state['pending']} 道题 · 待处理冲突：{state['conflicts']} 道题\n"
                            f"最近完成同步：{state['last_success'] or '尚未同步'}")

    def run(self, function, callback):
        if self.worker is not None:
            return
        for control in self.controls:
            control.setEnabled(False)
        self.status.setText('正在处理，请稍候……本地修改已保留。')
        self.worker = Worker(function)
        self.worker.signals.succeeded.connect(lambda result: self._completed(result, callback))
        self.worker.signals.failed.connect(self._failed)
        QThreadPool.globalInstance().start(self.worker)

    def _finish(self):
        self.worker.function = lambda: None
        self.worker = None
        for control in self.controls:
            control.setEnabled(True)

    def _completed(self, result, callback):
        self._finish()
        self._refresh_window()
        callback(result)

    def _failed(self, error):
        self._finish()
        self._refresh_window()
        self.refresh()
        if isinstance(error, (CloudSyncError, LoginCheckError, ValueError)):
            message = str(error)
        elif isinstance(error, (sqlite3.Error, OSError)):
            message = '本地数据库或图片未能完成处理，请检查目录和剩余空间后重试。'
        else:
            message = '处理未完成，本地修改已保留，请检查后重试。'
        self.details.setText(message)

    def _refresh_window(self):
        for key in ('attachments', 'reader'):
            if key in self.window._pages:
                if self.window.page_stack.currentWidget() is self.window._pages[key]:
                    self.window._show_page('library')
                self.window._discard_page(key)
        self.window._refresh_filter_options()
        self.window.refresh()

    def _ready_for_changes(self):
        if not self.window._save_workspaces():
            self.details.setText('个人笔记尚未保存，请修正后重试。')
            return False
        if 'question' in self.window._pages or 'practice_run' in self.window._pages:
            self.details.setText('请先保存或关闭题目编辑，结束当前练习，再进行同步。未保存的草稿继续保留。')
            return False
        if any(getattr(dialog, '_recognizing', False) for dialog in self.window._recognition_dialogs):
            self.details.setText('请等本次识题结束后再同步，原图和草稿已保留。')
            return False
        return True

    def sync(self):
        if not self._ready_for_changes():
            return
        local, client = self.local(), CloudClient(self.window.cloud_session)
        def completed(result):
            self.refresh()
            self.details.setText(f"本轮已上传 {result['uploaded']} 项，接收 {result['downloaded']} 项变化。" +
                ('仍有同步冲突，请点击“处理同步冲突”。' if result['conflicts'] else
                 '仍有待同步修改，请再次同步。' if result['pending'] else '当前题目与原图已同步。') +
                ('旧编辑草稿已保存副本，可在“处理同步冲突”中查看副本目录。' if result['archived_drafts'] else ''))
        self.run(lambda: synchronize(local, client), completed)

    def renew(self):
        dialog = CloudSignInDialog(self, self.window.cloud_session.username, self.window.cloud_session.user_id)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.window.cloud_session.close()
            self.window.cloud_session = dialog.session
            self.details.setText('登录已更新，可以继续同步。')

    def logout(self):
        if self.worker is not None:
            return
        self.accept()
        # The process keeps one immutable workspace until it has closed its jobs.
        if self.window.close():
            self.window.cloud_session.close()

    def import_local(self):
        source = self.window.cloud_root
        if not (source / 'questions.db').is_file():
            self.details.setText('原本地题库尚不存在。可以在此账号直接新增题目。')
            return
        with closing(sqlite3.connect(source.resolve().joinpath('questions.db').as_uri() + '?mode=ro', uri=True)) as db:
            count = db.execute('SELECT count(*) FROM questions').fetchone()[0]
        if QMessageBox.question(self, '导入本地题库', f'将原本地题库的 {count} 道题、原图和掌握状态复制到当前账号。\n'
                '导入前保存完整本地备份，原题库继续保留；同一来源已导入的题目会跳过。\n'
                '导入后点击“立即同步”上传到当前账号，继续导入吗？') != QMessageBox.StandardButton.Yes:
            return
        local = self.local()
        def completed(result):
            self.refresh()
            self.details.setText(f"已导入 {result['imported']} 道题。原题库保留，备份位置：{result['backup']}\n点击立即同步上传。")
        self.run(lambda: local.import_guest(source), completed)

    def conflicts(self):
        if not self._ready_for_changes():
            return
        dialog = ConflictDialog(self.local(), CloudClient(self.window.cloud_session), self)
        dialog.exec()
        self.refresh()
        self._refresh_window()

    def reject(self):
        if self.worker is not None:
            self.details.setText('处理正在进行，请结束后再关闭。单次网络请求最多等待约 30 秒。')
            return
        super().reject()


class ConflictDialog(QDialog):
    def __init__(self, local, client, parent):
        super().__init__(parent)
        self.local, self.client = local, client
        self.worker = None
        self.setWindowTitle('处理同步冲突')
        self.resize(800, 600)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)
        self.status = QLabel('选择一项比较本地和云端内容。处理前会保留本地内容与原图的副本。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.keep_button = QPushButton('保留本地修改')
        self.cloud_button = QPushButton('采用云端内容')
        self.keep_button.clicked.connect(lambda: self.resolve(True))
        self.cloud_button.clicked.connect(lambda: self.resolve(False))
        actions.addWidget(self.keep_button)
        actions.addWidget(self.cloud_button)
        backups = QPushButton('查看保留的冲突副本')
        backups.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(local.root / 'attachments' / '_conflicts'))))
        actions.addWidget(backups)
        layout.addLayout(actions)
        self.list.currentRowChanged.connect(self.selected)
        self.reload()

    def reload(self):
        self.rows = self.local.conflicts()
        self.list.clear()
        for row in self.rows:
            self.list.addItem(row['stem'] or '本地已删除的题目')
        if self.rows:
            self.list.setCurrentRow(0)
        else:
            self.preview.setPlainText('没有待处理冲突。')
        self.keep_button.setEnabled(bool(self.rows))
        self.cloud_button.setEnabled(bool(self.rows))

    def selected(self, index):
        if index < 0 or index >= len(self.rows):
            return
        row = self.rows[index]
        with self.local.connection() as db:
            question = db.execute('SELECT * FROM questions WHERE id=?', (row['local_id'],)).fetchone()
        remote = json.loads(row['conflict'])
        content = ('本地：\n' + (json.dumps(dict(question), ensure_ascii=False, indent=2) if question else '已删除') +
                   '\n\n云端：\n' + ('已删除' if remote and remote['deleted'] else json.dumps(remote, ensure_ascii=False, indent=2)))
        self.preview.setPlainText(content)

    def resolve(self, keep_local):
        index = self.list.currentRow()
        if self.worker is not None or index < 0:
            return
        entity_id = self.rows[index]['id']
        self.keep_button.setEnabled(False)
        self.cloud_button.setEnabled(False)
        self.list.setEnabled(False)
        self.status.setText('正在保留副本并处理，请稍候……')
        self.worker = Worker(lambda: self.local.resolve(entity_id, keep_local, self.client))
        self.worker.signals.succeeded.connect(self.completed)
        self.worker.signals.failed.connect(self.failed)
        QThreadPool.globalInstance().start(self.worker)

    def finish(self):
        self.worker.function = lambda: None
        self.worker = None
        self.list.setEnabled(True)
        self.reload()

    def completed(self, result):
        self.finish()
        self.status.setText('冲突已处理，本地副本已保留。回到账号窗口再次同步。')

    def failed(self, error):
        self.finish()
        self.status.setText(str(error) if isinstance(error, (CloudSyncError, ValueError)) else '处理未完成，请重试。')

    def reject(self):
        if self.worker is None:
            super().reject()
