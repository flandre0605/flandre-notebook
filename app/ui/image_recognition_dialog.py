import tempfile
import sqlite3
from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal, QSignalBlocker
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QStackedWidget, QVBoxLayout, QWidget, QPlainTextEdit, QMessageBox,
)

from app.database import store
from app.services import attachments
from app.services import recognition_drafts
from app.services.model_provider import ProviderError, parse_recognition_text, recognize_image
from app.ui.recognition_draft_dialog import RecognitionDraftDialog
from app.ui.worker import Worker
from app.ui.motion import AnimatedButton, ContentFade
from app.ui.theme import ICON_DIR, MUTED, TEXT
from app.ui.model_selection import fill_model_choices


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
    def __init__(self, image_path: str | Path | None = None, parent=None, auto_recognize=False, resume_key=None):
        super().__init__(parent)
        self.setWindowTitle("AI 图片识题")
        self.resize(760, 650)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self.image_path: Path | None = None
        self._clipboard_temp_dirs = []
        self._recognizing = False
        self._dismissed = False
        self.session_key = None
        self._draft_state = None
        self.draft_editor = None
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(600)
        self._autosave.timeout.connect(self.save_progress)
        self.drop_zone = ImageDropZone()
        self.drop_zone.image_dropped.connect(self.set_image)
        self.views = QStackedWidget()
        self.input_page = QWidget()
        self.profile = QComboBox()
        self.profiles = fill_model_choices(self.profile, "vision")
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
        self.recover_text_button = AnimatedButton('从文字响应恢复草稿')
        self.recover_text_button.setEnabled(False)
        self.recover_text_button.clicked.connect(self.recover_text)
        self.continue_draft = AnimatedButton("继续核对已保存草稿")
        self.continue_draft.clicked.connect(self._continue_draft)
        self.continue_draft.hide()
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
        response_actions = QHBoxLayout()
        response_actions.addWidget(self.details_button)
        response_actions.addWidget(self.recover_text_button)
        input_layout.addLayout(response_actions)
        input_layout.addWidget(self.response_details)
        input_layout.addWidget(self.continue_draft)
        input_layout.addLayout(actions)
        self.views.addWidget(self.input_page)
        self._motion = ContentFade(self)
        self.views.currentChanged.connect(lambda _: self._motion.play(self.views.currentWidget()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.views)
        recovery_row = QHBoxLayout()
        self.sessions = QComboBox()
        self.sessions.setMinimumContentsLength(15)
        self.sessions.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sessions.currentIndexChanged.connect(self._select_session)
        self.discard_button = AnimatedButton("舍弃这份草稿")
        self.discard_button.setObjectName("dangerButton")
        self.discard_button.clicked.connect(self.discard_draft)
        self.draft_status = QLabel("开始识题后，图片与草稿保存在本机，关闭后可继续核对。")
        self.draft_status.setObjectName("muted")
        self.draft_status.setWordWrap(True)
        self.draft_status.setTextFormat(Qt.TextFormat.PlainText)
        recovery_row.addWidget(self.sessions, 1)
        recovery_row.addWidget(self.discard_button)
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(24, 6, 24, 16)
        footer_layout.addWidget(self.draft_status)
        footer_layout.addLayout(recovery_row)
        layout.addWidget(footer)
        self._refresh_sessions()
        self.recognize_button.setEnabled(bool(self.profiles))
        self.profile.setEnabled(bool(self.profiles))
        if not self.profiles:
            self.status.setText("没有已启用的视觉模型，请先到「设置 → 模型服务」添加配置。")
        if image_path:
            self.set_image(str(image_path))
        if resume_key:
            self._load_session(resume_key)
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
        self.save_progress()
        self.session_key = self._draft_state = None
        self.continue_draft.hide()
        self.discard_button.setEnabled(False)
        self._refresh_sessions()
        self.image_path = None
        self.response_details.clear()
        self.response_details.hide()
        self.details_button.hide()
        self.details_button.setText('查看原始响应')
        self.recover_text_button.setEnabled(False)
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
        self.recover_text_button.setEnabled(True)

    def recognize(self):
        if self._recognizing or self._dismissed or self.views.currentWidget() is not self.input_page:
            return
        if self.image_path is None:
            self.status.setText("请先拖入、粘贴或选择一张题目图片。")
            return
        profile_id = self.profile.currentData()
        profile = store.get_profile(profile_id) if profile_id else None
        if profile is None or not profile["enabled"] or not profile["vision_enabled"]:
            self.profiles = fill_model_choices(self.profile, "vision")
            self._set_input_enabled(True)
            self.status.setText("所选配置已不可用，模型列表已刷新；请选择可用视觉模型后再开始。")
            return
        try:
            if self.session_key is None or (self._draft_state or {}).get("drafts"):
                # Re-recognition is a new task: never replace a user's reviewed draft or local notes.
                self._create_session(profile_id)
            self._draft_state["profile_id"] = profile_id
            self.save_progress()
            self._refresh_sessions()
        except (OSError, ValueError, sqlite3.Error) as error:
            self.status.setText(f"原图保存失败，尚未发送识题请求：{error}")
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
        try:
            if self.session_key is None:
                self._create_session(self.profile.currentData())
            self._draft_state.update(drafts=list(draft), current_index=0)
            if hasattr(draft, 'raw_response'):
                self._draft_state['raw_response'] = draft.raw_response
            recognition_drafts.save(self.session_key, self._draft_state)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.draft_status.setText(f"识题草稿保存失败：{error}。请保留窗口并及时收录。")
        self._set_input_enabled(True)
        self.response_details.setPlainText(getattr(draft, 'raw_response', (self._draft_state or {}).get('raw_response', '')))
        self.details_button.setVisible(bool(self.response_details.toPlainText()))
        self.status.setText("识别完成 · 请核对草稿")
        editor = RecognitionDraftDialog(None, self.image_path, draft, self)
        editor.setWindowFlags(Qt.WindowType.Widget)
        editor.save_requested.connect(lambda current=editor: self._save_draft(current))
        editor.rejected.connect(lambda current=editor: self._return_to_input(current))
        self.draft_editor = editor
        editor.content_changed.connect(lambda: self._autosave.start())
        self.views.addWidget(editor)
        self.views.setCurrentWidget(editor)
        self._refresh_sessions()
        available = self.screen().availableGeometry()
        self.resize(min(max(980, self.width()), available.width() - 32),
                    min(max(700, self.height()), available.height() - 64))
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _return_to_input(self, editor):
        self.save_progress()
        self.views.setCurrentWidget(self.input_page)
        self.views.removeWidget(editor)
        editor.deleteLater()
        self.draft_editor = None
        self.continue_draft.setVisible(bool(self._draft_state and self._draft_state.get("drafts")))

    def _save_draft(self, editor):
        if self._dismissed or self.draft_editor is not editor:
            return
        try:
            from app.services.mobile_inbox import InboxStore
            original = InboxStore(store.DATA_DIR, '').original_for_draft(self.session_key)
            question_ids = attachments.import_recognized_questions(editor.values(), self.image_path, self.session_key,
                                                                   [original] if original else [])
        except Exception as error:
            editor.validation_status.setText(f"收录失败：{error}。本次未写入题目，草稿保留。")
            self.status.setToolTip(str(error))
            return
        self._autosave.stop()
        if self.session_key:
            try:
                recognition_drafts.discard(self.session_key, self._draft_state)
            except (OSError, ValueError, sqlite3.Error):
                pass  # Formal rows are already committed; a leftover draft image must not trigger another import.
        self.session_key = self._draft_state = None
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
        if self._draft_state is not None:
            self._draft_state['raw_response'] = details
            self.save_progress()
        self.status.setToolTip(details or str(error))
        self.response_details.setPlainText(details)
        self.response_details.hide()
        self.details_button.setText("查看原始响应")
        self.details_button.setVisible(bool(details))

    def recover_text(self):
        if self._recognizing or self.image_path is None:
            self.status.setText('请先选择原题图片，再整理已有文字。')
            return
        content = self.response_details.toPlainText()
        if not content:
            from PySide6.QtWidgets import QInputDialog
            content, accepted = QInputDialog.getMultiLineText(self, '恢复题目文字',
                '粘贴已有的完整 JSON，或带“题目、解答、答案/结论”的单题文字。这里只在本机整理，不发送模型请求。',
                QApplication.clipboard().text())
            if not accepted:
                return
        try:
            if self.session_key is None or (self._draft_state or {}).get('drafts'):
                self._create_session(self.profile.currentData())
            draft = parse_recognition_text(content)
            self._recognized(draft)
            self.status.setText('已从文字恢复 · 请核对题干、答案与学科，确认后收录。')
        except (ProviderError, OSError, ValueError, sqlite3.Error) as error:
            self._failed(error)

    def _create_session(self, profile_id):
        from app.services.mobile_inbox import link_replacement_draft
        previous = self.session_key
        key, state, path = recognition_drafts.create(self.image_path, profile_id)
        try:
            link_replacement_draft(previous, key)
            if previous and self._draft_state:
                state['source_name'] = self._draft_state.get('source_name',state['source_name'])
                recognition_drafts.save(key,state)
        except Exception:
            recognition_drafts.discard(key,state)
            raise
        self.session_key, self._draft_state, self.image_path = key, state, path

    def _toggle_details(self):
        visible = self.response_details.isHidden()
        self.response_details.setVisible(visible)
        self.details_button.setText("收起原始响应" if visible else "查看原始响应")

    def _set_input_enabled(self, enabled):
        self.recognize_button.setEnabled(enabled and bool(self.profiles))
        self.choose_button.setEnabled(enabled)
        self.paste_button.setEnabled(enabled)
        self.profile.setEnabled(enabled and bool(self.profiles))
        self.recover_text_button.setEnabled(enabled and self.image_path is not None)
        self.drop_zone.setAcceptDrops(enabled)
        self.sessions.setEnabled(enabled)
        self.discard_button.setEnabled(enabled and self.session_key is not None)

    def save_progress(self):
        self._autosave.stop()
        if not self.session_key or not self._draft_state:
            return
        if self.draft_editor is not None:
            self._draft_state.update(drafts=self.draft_editor.values(), current_index=self.draft_editor.current_index)
        self._draft_state["profile_id"] = self.profile.currentData() or ""
        try:
            recognition_drafts.save(self.session_key, self._draft_state)
            self.draft_status.setText("识题草稿已自动保存，关闭后可从首页继续。")
        except (OSError, ValueError, sqlite3.Error) as error:
            self.draft_status.setText(f"识题草稿保存失败：{error}。请保留窗口并及时收录。")

    def _refresh_sessions(self):
        with QSignalBlocker(self.sessions):
            self.sessions.clear()
            self.sessions.addItem("选择已保存的识题草稿…", None)
            for key in recognition_drafts.keys():
                state = store.load_workspace(key) or {}
                self.sessions.addItem(f"{str(state.get('source_name', '图片'))[:80]} · {len(state.get('drafts', [])) if isinstance(state.get('drafts'), list) else 0} 道", key)
            self.sessions.setCurrentIndex(max(0, self.sessions.findData(self.session_key)))
        self.discard_button.setEnabled(self.session_key is not None and not self._recognizing)

    def _select_session(self, *_):
        key = self.sessions.currentData()
        if key and key != self.session_key and not self._recognizing:
            self._load_session(key)

    def _load_session(self, key):
        try:
            state, path = recognition_drafts.load(key)
            self.save_progress()
        except (OSError, ValueError, sqlite3.Error) as error:
            self.draft_status.setText(f"草稿无法恢复：{error}。请保留备份或重新选择图片。")
            return
        if self.draft_editor is not None:
            self._return_to_input(self.draft_editor)
        self.session_key, self._draft_state, self.image_path = key, state, path
        self.response_details.setPlainText(state.get('raw_response', ''))
        self.details_button.setVisible(bool(state.get('raw_response')))
        self.recover_text_button.setEnabled(True)
        self.drop_zone.set_image(path)
        self.profile.setCurrentIndex(max(0, self.profile.findData(state["profile_id"])))
        self.status.setText("已恢复上次图片；点击开始识题才会发送请求。")
        self.recognize_button.setEnabled(bool(self.profiles))
        if state["drafts"]:
            index = state["current_index"]
            self._recognized(state["drafts"])
            self.draft_editor.question_selector.setCurrentIndex(index)
        self._refresh_sessions()

    def _continue_draft(self):
        if self.session_key and self._draft_state and self._draft_state["drafts"]:
            self._load_session(self.session_key)

    def discard_draft(self):
        if not self.session_key or self._recognizing:
            return
        if QMessageBox.question(self, "舍弃识题草稿", "舍弃这份未收录的草稿和图片副本？已保存的题目不受影响。") != QMessageBox.StandardButton.Yes:
            return
        try:
            cleaned = recognition_drafts.discard(self.session_key, self._draft_state)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.draft_status.setText(f"舍弃失败：{error}")
            return
        self._autosave.stop()
        self.session_key = self._draft_state = None
        if self.draft_editor is not None:
            self._return_to_input(self.draft_editor)
        self.image_path = None
        self.drop_zone.clear_image()
        self.continue_draft.hide()
        self.draft_status.setText("草稿已舍弃。" if cleaned else "草稿已舍弃，图片副本未能清理，可稍后清理。")
        self._refresh_sessions()

    def abandon_for_restore(self):
        self._autosave.stop()
        self.session_key = self._draft_state = None
        self.reject()

    def done(self, result):
        self.save_progress()
        self._motion.finish()
        self._dismissed = True
        if self._recognizing:
            # ponytail: urllib 请求不能中断；先隐藏，返回/超时后释放截图与窗口。
            self._pending_result = result
            self.hide()
            return
        super().done(result)
