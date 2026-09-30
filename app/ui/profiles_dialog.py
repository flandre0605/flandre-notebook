from uuid import uuid4

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QInputDialog, QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from app.database import store
from app.services import credentials
from app.services.model_provider import list_models, test_profile, validate_profile
from app.ui.worker import Worker


class ProfilesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("模型服务配置")
        self.resize(720, 480)
        self.profiles = QListWidget()
        self.profiles.currentRowChanged.connect(self._show_profile)
        self.name = QLineEdit()
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://中转站域名/v1")
        self.endpoint_path = QLineEdit("/chat/completions")
        self.endpoint_path.setPlaceholderText("/chat/completions")
        self.endpoint_path.setToolTip("中转站自定义的 OpenAI 兼容接口路径；通常为 /chat/completions")
        self.model = QLineEdit()
        self.fetch_models_button = QPushButton("获取模型列表")
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
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self._test)
        self.connection_status = QLabel("尚未测试连接")
        self.connection_status.setStyleSheet("color:#7b8799;font-size:12px;")
        self.new_button = QPushButton("新增")
        self.save_button = QPushButton("保存配置")
        self.delete_button = QPushButton("删除")
        self.new_button.clicked.connect(self._new)
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)

        form = QFormLayout()
        form.addRow("显示名称", self.name)
        form.addRow("API 基础地址", self.base_url)
        form.addRow("API 请求路径", self.endpoint_path)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.fetch_models_button)
        form.addRow("模型 ID", model_row)
        form.addRow("API Key", self.api_key)
        form.addRow("超时", self.timeout)
        form.addRow("能力", self.vision)
        form.addRow("状态", self.enabled)
        connection_row = QHBoxLayout()
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
        layout = QHBoxLayout(self)
        layout.addWidget(self.profiles, 1)
        layout.addLayout(right, 2)
        self._reload()
        for field in (self.name, self.base_url, self.endpoint_path, self.model, self.api_key):
            field.textChanged.connect(self._mark_edited)
        self.timeout.valueChanged.connect(self._mark_edited)
        self.vision.stateChanged.connect(self._mark_edited)
        self.enabled.stateChanged.connect(self._mark_edited)

    def _reload(self, selected_id=None):
        self.rows = store.list_profiles()
        self.profiles.clear()
        for row in self.rows:
            self.profiles.addItem(f"{row['name']} · {row['model_id']}")
        index = next((i for i, row in enumerate(self.rows) if row["id"] == selected_id), 0)
        if self.rows:
            self.profiles.setCurrentRow(index)
        else:
            self._clear()

    def _clear(self):
        for field in (self.name, self.base_url, self.endpoint_path, self.model, self.api_key):
            field.clear()
        self.endpoint_path.setText("/chat/completions")
        self.timeout.setValue(60)
        self.vision.setChecked(False)
        self.enabled.setChecked(True)
        self.test_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.connection_status.setText("尚未测试连接")
        self.connection_status.setStyleSheet("color:#7b8799;font-size:12px;")

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
        self.model.setText(row["model_id"])
        self.api_key.clear()
        self.timeout.setValue(row["timeout_seconds"])
        self.vision.setChecked(bool(row["vision_enabled"]))
        self.enabled.setChecked(bool(row["enabled"]))
        self.test_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.connection_status.setText("尚未测试连接")
        self.connection_status.setStyleSheet("color:#7b8799;font-size:12px;")

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
            "model_id": self.model.text().strip(),
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
            QMessageBox.warning(self, "配置校验未通过", str(error))
            return False
        try:
            if key:
                credentials.save_api_key(profile_id, key)
            store.save_profile(values, profile_id)
        except Exception as error:
            QMessageBox.critical(self, "保存失败", str(error))
            return False
        self._reload(profile_id)
        return True

    def _test(self):
        row = self._current()
        if row is None:
            QMessageBox.information(self, "先保存配置", "请先保存模型配置，再测试连接。")
            return
        key = self.api_key.text().strip()
        try:
            if key:
                credentials.save_api_key(row["id"], key)
            if not self._save():
                return
        except Exception as error:
            QMessageBox.critical(self, "保存失败", str(error))
            return
        row = self._current()
        if row is None:
            return
        try:
            profile = store.get_profile(row["id"])
            validate_profile(profile)
            self.test_button.setEnabled(False)
            self.connection_status.setText("正在连接…")
            self.connection_status.setStyleSheet("color:#4169d8;font-size:12px;")
            self.worker = Worker(lambda: test_profile(profile))
            self.worker.signals.succeeded.connect(self._test_succeeded)
            self.worker.signals.failed.connect(self._test_failed)
            QThreadPool.globalInstance().start(self.worker)
        except Exception as error:
            self.test_button.setEnabled(True)
            QMessageBox.critical(self, "连接失败", str(error))

    def _fetch_models(self):
        row = self._current()
        api_key = self.api_key.text().strip()
        if not api_key and row is None:
            QMessageBox.warning(self, "缺少 API Key", "请先填写 API Key，才能获取模型列表。")
            return
        profile = self._values()
        profile["api_key_ref"] = row["api_key_ref"] if row else ""
        try:
            validate_profile(profile, require_model=False)
            if not api_key and not credentials.has_api_key(profile["api_key_ref"]):
                raise ValueError("此配置没有已保存的 API Key，请填写后再获取模型列表。")
        except Exception as error:
            QMessageBox.warning(self, "配置校验未通过", str(error))
            return
        self.fetch_models_button.setEnabled(False)
        self.connection_status.setText("正在获取模型列表…")
        self.connection_status.setStyleSheet("color:#4169d8;font-size:12px;")
        self.models_worker = Worker(lambda: list_models(profile, api_key or None))
        self.models_worker.signals.succeeded.connect(self._models_succeeded)
        self.models_worker.signals.failed.connect(self._models_failed)
        QThreadPool.globalInstance().start(self.models_worker)

    def _models_succeeded(self, models):
        self.fetch_models_button.setEnabled(True)
        self.connection_status.setText(f"获取到 {len(models)} 个模型")
        self.connection_status.setStyleSheet("color:#27734b;font-size:12px;font-weight:600;")
        model, accepted = QInputDialog.getItem(
            self, "选择模型", "选择一个模型 ID：", models, 0, False
        )
        if accepted:
            self.model.setText(model)

    def _models_failed(self, error):
        self.fetch_models_button.setEnabled(True)
        self.connection_status.setText("模型列表获取失败")
        self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;font-weight:600;")
        QMessageBox.warning(
            self,
            "获取模型列表失败",
            f"{error}\n\n部分中转站不开放模型列表接口；这种情况下仍可手动填写模型 ID。",
        )

    def _test_succeeded(self, response):
        self.test_button.setEnabled(True)
        self.connection_status.setText("连接成功")
        self.connection_status.setStyleSheet("color:#27734b;font-size:12px;font-weight:600;")
        QMessageBox.information(self, "连接成功", f"模型服务已返回：{response[:200]}")

    def _test_failed(self, error):
        self.test_button.setEnabled(True)
        self.connection_status.setText("连接失败，请检查配置")
        self.connection_status.setStyleSheet("color:#b84d58;font-size:12px;font-weight:600;")
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("连接失败")
        message.setText(str(error))
        details = getattr(error, "raw_response", "")
        if details:
            message.setDetailedText(details)
        message.exec()

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
            QMessageBox.critical(self, "删除失败", str(error))
            return
        self._reload()
