import tempfile
from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from app.database import store
from app.services import attachments
from app.services.model_provider import recognize_image
from app.ui.recognition_draft_dialog import RecognitionDraftDialog
from app.ui.worker import Worker


class ImageDropZone(QFrame):
    image_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumSize(460, 320)
        self.setStyleSheet(
            "QFrame{background:#fff;border:2px dashed #cbd5e3;border-radius:14px;}"
        )
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.placeholder)
        placeholder_layout.setContentsMargins(24, 24, 24, 24)
        placeholder_layout.setSpacing(8)
        icon = QLabel("▧")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("border:0;color:#7890c7;font-size:34px;")
        title = QLabel("把题目图片拖到这里")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("border:0;color:#34435c;font-size:16px;font-weight:700;")
        hint = QLabel("支持 PNG、JPG、WEBP · 也可以粘贴剪贴板图片")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("border:0;color:#8a96a8;font-size:12px;")
        placeholder_layout.addStretch()
        placeholder_layout.addWidget(icon)
        placeholder_layout.addWidget(title)
        placeholder_layout.addWidget(hint)
        placeholder_layout.addStretch()
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.placeholder)
        self.preview_stack.addWidget(self.preview)
        layout = QVBoxLayout(self)
        layout.addWidget(self.preview_stack)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
            self.setStyleSheet("QFrame{background:#f5f8ff;border:2px dashed #6d91e8;border-radius:14px;}")
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("QFrame{background:#fff;border:2px dashed #cbd5e3;border-radius:14px;}")
        event.accept()

    def dropEvent(self, event):
        self.setStyleSheet("QFrame{background:#fff;border:2px dashed #cbd5e3;border-radius:14px;}")
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.image_dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()

    def set_image(self, path: Path):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.preview.setText(path.name)
            self.preview_stack.setCurrentWidget(self.preview)
            return
        self.preview.setPixmap(
            pixmap.scaled(
                600,
                440,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview_stack.setCurrentWidget(self.preview)
        self.preview.setToolTip(str(path))

    def clear_image(self):
        self.preview.setPixmap(QPixmap())
        self.preview.setText("")
        self.preview.setToolTip("")
        self.preview_stack.setCurrentWidget(self.placeholder)


class ImageRecognitionDialog(QDialog):
    def __init__(self, image_path: str | Path | None = None, parent=None, auto_recognize=False):
        super().__init__(parent)
        self.setWindowTitle("AI 图片识题")
        self.resize(760, 650)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self.image_path: Path | None = None
        self._clipboard_temp_dirs = []
        self.drop_zone = ImageDropZone()
        self.drop_zone.image_dropped.connect(self.set_image)
        self.profile = QComboBox()
        self.profiles = store.list_profiles(enabled_only=True)
        self.profiles = [profile for profile in self.profiles if profile["vision_enabled"]]
        for profile in self.profiles:
            self.profile.addItem(f"{profile['name']} · {profile['model_id']}", profile["id"])
        self.choose_button = QPushButton("选择图片…")
        self.choose_button.clicked.connect(self.choose_image)
        self.paste_button = QPushButton("粘贴图片（Ctrl+V）")
        self.paste_button.clicked.connect(self.paste_image)
        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        paste_shortcut.activated.connect(self.paste_image)
        self.recognize_button = QPushButton("开始识题")
        self.recognize_button.setObjectName("primaryButton")
        self.recognize_button.clicked.connect(self.recognize)
        self.status = QLabel("选择或拖入题目图片，再选择视觉模型。")
        self.status.setStyleSheet("color:#7b8799;font-size:12px;")
        heading = QLabel("整理纸上的错题")
        heading.setStyleSheet("color:#17243a;font-size:22px;font-weight:700;")
        subtitle = QLabel("导入题目图片，AI 会按题目拆分并生成可编辑草稿。")
        subtitle.setStyleSheet("color:#8490a3;font-size:12px;")
        actions = QHBoxLayout()
        actions.addWidget(self.profile, 1)
        actions.addWidget(self.paste_button)
        actions.addWidget(self.choose_button)
        actions.addWidget(self.recognize_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addWidget(self.drop_zone, 1)
        layout.addWidget(self.status)
        layout.addLayout(actions)
        self.recognize_button.setEnabled(bool(self.profiles))
        self.profile.setEnabled(bool(self.profiles))
        if not self.profiles:
            self.status.setText("没有已启用的视觉模型，请先到「设置 → 模型服务」添加配置。")
        if image_path:
            self.set_image(str(image_path))
        if auto_recognize:
            QTimer.singleShot(0, self.recognize)

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择题目图片", "", "图片 (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            self.set_image(path)

    def paste_image(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasImage():
            image = clipboard.image()
            if image.isNull():
                self.status.setText("剪贴板里没有可读取的图片。")
                return
            temporary = tempfile.TemporaryDirectory(prefix="mistake-notebook-image-")
            path = Path(temporary.name) / "clipboard.png"
            if not image.save(str(path), "PNG"):
                temporary.cleanup()
                QMessageBox.warning(self, "粘贴失败", "无法读取剪贴板中的图片。")
                return
            self._clipboard_temp_dirs.append(temporary)
            self.set_image(str(path))
            return
        if mime_data.hasUrls():
            path = next((url.toLocalFile() for url in mime_data.urls() if url.isLocalFile()), "")
            if path:
                self.set_image(path)
                return
        self.status.setText("剪贴板里没有图片或图片文件。")

    def set_image(self, path: str):
        self.image_path = None
        self.recognize_button.setEnabled(False)
        self.drop_zone.clear_image()
        try:
            self.image_path = attachments.validate_image(path)
        except (OSError, ValueError) as error:
            self.status.setText(f"图片不可用：{error}")
            return
        self.drop_zone.set_image(self.image_path)
        self.status.setText(f"已选择：{self.image_path.name}")
        self.recognize_button.setEnabled(bool(self.profiles))

    def recognize(self):
        if self.image_path is None:
            self.status.setText("请先拖入、粘贴或选择一张题目图片。")
            return
        profile_id = self.profile.currentData()
        profile = store.get_profile(profile_id) if profile_id else None
        if profile is None:
            self.status.setText("没有可用的视觉模型，请先到设置中启用一个视觉模型。")
            return
        self.recognize_button.setEnabled(False)
        self.choose_button.setEnabled(False)
        self.profile.setEnabled(False)
        self.status.setText(f"正在使用 {profile['name']} 识别图片…")
        image_path = self.image_path
        self.worker = Worker(lambda: recognize_image(profile, image_path))
        self.worker.signals.succeeded.connect(self._recognized)
        self.worker.signals.failed.connect(self._failed)
        QThreadPool.globalInstance().start(self.worker)

    def _recognized(self, draft):
        self.recognize_button.setEnabled(True)
        self.choose_button.setEnabled(True)
        self.profile.setEnabled(bool(self.profiles))
        self.status.setText("识别完成 · 请核对草稿")
        editor = RecognitionDraftDialog(None, self.image_path, draft, self)
        editor.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        editor.accepted.connect(lambda current=editor: self._save_draft(current))
        editor.show()
        editor.raise_()
        editor.activateWindow()

    def _save_draft(self, editor):
        question_ids = []
        try:
            for values in editor.values():
                question_id = store.save_question(values)
                question_ids.append(question_id)
                # ponytail: copy the source image per question; share attachment storage if duplication becomes material.
                attachments.import_image(question_id, self.image_path)
        except Exception as error:
            cleanup_errors = []
            for question_id in question_ids:
                try:
                    cleanup_errors.extend(attachments.delete_question_images(question_id))
                except Exception as cleanup_error:
                    cleanup_errors.append(str(cleanup_error))
            detail = f"\n清理失败：{'；'.join(cleanup_errors)}" if cleanup_errors else ""
            self.status.setText(f"收录失败：{error}{detail}")
            self.status.setToolTip(str(error))
            return
        self.status.setText(f"已收录 {len(question_ids)} 道题，原图已保存为题目附件。")
        self.accept()

    def _failed(self, error):
        self.recognize_button.setEnabled(True)
        self.choose_button.setEnabled(True)
        self.profile.setEnabled(bool(self.profiles))
        self.status.setText(f"识题失败：{error}")
        details = getattr(error, "raw_response", "")
        self.status.setToolTip(details or str(error))
