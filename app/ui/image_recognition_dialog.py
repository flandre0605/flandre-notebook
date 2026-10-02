import tempfile
from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QStackedWidget, QVBoxLayout, QWidget, QPlainTextEdit,
)

from app.database import store
from app.services import attachments
from app.services.model_provider import recognize_image
from app.ui.recognition_draft_dialog import RecognitionDraftDialog
from app.ui.worker import Worker
from app.ui.motion import AnimatedButton, ContentFade
from app.ui.theme import ICON_DIR, MUTED, TEXT


class ImageDropZone(QFrame):
    image_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumSize(460, 320)
        self.setObjectName("imageDropZone")
        self.setProperty("dragging", False)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.placeholder)
        placeholder_layout.setContentsMargins(24, 24, 24, 24)
        placeholder_layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(QPixmap(f"{ICON_DIR}/image.svg").scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        icon.setFixedSize(64, 64)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("background:#fbe8f0;border:1px solid #ecd5df;border-radius:16px;")
        title = QLabel("把题目图片拖到这里")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color:{TEXT};font-size:16px;font-weight:700;")
        hint = QLabel("支持 PNG、JPG、WEBP · 也可以粘贴剪贴板图片")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color:{MUTED};font-size:12px;")
        placeholder_layout.addStretch()
        placeholder_layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignHCenter)
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
            self._set_dragging(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_dragging(False)
        event.accept()

    def dropEvent(self, event):
        self._set_dragging(False)
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.image_dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()

    def _set_dragging(self, dragging):
        self.setProperty("dragging", dragging)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

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
        self._recognizing = False
        self._dismissed = False
        self.drop_zone = ImageDropZone()
        self.drop_zone.image_dropped.connect(self.set_image)
        self.views = QStackedWidget()
        self.input_page = QWidget()
        self.profile = QComboBox()
        self.profiles = store.list_profiles(enabled_only=True)
        self.profiles = [profile for profile in self.profiles if profile["vision_enabled"]]
        for profile in self.profiles:
            self.profile.addItem(f"{profile['name']} · {profile['model_id']}", profile["id"])
        self.choose_button = AnimatedButton("选择图片…")
        self.choose_button.clicked.connect(self.choose_image)
        self.paste_button = AnimatedButton("粘贴图片（Ctrl+V）")
        self.paste_button.clicked.connect(self.paste_image)
        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        paste_shortcut.activated.connect(self.paste_image)
        self.recognize_button = AnimatedButton("开始识题")
        self.recognize_button.setObjectName("primaryButton")
        self.recognize_button.clicked.connect(self.recognize)
        self.status = QLabel("选择或拖入题目图片，再选择视觉模型。")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.response_details = QPlainTextEdit()
        self.response_details.setReadOnly(True)
        self.response_details.setMaximumHeight(160)
        self.response_details.setPlaceholderText("模型原始响应")
        self.response_details.hide()
        self.details_button = AnimatedButton("查看原始响应")
        self.details_button.hide()
        self.details_button.clicked.connect(self._toggle_details)
        heading = QLabel("整理纸上的错题")
        heading.setObjectName("pageTitle")
        heading.setStyleSheet("font-size:22px;font-weight:700;")
        subtitle = QLabel("导入题目图片，AI 会按题目拆分并生成可编辑草稿。")
        subtitle.setObjectName("muted")
        actions = QHBoxLayout()
        actions.addWidget(self.profile, 1)
        actions.addWidget(self.paste_button)
        actions.addWidget(self.choose_button)
        actions.addWidget(self.recognize_button)
        input_layout = QVBoxLayout(self.input_page)
        input_layout.setContentsMargins(24, 20, 24, 20)
        input_layout.setSpacing(14)
        input_layout.addWidget(heading)
        input_layout.addWidget(subtitle)
        input_layout.addWidget(self.drop_zone, 1)
        input_layout.addWidget(self.status)
        input_layout.addWidget(self.details_button)
        input_layout.addWidget(self.response_details)
        input_layout.addLayout(actions)
        self.views.addWidget(self.input_page)
        self._motion = ContentFade(self)
        self.views.currentChanged.connect(lambda _: self._motion.play(self.views.currentWidget()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.views)
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
        if self._recognizing or self.views.currentWidget() is not self.input_page:
            return
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
                self.status.setText("粘贴失败：无法读取剪贴板中的图片。")
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
        if self._recognizing or self.views.currentWidget() is not self.input_page:
            return
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
        if self._recognizing or self._dismissed or self.views.currentWidget() is not self.input_page:
            return
        if self.image_path is None:
            self.status.setText("请先拖入、粘贴或选择一张题目图片。")
            return
        profile_id = self.profile.currentData()
        profile = store.get_profile(profile_id) if profile_id else None
        if profile is None:
            self.status.setText("没有可用的视觉模型，请先到设置中启用一个视觉模型。")
            return
        self._recognizing = True
        self.details_button.hide()
        self.response_details.hide()
        self.response_details.clear()
        self._set_input_enabled(False)
        self.status.setText(f"正在使用 {profile['name']} 识别图片…")
        image_path = self.image_path
        self.worker = Worker(lambda: recognize_image(profile, image_path))
        self.worker.signals.succeeded.connect(self._recognized)
        self.worker.signals.failed.connect(self._failed)
        QThreadPool.globalInstance().start(self.worker)

    def _recognized(self, draft):
        self._recognizing = False
        if self._dismissed:
            self.done(self._pending_result)
            return
        self._set_input_enabled(True)
        self.status.setText("识别完成 · 请核对草稿")
        editor = RecognitionDraftDialog(None, self.image_path, draft, self)
        editor.setWindowFlags(Qt.WindowType.Widget)
        editor.save_requested.connect(lambda current=editor: self._save_draft(current))
        editor.rejected.connect(lambda current=editor: self._return_to_input(current))
        self.draft_editor = editor
        self.views.addWidget(editor)
        self.views.setCurrentWidget(editor)
        available = self.screen().availableGeometry()
        self.resize(min(max(980, self.width()), available.width() - 32),
                    min(max(700, self.height()), available.height() - 64))
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _return_to_input(self, editor):
        self.views.setCurrentWidget(self.input_page)
        self.views.removeWidget(editor)
        editor.deleteLater()
        self.draft_editor = None

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
        editor.accept()
        self.accept()

    def _failed(self, error):
        self._recognizing = False
        if self._dismissed:
            self.done(self._pending_result)
            return
        self._set_input_enabled(True)
        self.status.setText(f"识题失败：{error}")
        details = getattr(error, "raw_response", "")
        self.status.setToolTip(details or str(error))
        self.response_details.setPlainText(details)
        self.response_details.hide()
        self.details_button.setText("查看原始响应")
        self.details_button.setVisible(bool(details))

    def _toggle_details(self):
        visible = self.response_details.isHidden()
        self.response_details.setVisible(visible)
        self.details_button.setText("收起原始响应" if visible else "查看原始响应")

    def _set_input_enabled(self, enabled):
        self.recognize_button.setEnabled(enabled and bool(self.profiles))
        self.choose_button.setEnabled(enabled)
        self.paste_button.setEnabled(enabled)
        self.profile.setEnabled(enabled and bool(self.profiles))
        self.drop_zone.setAcceptDrops(enabled)

    def done(self, result):
        self._motion.finish()
        self._dismissed = True
        if self._recognizing:
            # ponytail: urllib 请求不能中断；先隐藏，返回/超时后释放截图与窗口。
            self._pending_result = result
            self.hide()
            return
        super().done(result)
