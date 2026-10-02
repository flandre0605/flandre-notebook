from uuid import uuid4

from PySide6.QtCore import QSettings, Qt, QThreadPool, QUrl
from PySide6.QtGui import QKeySequence, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QKeySequenceEdit, QLineEdit, QListWidget, QMessageBox, QSpinBox, QVBoxLayout, QApplication,
)

from app.database import store
from app.services import credentials
from app.services import deepseek_web
from app.services.model_provider import list_models, test_profile, validate_profile
from app.ui.screenshot import GlobalScreenshotHotkey
from app.ui.motion import AnimatedButton
from app.ui.theme import ACCENT, MUTED
from app.ui.worker import Worker


class ProfilesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置与模型服务")
        self.resize(760, 540)
        self.profiles = QListWidget()
        self.profiles.currentRowChanged.connect(self._show_profile)
        self.name = QLineEdit()
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://中转站域名/v1")
        self.endpoint_path = QLineEdit("/chat/completions")
        self.endpoint_path.setPlaceholderText("/chat/completions")
        self.endpoint_path.setToolTip("中转站自定义的 OpenAI 兼容接口路径；通常为 /chat/completions")
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.fetch_models_button = AnimatedButton("获取模型列表")
        self.fetch_models_button.clicked.connect(self._fetch_models)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("新配置必填；编辑时留空表示保留原密钥")
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 300)
        self.timeout.setSuffix(" 秒")
        self.vision = QCheckBox("支持图片识题")
        self.enabled = QCheckBox("启用")
        self.enabled.setChecked(True)
        self.test_button = AnimatedButton("测试连接")
        self.test_button.clicked.connect(self._test)
        self.connection_status = QLabel("尚未测试连接")
        self.connection_status.setWordWrap(True)
        self.connection_status.setStyleSheet(f"color:{MUTED};font-size:12px;")
        self.screenshot_shortcut = QKeySequenceEdit(
            QKeySequence(QSettings().value("shortcuts/screenshot", "Ctrl+Alt+S"))
        )
        self.screenshot_shortcut.setMinimumHeight(38)
        self.apply_shortcut_button = AnimatedButton("应用快捷键")
        self.apply_shortcut_button.clicked.connect(self._apply_screenshot_shortcut)
        self.shortcut_status = QLabel(
            f"当前快捷键：{self.screenshot_shortcut.keySequence().toString(QKeySequence.SequenceFormat.NativeText)}"
        )
        self.shortcut_status.setStyleSheet(f"color:{MUTED};font-size:12px;")
        self.new_button = AnimatedButton("新增配置")
        self.new_button.setObjectName("softButton")
        self.save_button = AnimatedButton("保存配置")
        self.save_button.setObjectName("primaryButton")
        self.delete_button = AnimatedButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.new_button.clicked.connect(self._new)
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)
        self.web_start_button = AnimatedButton("启动网页版服务")
        self.web_start_button.clicked.connect(self._start_web)
        self.web_manage_button = AnimatedButton("打开管理页")
        self.web_manage_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(deepseek_web.ORIGIN)))
        self.web_password_button = AnimatedButton("复制管理密码")
        self.web_password_button.clicked.connect(self._copy_web_password)
        QApplication.instance().aboutToQuit.connect(deepseek_web.shutdown)

        form = QFormLayout()
        form.setVerticalSpacing(14)
        form.addRow("显示名称", self.name)
        form.addRow("API 基础地址", self.base_url)
        form.addRow("API 请求路径", self.endpoint_path)
        model_row = QHBoxLayout()
        model_row.setSpacing(10)
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.fetch_models_button)
        form.addRow("模型 ID", model_row)
        form.addRow("API Key", self.api_key)
        form.addRow("超时", self.timeout)
        form.addRow("能力", self.vision)
        form.addRow("状态", self.enabled)
        shortcut_row = QHBoxLayout()
        shortcut_row.setSpacing(10)
        shortcut_row.addWidget(self.screenshot_shortcut, 1)
        shortcut_row.addWidget(self.apply_shortcut_button)
        form.addRow("截图快捷键", shortcut_row)
        form.addRow("", self.shortcut_status)
        connection_row = QHBoxLayout()
        connection_row.setSpacing(10)
        connection_row.addWidget(self.test_button)
        connection_row.addWidget(self.connection_status, 1)
        form.addRow("连接状态", connection_row)
        actions = QHBoxLayout()
        for button in (self.new_button, self.save_button, self.delete_button):
            actions.addWidget(button)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addStretch()
        right.addLayout(actions)
        left = QVBoxLayout()
        list_title = QLabel("模型配置")
        list_title.setObjectName("sectionTitle")
        self.empty_hint = QLabel("暂无配置：在右侧填写服务信息后，点击“保存配置”。")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setWordWrap(True)
        left.addWidget(list_title)
        left.addWidget(self.empty_hint)
        left.addWidget(self.profiles, 1)
        left.addWidget(QLabel("DeepSeek 网页版 · 本机服务"))
        left.addWidget(self.web_start_button)
        left.addWidget(self.web_manage_button)
        left.addWidget(self.web_password_button)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(24)
        layout.addLayout(left, 1)
        layout.addLayout(right, 2)
        self._reload()
        for field in (self.name, self.base_url, self.endpoint_path, self.api_key):
            field.textChanged.connect(self._mark_edited)
        self.model.currentTextChanged.connect(self._mark_edited)
        self.timeout.valueChanged.connect(self._mark_edited)
        self.vision.stateChanged.connect(self._mark_edited)
        self.enabled.stateChanged.connect(self._mark_edited)

    def _start_web(self):
        self.web_start_button.setEnabled(False)
        self.connection_status.setText("正在启动本地服务…")
        self.web_worker = Worker(deepseek_web.start)
        self.web_worker.signals.succeeded.connect(self._web_started)
        self.web_worker.signals.failed.connect(self._web_failed)
        QThreadPool.globalInstance().start(self.web_worker)

    def _web_started(self, key):
        self.web_start_button.setEnabled(True)
        index = next((i for i, row in enumerate(self.rows) if row["name"] == "DeepSeek 网页版（本机）"
                      and row["base_url"] == f"{deepseek_web.ORIGIN}/v1"), None)
        if index is None:
            self._new()
        else:
            self.profiles.setCurrentRow(index)
        self.name.setText("DeepSeek 网页版（本机）")
        self.base_url.setText(f"{deepseek_web.ORIGIN}/v1")
        self.endpoint_path.setText("/chat/completions")
        self.model.setEditText("v4.1flash")
        self.api_key.setText(key)
        self.timeout.setValue(180)
        self.vision.setChecked(True)
        self.enabled.setChecked(True)
        if self._save():
            self.connection_status.setText("本地服务已启动，尚未验证网页账号。打开管理页，用户名 notebook；点击复制管理密码登录并添加网页 Token。")

    def _web_failed(self, error):
        self.web_start_button.setEnabled(True)
        self.connection_status.setText(str(error))

    def _copy_web_password(self):
        try:
            if not credentials.has_api_key(deepseek_web.KEY_REF):
                raise RuntimeError("请先启动网页版服务。")
            QApplication.clipboard().setText(credentials.get_api_key(deepseek_web.KEY_REF))
            self.connection_status.setText("管理密码已复制，管理页用户名：notebook。此密码用于本地服务。")
        except Exception as error:
            self.connection_status.setText(str(error))

    def _apply_screenshot_shortcut(self):
        sequence = self.screenshot_shortcut.keySequence()
        modifiers, key = GlobalScreenshotHotkey._native_combination(sequence)
        if sequence.count() != 1 or not modifiers or key is None:
            self.shortcut_status.setText("请设置一个带修饰键的按键组合（如 Ctrl+Alt+S）")
            self.shortcut_status.setStyleSheet("color:#b84d58;font-size:12px;")
            return
        shortcut = sequence.toString(QKeySequence.SequenceFormat.PortableText)
        settings = QSettings()
        settings.setValue("shortcuts/screenshot", shortcut)
        parent = self.parentWidget()
        while parent is not None and not hasattr(parent, "set_screenshot_shortcut"):
            parent = parent.parentWidget()
        registered = parent.set_screenshot_shortcut(shortcut) if parent else False
        if registered:
            self.shortcut_status.setText(f"已启用全局快捷键：{shortcut}")
            self.shortcut_status.setStyleSheet("color:#27734b;font-size:12px;")
        else:
            self.shortcut_status.setText(f"{shortcut} 当前仅在应用打开时可用，可能与其他快捷键冲突")
            self.shortcut_status.setStyleSheet("color:#a66a16;font-size:12px;")

    def _reload(self, selected_id=None):
        self.rows = store.list_profiles()
        self.empty_hint.setVisible(not self.rows)
        self.profiles.clear()
        for row in self.rows:
            self.profiles.addItem(f"{row['name']} · {row['model_id']}")
        index = next((i for i, row in enumerate(self.rows) if row["id"] == selected_id), 0)
        if self.rows:
            self.profiles.setCurrentRow(index)
        else:
            self._clear()

    def _clear(self):
        for field in (self.name, self.base_url, self.endpoint_path, self.api_key):
            field.clear()
        self.model.clear()
        self.model.setEditText("")
        self.endpoint_path.setText("/chat/completions")
        self.timeout.setValue(60)
        self.vision.setChecked(False)
        self.enabled.setChecked(True)
        self.test_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.connection_status.setText("尚未测试连接")
        self.connection_status.setStyleSheet(f"color:{MUTED};font-size:12px;")

    def _mark_edited(self, *_):
        self.connection_status.setText("配置已修改，请重新测试")
        self.connection_status.setStyleSheet("color:#a66a16;font-size:12px;")

    def _show_profile(self, index):
        if index < 0 or index >= len(self.rows):
            self._clear()
            return
        row = self.rows[index]
        self.name.setText(row["name"])
        self.base_url.setText(row["base_url"])
        self.endpoint_path.setText(row["endpoint_path"])
        self.model.setCurrentText(row["model_id"])
        self.api_key.clear()
        self.timeout.setValue(row["timeout_seconds"])
        self.vision.setChecked(bool(row["vision_enabled"]))
        self.enabled.setChecked(bool(row["enabled"]))
        self.test_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.connection_status.setText("尚未测试连接")
        self.connection_status.setStyleSheet(f"color:{MUTED};font-size:12px;")

    def _new(self):
        self.profiles.setCurrentRow(-1)
        self._clear()
        self.name.setFocus()

    def _current(self):
        index = self.profiles.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def _values(self):
        return {
            "name": self.name.text().strip(),
            "base_url": self.base_url.text().strip(),
            "endpoint_path": self.endpoint_path.text().strip(),
            "model_id": self.model.currentText().strip(),
            "timeout_seconds": self.timeout.value(),
            "vision_enabled": self.vision.isChecked(),
            "enabled": self.enabled.isChecked(),
        }

    def _save(self):
        values = self._values()
        row = self._current()
        profile_id = row["id"] if row else uuid4().hex
        key = self.api_key.text().strip()
        values["api_key_ref"] = profile_id
        try:
            validate_profile(values)
            if not key and (not row or not credentials.has_api_key(profile_id)):
                raise ValueError("请填写 API Key；已有配置可留空以保留已保存的密钥。")
        except Exception as error:
            self.connection_status.setText(str(error))
            self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;")
            return False
        try:
            if key:
                credentials.save_api_key(profile_id, key)
            store.save_profile(values, profile_id)
        except Exception as error:
            self.connection_status.setText(f"保存失败：{error}")
            self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;")
            return False
        self._reload(profile_id)
        return True

    def _test(self):
        row = self._current()
        if row is None:
            self.connection_status.setText("请先保存模型配置，再测试连接。")
            self.connection_status.setStyleSheet("color:#a66a16;font-size:12px;")
            return
        key = self.api_key.text().strip()
        try:
            if key:
                credentials.save_api_key(row["id"], key)
            if not self._save():
                return
        except Exception as error:
            self.connection_status.setText(f"保存失败：{error}")
            self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;")
            return
        row = self._current()
        if row is None:
            return
        try:
            profile = store.get_profile(row["id"])
            validate_profile(profile)
            self.test_button.setEnabled(False)
            self.connection_status.setText("正在连接…")
            self.connection_status.setStyleSheet(f"color:{ACCENT};font-size:12px;")
            self.worker = Worker(lambda: test_profile(profile))
            self.worker.signals.succeeded.connect(self._test_succeeded)
            self.worker.signals.failed.connect(self._test_failed)
            QThreadPool.globalInstance().start(self.worker)
        except Exception as error:
            self.test_button.setEnabled(True)
            self.connection_status.setText(f"连接失败：{error}")
            self.connection_status.setToolTip(str(error))
            self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;")

    def _fetch_models(self):
        row = self._current()
        api_key = self.api_key.text().strip()
        if not api_key and row is None:
            self.connection_status.setText("请先填写 API Key，才能获取模型列表。")
            self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;")
            return
        profile = self._values()
        profile["api_key_ref"] = row["api_key_ref"] if row else ""
        try:
            validate_profile(profile, require_model=False)
            if not api_key and not credentials.has_api_key(profile["api_key_ref"]):
                raise ValueError("此配置没有已保存的 API Key，请填写后再获取模型列表。")
        except Exception as error:
            self.connection_status.setText(str(error))
            self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;")
            return
        self.fetch_models_button.setEnabled(False)
        self.connection_status.setText("正在获取模型列表…")
        self.connection_status.setStyleSheet(f"color:{ACCENT};font-size:12px;")
        self.models_worker = Worker(lambda: list_models(profile, api_key or None))
        self.models_worker.signals.succeeded.connect(self._models_succeeded)
        self.models_worker.signals.failed.connect(self._models_failed)
        QThreadPool.globalInstance().start(self.models_worker)

    def _models_succeeded(self, models):
        self.fetch_models_button.setEnabled(True)
        self.connection_status.setText(f"获取到 {len(models)} 个模型")
        self.connection_status.setStyleSheet("color:#27734b;font-size:12px;font-weight:600;")
        selected = self.model.currentText()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(models)
        self.model.setCurrentText(selected if selected in models else models[0])
        self.model.blockSignals(False)

    def _models_failed(self, error):
        self.fetch_models_button.setEnabled(True)
        self.connection_status.setText(f"模型列表获取失败，可手动填写模型 ID：{error}")
        self.connection_status.setToolTip(str(error))
        self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;font-weight:600;")

    def _test_succeeded(self, response):
        self.test_button.setEnabled(True)
        self.connection_status.setText("连接成功")
        self.connection_status.setStyleSheet("color:#27734b;font-size:12px;font-weight:600;")
        self.connection_status.setToolTip(response[:500])

    def _test_failed(self, error):
        self.test_button.setEnabled(True)
        self.connection_status.setText(f"连接失败：{error}")
        self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;font-weight:600;")
        details = getattr(error, "raw_response", "")
        self.connection_status.setToolTip(details or str(error))

    def _delete(self):
        row = self._current()
        if row is None:
            return
        if QMessageBox.question(self, "删除配置", f"确定删除「{row['name']}」吗？") != QMessageBox.StandardButton.Yes:
            return
        try:
            store.delete_profile(row["id"])
            credentials.delete_api_key(row["api_key_ref"])
        except Exception as error:
            self.connection_status.setText(f"删除失败：{error}")
            self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;")
            return
        self._reload()
