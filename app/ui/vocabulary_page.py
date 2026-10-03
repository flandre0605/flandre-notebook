import csv
from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt, Signal, QSignalBlocker, QThreadPool, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox,
    QStackedWidget, QStyle, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.database import store, vocabulary
from app.services.model_provider import ProviderError, validate_profile
from app.services.vocabulary_translation import translate_words
from app.ui.motion import AnimatedButton
from app.ui.pronunciation import Pronunciation
from app.ui.theme import ACCENT, MUTED
from app.ui.worker import Worker


class WordStudy(QWidget):
    content_changed = Signal()
    back_requested = Signal()
    pronounce_requested = Signal(str)
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.words = []
        self._restoring = False
        self._checkpoint = QTimer(self)
        self._checkpoint.setSingleShot(True)
        self._checkpoint.setInterval(600)
        self._checkpoint.timeout.connect(self.save_progress)
        self.progress = QLabel()
        self.progress.setObjectName("badge")
        self.progress.setWordWrap(True)
        self.progress.setTextFormat(Qt.TextFormat.PlainText)
        back = AnimatedButton("返回单词本")
        back.clicked.connect(self.back_requested.emit)
        header = QHBoxLayout()
        header.addWidget(self.progress)
        header.addStretch()
        header.addWidget(back)
        self.pronounce = AnimatedButton("发音")
        self.pronounce.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.pronounce.clicked.connect(self.speak)
        self.auto_speak = QCheckBox("翻卡自动发音")
        speech = QHBoxLayout()
        speech.addStretch()
        speech.addWidget(self.pronounce)
        speech.addWidget(self.auto_speak)
        speech.addStretch()
        self.caption = QLabel()
        self.caption.setObjectName("muted")
        self.face = QLabel()
        self.face.setObjectName("wordFace")
        self.face.setMinimumHeight(100)
        self.phonetic = QLabel()
        self.phonetic.setFont(QFont("Segoe UI", 11))
        self.phonetic.setObjectName("muted")
        self.solution = QLabel()
        self.solution.setObjectName("wordMeaning")
        self.example = QLabel()
        self.example.setObjectName("muted")
        for label in (self.caption, self.face, self.phonetic, self.solution, self.example):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.answer = QLineEdit()
        self.answer.setMaxLength(100)
        self.answer.setPlaceholderText("输入英文单词，按 Enter 检查拼写")
        self.answer.returnPressed.connect(self.reveal)
        self.answer.textChanged.connect(lambda: self._checkpoint.start() if not self._restoring else None)
        self.reveal_button = AnimatedButton("显示释义")
        self.reveal_button.setObjectName("primaryButton")
        self.reveal_button.clicked.connect(self.reveal)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.forgot = AnimatedButton("没记住")
        self.hard = AnimatedButton("还不熟")
        self.known = AnimatedButton("记住了")
        self.known.setObjectName("primaryButton")
        self.hard.setObjectName("softButton")
        self.forgot.clicked.connect(lambda: self.record("forgot"))
        self.hard.clicked.connect(lambda: self.record("hard"))
        self.known.clicked.connect(lambda: self.record("known"))
        ratings = QHBoxLayout()
        for button in (self.forgot, self.hard, self.known):
            ratings.addWidget(button)
        card = QFrame()
        card.setObjectName("formCard")
        card.setMinimumWidth(600)
        card.setMaximumWidth(740)
        content = QVBoxLayout(card)
        content.setContentsMargins(32, 30, 32, 30)
        content.setSpacing(20)
        for widget in (self.caption, self.face, self.phonetic, self.answer,
                       self.reveal_button, self.solution, self.example, self.status):
            content.addWidget(widget)
        content.addLayout(ratings)
        content.addLayout(speech)
        wrapper = QWidget()
        wrapper.setObjectName("wordStudyCanvas")
        wrapper.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        centered = QVBoxLayout(wrapper)
        centered.setContentsMargins(0, 16, 0, 16)
        centered.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        centered.addStretch()
        scroll = QScrollArea()
        scroll.setObjectName("wordStudyScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(wrapper)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)

    def begin(self, words, mode, resume=None):
        self.words = [dict(word) for word in words]
        self.mode = mode
        self.index = self.remembered = 0
        self._restoring = bool(resume)
        if resume:
            self.index, self.remembered = resume["index"], resume["remembered"]
        self.show_card()
        if resume:
            self.answer.setText(resume["answer"])
            if resume["revealed"]:
                self.reveal()
        self._restoring = False
        self.save_progress()

    def session_state(self):
        word = self.words[self.index]
        return dict(ids=[row["id"] for row in self.words], index=self.index, mode=self.mode,
                    remembered=self.remembered, answer=self.answer.text(), revealed=self.revealed,
                    word_content=[word[key] for key in ("word", "meaning", "phonetic", "example")])

    def save_progress(self):
        self._checkpoint.stop()
        if self._restoring or not self.words or self.index >= len(self.words):
            return
        try:
            store.save_workspace("vocabulary:study", self.session_state())
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(f"背诵进度保存失败：{error}")

    def show_card(self):
        self.stop_requested.emit()
        self.revealed = False
        self.correct = None
        self.status.clear()
        self.answer.clear()
        self.answer.setReadOnly(False)
        for widget in (self.solution, self.example, self.forgot, self.hard, self.known):
            widget.hide()
        if self.index >= len(self.words):
            self.pronounce.hide()
            self.auto_speak.hide()
            self.progress.setText("本轮完成")
            self.caption.setText("每一次回忆，都在巩固记忆")
            self.face.setText(f"已复习 {len(self.words)} 个单词")
            self.phonetic.setText(f"记住了 {self.remembered} 个 · 其余可在到期复习中继续巩固")
            self.phonetic.show()
            self.answer.hide()
            self.reveal_button.hide()
        else:
            word = self.words[self.index]
            spelling = self.mode == "spelling"
            self.progress.setText(f"{self.index + 1} / {len(self.words)} · {word['book'] or '未分组'}")
            self.caption.setText("看释义，回忆英文拼写" if spelling else "看英文，先回忆释义再翻卡")
            self.face.setText(word["meaning"] if spelling else word["word"])
            self.phonetic.setText(word["phonetic"])
            self.phonetic.setVisible(not spelling and bool(word["phonetic"]))
            self.answer.setVisible(spelling)
            self.reveal_button.setText("检查拼写" if spelling else "显示释义")
            self.reveal_button.show()
            self.pronounce.setVisible(not spelling)
            self.auto_speak.show()
            if not spelling and self.auto_speak.isChecked() and not self._restoring:
                self.speak()
            if spelling:
                self.answer.setFocus()
        self.content_changed.emit()
        if not self._restoring:
            self.save_progress()

    def reveal(self):
        if self.revealed or self.index >= len(self.words):
            return
        word = self.words[self.index]
        if self.mode == "spelling":
            if not self.answer.text().strip():
                self.status.setText("先输入英文单词，再检查拼写。")
                return
            self.correct = vocabulary.normalize_word(self.answer.text()).casefold() == word["word"].casefold()
            self.status.setText("拼写正确" if self.correct else "拼写不一致，请对照答案再记一次。")
            self.status.setStyleSheet(f"color:{ACCENT if self.correct else '#b84d58'};font-weight:600;")
        else:
            self.status.setText("按本次回忆情况选择掌握程度，记录后进入下一个单词。")
            self.status.setStyleSheet(f"color:{MUTED};")
        self.revealed = True
        self.solution.setText(f"{word['word']}\n\n{word['meaning']}" if self.mode == "spelling" else word["meaning"])
        self.solution.show()
        self.example.setText(word["example"])
        self.example.setVisible(bool(word["example"]))
        self.answer.setReadOnly(True)
        self.reveal_button.hide()
        self.forgot.setText("记录并继续" if self.correct is False else "没记住")
        self.forgot.show()
        self.hard.setVisible(self.correct is not False)
        self.known.setVisible(self.correct is not False)
        self.pronounce.show()
        self.phonetic.setVisible(bool(word["phonetic"]))
        if self.mode == "spelling" and self.auto_speak.isChecked() and not self._restoring:
            self.speak()
        self.content_changed.emit()
        if not self._restoring:
            self.save_progress()

    def speak(self):
        if self.index < len(self.words) and (self.mode != "spelling" or self.revealed):
            self.pronounce_requested.emit(self.words[self.index]["word"])

    def record(self, rating):
        if not self.revealed or self.index >= len(self.words):
            return
        if self.correct is False:
            rating = "forgot"
        try:
            next_state = self.session_state()
            next_state.update(index=self.index + 1, remembered=self.remembered + int(rating == "known"),
                              answer="", revealed=False)
            if self.index + 1 < len(self.words):
                next_state["word_content"] = [self.words[self.index + 1][key] for key in ("word", "meaning", "phonetic", "example")]
            vocabulary.record_review(self.words[self.index]["id"], rating, session_state=next_state)
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(f"保存失败，未进入下一词：{error}")
            return
        self.remembered += rating == "known"
        self.index += 1
        self._checkpoint.stop()
        self.show_card()

    def resume(self):
        state = store.load_workspace("vocabulary:study")
        if not state:
            return False
        try:
            ids, index = state["ids"], state["index"]
            if not isinstance(ids, list) or not 1 <= len(ids) <= 200 or any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != len(ids):
                raise ValueError("队列无效")
            if type(index) is not int or not 0 <= index < len(ids) or state["mode"] not in ("card", "spelling"):
                raise ValueError("队列位置无效")
            if type(state["remembered"]) is not int or not 0 <= state["remembered"] <= index or type(state["revealed"]) is not bool:
                raise ValueError("作答状态无效")
            if not isinstance(state["answer"], str) or len(state["answer"]) > 100:
                raise ValueError("拼写内容无效")
            words = [vocabulary.get_word(word_id) for word_id in ids]
            if any(word is None for word in words):
                raise ValueError("本轮包含已删除的单词")
            if state.get("word_content") != [words[index][key] for key in ("word", "meaning", "phonetic", "example")]:
                state["revealed"] = False
            self.begin(words, state["mode"], resume=state)
            return True
        except (KeyError, TypeError, ValueError) as error:
            self.status.setText(f"无法恢复背诵：{error}。可结束本轮后重新选词，已有复习次数保留。")
            return False


class VocabularyPage(QDialog):
    content_changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("英语背单词")
        self.speech = Pronunciation(self)
        self._translation_busy = False
        self._job_cancelled = False
        self._editing_active = False
        self._restoring = False
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(600)
        self._autosave.timeout.connect(self.save_workspaces)
        self.views = QStackedWidget()
        self.library = QWidget()
        self.editor = QWidget()
        self.import_page = QWidget()
        self.study = WordStudy()
        self.study.pronounce_requested.connect(self.speech.say)
        self.study.stop_requested.connect(self.speech.stop)
        self.study.pronounce.setEnabled(bool(self.speech.voices))
        self.study.auto_speak.setEnabled(bool(self.speech.voices))
        for page in (self.library, self.editor, self.study, self.import_page):
            self.views.addWidget(page)
        self.study.back_requested.connect(self.show_library)
        self.study.content_changed.connect(self.content_changed.emit)
        self.views.currentChanged.connect(self._view_changed)
        self._build_library()
        self._build_editor()
        self._build_import()
        self._build_tools()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.model_tools)
        layout.addWidget(self.views, 1)
        layout.addWidget(self.speech_tools)
        self._view_changed()
        self.refresh()
        for field in (self.word, self.meaning, self.phonetic, self.example, self.book):
            field.textChanged.connect(lambda: self._autosave.start() if not self._restoring else None)
        self.restore_import_draft()
        self._refresh_resume()

    def _build_library(self):
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索英文单词或中文释义…")
        self.book_filter = QComboBox()
        self.book_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.book_filter.setMinimumContentsLength(10)
        self.book_filter.setMaximumWidth(220)
        self.book_filter.addItem("全部单词本", "")
        self.scope = QComboBox()
        for title, value in (("全部单词", "all"), ("新单词", "new"), ("到期复习", "due")):
            self.scope.addItem(title, value)
        self.search.textChanged.connect(self.refresh)
        self.book_filter.currentIndexChanged.connect(self.refresh)
        self.scope.currentIndexChanged.connect(self.refresh)
        filters = QHBoxLayout()
        filters.addWidget(self.search, 1)
        filters.addWidget(self.book_filter)
        filters.addWidget(self.scope)
        add = self.add_button = AnimatedButton("新增单词")
        add.setObjectName("softButton")
        add.clicked.connect(lambda: self.edit_word())
        self.edit_button = AnimatedButton("编辑")
        self.edit_button.clicked.connect(lambda: self.edit_word(self.selected_id()))
        self.delete_button = AnimatedButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self.delete_word)
        upload = self.upload_button = AnimatedButton("导入 TXT / CSV")
        upload.setToolTip("TXT 每行一个单词，可用 Tab 分隔释义；CSV 必须有 word 列，释义可自动补全。")
        upload.clicked.connect(self.import_file)
        sample = self.sample_button = AnimatedButton("导入 10 个示例词")
        sample.clicked.connect(lambda: self.import_file(Path(__file__).resolve().parents[2] / "assets" / "vocabulary_template.csv"))
        actions = QHBoxLayout()
        self.library_speak = AnimatedButton("发音")
        self.library_speak.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.library_speak.clicked.connect(self.speak_selected)
        self.resume_import = AnimatedButton("继续导入草稿")
        self.resume_import.clicked.connect(lambda: self.views.setCurrentWidget(self.import_page))
        self.resume_import.hide()
        for button in (add, self.edit_button, self.delete_button, self.library_speak, upload, sample, self.resume_import):
            actions.addWidget(button)
        actions.addStretch()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["英文单词", "释义", "单词本", "状态"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_word(self.selected_id()))
        self.empty_hint = QLabel("先添加单词或导入 TXT / CSV；也可以导入 10 个示例词，体验背诵流程。")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setObjectName("muted")
        self.mode = QComboBox()
        self.mode.addItem("看英文记释义", "card")
        self.mode.addItem("看释义练拼写", "spelling")
        self.limit = QSpinBox()
        self.limit.setRange(1, 200)
        self.limit.setValue(20)
        self.limit.setSuffix(" 个")
        start = self.start_button = AnimatedButton("开始 / 继续背诵")
        start.setObjectName("primaryButton")
        start.clicked.connect(self.start_study)
        self.end_study_button = AnimatedButton("结束本轮")
        self.end_study_button.setObjectName("dangerButton")
        self.end_study_button.clicked.connect(self.end_study)
        study_row = QHBoxLayout()
        study_row.addWidget(QLabel("背诵方式"))
        study_row.addWidget(self.mode, 1)
        study_row.addWidget(QLabel("本轮数量"))
        study_row.addWidget(self.limit)
        study_row.addWidget(start)
        study_row.addWidget(self.end_study_button)
        layout = QVBoxLayout(self.library)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self.summary)
        layout.addLayout(filters)
        layout.addLayout(actions)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty_hint)
        layout.addWidget(self.status)
        layout.addLayout(study_row)

    def _build_editor(self):
        self.editor_title = QLabel("新增单词")
        self.editor_title.setObjectName("detailTitle")
        self.word = QLineEdit()
        self.word.setMaxLength(100)
        self.word.setPlaceholderText("例如 remember / keep going")
        self.editor_speak = AnimatedButton("发音")
        self.editor_speak.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.editor_speak.setEnabled(bool(self.speech.voices))
        self.editor_speak.clicked.connect(lambda: self.speech.say(self.word.text()))
        self.meaning = QPlainTextEdit()
        self.meaning.setPlaceholderText("中文释义与词性，例如 v. 记得；想起")
        self.meaning.setMaximumHeight(100)
        self.phonetic = QLineEdit()
        self.phonetic.setFont(QFont("Segoe UI", 11))
        self.phonetic.setMaxLength(100)
        self.phonetic.setPlaceholderText("音标（可选）")
        self.example = QPlainTextEdit()
        self.example.setPlaceholderText("例句与译文（可选）")
        self.example.setMaximumHeight(100)
        self.book = QLineEdit()
        self.book.setMaxLength(100)
        self.book.setPlaceholderText("例如 四级词汇 / 我的生词")
        form = QFormLayout()
        form.setVerticalSpacing(14)
        word_row = QHBoxLayout()
        word_row.addWidget(self.word, 1)
        word_row.addWidget(self.editor_speak)
        form.addRow("英文单词 *", word_row)
        self.translate_button = AnimatedButton("自动补全释义、音标和例句")
        self.translate_button.setObjectName("softButton")
        self.translate_button.clicked.connect(self.translate_editor)
        form.addRow("AI 辅助", self.translate_button)
        for title, field in (("中文释义 *", self.meaning),
                             ("音标", self.phonetic), ("例句", self.example), ("单词本", self.book)):
            form.addRow(title, field)
        self.editor_status = QLabel()
        self.editor_status.setWordWrap(True)
        self.editor_status.setTextFormat(Qt.TextFormat.PlainText)
        self.editor_status.setStyleSheet("color:#b84d58;")
        save = self.save_button = AnimatedButton("保存单词")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_word)
        cancel = AnimatedButton("返回单词本")
        cancel.clicked.connect(self.show_library)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        card = QFrame()
        card.setObjectName("formCard")
        card.setMaximumWidth(740)
        content = QVBoxLayout(card)
        content.setContentsMargins(24, 24, 24, 24)
        content.setSpacing(18)
        content.addWidget(self.editor_title)
        content.addLayout(form)
        content.addWidget(self.editor_status)
        content.addLayout(buttons)
        layout = QVBoxLayout(self.editor)
        layout.setContentsMargins(0, 0, 0, 0)
        wrapper = QWidget()
        inner = QVBoxLayout(wrapper)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(card)
        inner.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(wrapper)
        layout.addWidget(scroll)

    def _build_tools(self):
        self.model_tools = QWidget()
        layout = QHBoxLayout(self.model_tools)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("自动翻译模型"))
        self.profile = QComboBox()
        self.profile.setMinimumContentsLength(20)
        self.profile.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        layout.addWidget(self.profile, 1)
        self.refresh_models = AnimatedButton("刷新模型配置")
        self.refresh_models.clicked.connect(self.refresh_profiles)
        layout.addWidget(self.refresh_models)
        self.stop_translation = AnimatedButton("停止翻译")
        self.stop_translation.clicked.connect(self.cancel_translation)
        self.stop_translation.hide()
        layout.addWidget(self.stop_translation)
        self.refresh_profiles()
        self.speech_tools = QWidget()
        layout = QHBoxLayout(self.speech_tools)
        layout.setContentsMargins(0, 0, 0, 0)
        self.speech_status = QLabel(self.speech.status)
        self.speech_status.setObjectName("muted")
        self.speech_status.setWordWrap(True)
        self.speech_status.setTextFormat(Qt.TextFormat.PlainText)
        self.speech.status_changed.connect(self.speech_status.setText)
        layout.addWidget(self.speech_status, 1)
        self.voice = QComboBox()
        for voice in self.speech.voices:
            self.voice.addItem(f"{voice.name()} · {voice.locale().name()}")
        if not self.speech.voices:
            self.voice.addItem("未安装英语语音")
            self.voice.setEnabled(False)
        self.voice.setMaximumWidth(300)
        self.voice.currentIndexChanged.connect(self.speech.set_voice)
        layout.addWidget(self.voice)
        self.speech_speed = QComboBox()
        self.speech_speed.addItems(["较慢", "稍慢", "正常", "稍快", "较快"])
        self.speech_speed.setCurrentIndex(self.speech.speed)
        self.speech_speed.setMaximumWidth(110)
        self.speech_speed.setAccessibleName("发音速度")
        self.speech_speed.setToolTip("切换语速会停止当前朗读，下次发音使用新语速；重启后保留。")
        self.speech_speed.setEnabled(bool(self.speech.voices))
        self.speech_speed.currentIndexChanged.connect(self.speech.set_speed)
        layout.addWidget(QLabel("语速"))
        layout.addWidget(self.speech_speed)
        stop = AnimatedButton("停止朗读")
        stop.setEnabled(bool(self.speech.voices))
        stop.clicked.connect(self.speech.stop)
        layout.addWidget(stop)

    def _view_changed(self, *_):
        self.speech.stop()
        page = self.views.currentWidget()
        if self._translation_busy and page is not self._job_page:
            self.cancel_translation()
        if hasattr(self, "model_tools"):
            self.model_tools.setVisible(page in (self.editor, self.import_page))
            self.speech_tools.setVisible(page is not self.import_page)
        self.content_changed.emit()

    def refresh_profiles(self):
        selected = self.profile.currentData()
        self.profile.clear()
        try:
            for row in store.list_profiles(enabled_only=True):
                self.profile.addItem(f"{row['name']} · {row['model_id']}", row["id"])
        except sqlite3.Error as error:
            self.profile.setToolTip(str(error))
        if not self.profile.count():
            self.profile.addItem("请先在模型服务中添加并启用配置", None)
        self.profile.setCurrentIndex(max(0, self.profile.findData(selected)))

    def speak_selected(self):
        row = vocabulary.get_word(self.selected_id())
        if row:
            self.speech.say(row["word"])

    def _build_import(self):
        title = QLabel("核对导入词表")
        title.setObjectName("detailTitle")
        self.import_info = QLabel()
        self.import_info.setWordWrap(True)
        self.import_info.setTextFormat(Qt.TextFormat.PlainText)
        self.import_info.setObjectName("muted")
        self.import_table = QTableWidget(0, 5)
        self.import_table.setHorizontalHeaderLabels(["英文单词", "中文释义 *", "音标", "例句", "单词本"])
        self.import_table.verticalHeader().hide()
        self.import_table.verticalHeader().setDefaultSectionSize(48)
        self.import_table.setShowGrid(False)
        self.import_table.setAlternatingRowColors(True)
        self.import_table.setWordWrap(False)
        self.import_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.import_table.itemChanged.connect(self._update_import_info)
        self.import_table.itemChanged.connect(lambda: self._autosave.start() if not self._restoring else None)
        self.import_status = QLabel()
        self.import_status.setWordWrap(True)
        self.import_status.setTextFormat(Qt.TextFormat.PlainText)
        self.import_status.setObjectName("muted")
        self.translate_import = AnimatedButton("自动补全中文释义")
        self.translate_import.setObjectName("softButton")
        self.translate_import.clicked.connect(self.translate_draft)
        self.confirm_import = AnimatedButton("确认导入")
        self.confirm_import.setObjectName("primaryButton")
        self.confirm_import.clicked.connect(self.save_import)
        cancel = AnimatedButton("返回单词本")
        cancel.clicked.connect(self.show_library)
        self.discard_import = AnimatedButton("舍弃草稿")
        self.discard_import.setObjectName("dangerButton")
        self.discard_import.clicked.connect(self.discard_import_draft)
        buttons = QHBoxLayout()
        buttons.addWidget(self.translate_import)
        buttons.addWidget(self.discard_import)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm_import)
        layout = QVBoxLayout(self.import_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(self.import_info)
        layout.addWidget(self.import_table, 1)
        layout.addWidget(self.import_status)
        layout.addLayout(buttons)

    def show_import_draft(self, rows, filename):
        self.refresh_profiles()
        self.import_filename = filename
        with QSignalBlocker(self.import_table):
            self.import_table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                for column, key in enumerate(("word", "meaning", "phonetic", "example", "book")):
                    item = QTableWidgetItem(row[key])
                    item.setToolTip(row[key])
                    if column == 2:
                        item.setFont(QFont("Segoe UI", 10))
                    if column == 0:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.import_table.setItem(index, column, item)
        self._update_import_info()
        self.resume_import.show()
        self.import_status.setText("自动补全将调用所选模型服务；可双击单元格编辑，确认前不会写入单词本。")
        self.views.setCurrentWidget(self.import_page)
        if not self._restoring:
            self.save_workspaces()

    def save_workspaces(self):
        self._autosave.stop()
        if self._restoring:
            return
        if self.import_table.rowCount():
            try:
                store.save_workspace("vocabulary:import", dict(filename=self.import_filename, rows=self._draft_rows()))
            except (sqlite3.Error, ValueError) as error:
                self.import_status.setText(f"导入草稿保存失败：{error}。请保留窗口并精简过长内容。")
        if self._editing_active:
            try:
                values = self._editor_values()
                if any(len(value) > 4000 for value in values.values()):
                    raise ValueError("草稿字段最多 4000 个字符。")
                store.save_workspace(self._word_draft_key(), values)
            except (sqlite3.Error, ValueError) as error:
                self.editor_status.setText(f"单词草稿保存失败：{error}")
        self.study.save_progress()

    def restore_import_draft(self):
        try:
            state = store.load_workspace("vocabulary:import")
            if not state:
                return
            if not isinstance(state.get("filename"), str) or len(state["filename"]) > 260:
                raise ValueError("文件名称无效")
            rows = vocabulary.validate_rows(state.get("rows"), require_meaning=False)
            self._restoring = True
            self.show_import_draft(rows, state["filename"])
            self.views.setCurrentWidget(self.library)
            self.status.setText("已恢复词表草稿，点击“继续导入草稿”核对；自动翻译不会自动重发。")
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(f"词表草稿暂时无法恢复：{error}")
        finally:
            self._restoring = False

    def discard_import_draft(self):
        if self._translation_busy:
            return
        if QMessageBox.question(self, "舍弃词表草稿", "舍弃尚未导入的词表草稿？已保存的单词不受影响。") != QMessageBox.StandardButton.Yes:
            return
        try:
            store.save_workspace("vocabulary:import", None)
        except sqlite3.Error as error:
            self.import_status.setText(f"舍弃失败：{error}")
            return
        self._autosave.stop()
        self.import_table.setRowCount(0)
        self.resume_import.hide()
        self.show_library()

    def _draft_rows(self):
        keys = ("word", "meaning", "phonetic", "example", "book")
        return [dict(zip(keys, (self.import_table.item(row, col).text().strip() for col in range(5))))
                for row in range(self.import_table.rowCount())]

    def _update_import_info(self, *_):
        missing = sum(not self.import_table.item(row, 1).text().strip()
                      for row in range(self.import_table.rowCount()))
        self.import_info.setText(f"{getattr(self, 'import_filename', '')} · 共 {self.import_table.rowCount()} 条 · 待补全释义 {missing} 条")

    def save_import(self):
        if self._translation_busy:
            return
        try:
            added, skipped = vocabulary.import_rows(self._draft_rows(), draft_key="vocabulary:import")
        except (sqlite3.Error, ValueError) as error:
            self.import_status.setText(f"未导入：{error}")
            return
        self.import_table.setRowCount(0)
        self.resume_import.hide()
        self._autosave.stop()
        self.status.setText(f"已导入 {added} 个单词，跳过 {skipped} 个重复项；已有内容与进度保留。")
        self.show_library()

    def translate_editor(self):
        if all((self.meaning.toPlainText().strip(), self.phonetic.text().strip(), self.example.toPlainText().strip())):
            self.editor_status.setText("释义、音标和例句已填写；清空需要补全的字段后再翻译。")
            return
        self._start_translation(self.editor, [self.word.text()])

    def translate_draft(self):
        words = [row["word"] for row in self._draft_rows() if not row["meaning"]]
        if not words:
            self.import_status.setText("所有释义已填写，可以核对后确认导入。")
            return
        self._start_translation(self.import_page, words)

    def _start_translation(self, page, words):
        if self._translation_busy:
            return
        label = self.editor_status if page is self.editor else self.import_status
        try:
            unique = {}
            for word in words:
                word = vocabulary.validate_word(word)
                unique.setdefault(word.casefold(), word)
            words = list(unique.values())
            profile = store.get_profile(self.profile.currentData())
            if profile is None or not profile["enabled"]:
                raise ValueError("请先在模型服务中添加并启用配置，再刷新模型配置。")
            validate_profile(profile)
        except (sqlite3.Error, ValueError, ProviderError) as error:
            label.setText(str(error))
            return
        self._job_page = page
        self._job_label = label
        label.setToolTip("")
        self._job_profile = dict(profile)
        self._pending_words = words
        self._job_total = len(words)
        self._job_done = 0
        self._job_cancelled = False
        self._translation_busy = True
        self._set_translation_controls()
        self._run_translation_batch()

    def _set_translation_controls(self):
        enabled = not self._translation_busy
        for widget in (self.translate_button, self.translate_import, self.confirm_import, self.save_button,
                       self.add_button, self.upload_button, self.sample_button, self.profile, self.refresh_models, self.discard_import,
                       self.word, self.meaning, self.phonetic, self.example, self.book):
            widget.setEnabled(enabled)
        self.import_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed
                                          if enabled else QTableWidget.EditTrigger.NoEditTriggers)
        self.stop_translation.setVisible(not enabled)
        self.stop_translation.setEnabled(not self._job_cancelled)
        self._selection_changed()

    def _run_translation_batch(self):
        self._job_label.setText(f"正在自动补全 {self._job_done} / {self._job_total}…")
        batch = self._pending_words[:20]
        profile = self._job_profile
        worker = Worker(lambda: translate_words(profile, batch))
        worker.signals.succeeded.connect(self._translation_succeeded)
        worker.signals.failed.connect(self._translation_failed)
        self._worker = worker
        QThreadPool.globalInstance().start(worker)

    def _translation_succeeded(self, entries):
        if self._job_cancelled:
            self._finish_translation("已停止；完成的草稿已保留，尚未导入。")
            return
        if self._job_page is self.editor:
            entry = entries[0]
            if not self.meaning.toPlainText().strip():
                self.meaning.setPlainText(entry["meaning"])
            if not self.phonetic.text().strip():
                self.phonetic.setText(entry["phonetic"])
            if not self.example.toPlainText().strip():
                self.example.setPlainText(entry["example"])
            self._finish_translation("已补全空白字段，请核对后保存。")
            return
        translated = {entry["word"].casefold(): entry for entry in entries}
        with QSignalBlocker(self.import_table):
            for row in range(self.import_table.rowCount()):
                entry = translated.get(self.import_table.item(row, 0).text().casefold())
                if entry:
                    for column, key in ((1, "meaning"), (2, "phonetic"), (3, "example")):
                        item = self.import_table.item(row, column)
                        if not item.text().strip():
                            item.setText(entry[key])
                            item.setToolTip(entry[key])
        self._update_import_info()
        count = min(20, len(self._pending_words))
        self.save_workspaces()
        self._job_done += count
        del self._pending_words[:count]
        if self._pending_words:
            self._run_translation_batch()
        else:
            self._finish_translation(f"已补全 {self._job_done} 个单词，请核对后确认导入。")

    def _translation_failed(self, error):
        self._job_label.setToolTip(getattr(error, "raw_response", ""))
        self._finish_translation("已停止翻译。" if self._job_cancelled
                                 else f"翻译失败：{error}；已完成的草稿保留，可重试剩余词条。")

    def _finish_translation(self, message):
        self._translation_busy = False
        self._set_translation_controls()
        self._job_label.setText(message)
        if self.views.currentWidget() is self.library:
            self.status.setText(message)

    def cancel_translation(self):
        if self._translation_busy:
            self._job_cancelled = True
            self.stop_translation.setEnabled(False)
            self._job_label.setText("正在停止，等待当前请求结束；不会继续发送下一批。")

    def selected_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self):
        enabled = self.selected_id() is not None and not self._translation_busy
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.library_speak.setEnabled(self.selected_id() is not None and bool(self.speech.voices))

    def refresh(self, *_):
        selected = self.selected_id()
        try:
            summary, books = vocabulary.summary_and_books()
            book = self.book_filter.currentData()
            with QSignalBlocker(self.book_filter):
                self.book_filter.clear()
                self.book_filter.addItem("全部单词本", "")
                for name in books:
                    self.book_filter.addItem(name, name)
                self.book_filter.setCurrentIndex(max(0, self.book_filter.findData(book)))
            rows = vocabulary.list_words(self.search.text().strip(), self.book_filter.currentData(), self.scope.currentData())
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(f"读取单词失败：{error}")
            return
        self.summary.setText(f"共 {summary[0]} 个单词 · 未学 {summary[1]} · 待复习 {summary[2]} · 当前显示 {len(rows)} 个")
        self.table.setRowCount(len(rows))
        index = 0
        for row_index, word in enumerate(rows):
            state = "未学" if not word["review_count"] else f"已复习 {word['review_count']} 次"
            for column, value in enumerate((word["word"], word["meaning"], word["book"] or "未分组", state)):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, word["id"])
                self.table.setItem(row_index, column, item)
            if word["id"] == selected:
                index = row_index
        if rows:
            self.table.selectRow(index)
        self._selection_changed()
        self.empty_hint.setVisible(not rows)
        self.empty_hint.setText(
            "没有符合筛选条件的单词，请调整搜索、单词本或复习范围。" if summary[0]
            else "先添加单词或导入 TXT / CSV；也可以导入 10 个示例词，体验背诵流程。"
        )

    def show_library(self):
        self.save_workspaces()
        self._editing_active = False
        self.cancel_translation()
        self.speech.stop()
        if self._translation_busy:
            self.status.setText("正在停止翻译，等待当前请求返回或超时；完成后可继续编辑。")
        self.views.setCurrentWidget(self.library)
        self.refresh()
        self._refresh_resume()

    def _refresh_resume(self):
        pending = bool(self.study.words and self.study.index < len(self.study.words)) or bool(store.load_workspace("vocabulary:study"))
        self.start_button.setText("继续本轮背诵" if pending else "开始背诵")
        self.end_study_button.setVisible(pending)

    def _word_draft_key(self):
        return f"vocabulary:word:{self.editing_id if self.editing_id is not None else 'new'}"

    def _editor_values(self):
        return dict(word=self.word.text(), meaning=self.meaning.toPlainText(), phonetic=self.phonetic.text(),
                    example=self.example.toPlainText(), book=self.book.text())

    def edit_word(self, word_id=None):
        if self._translation_busy:
            return
        self.refresh_profiles()
        try:
            row = vocabulary.get_word(word_id) if word_id is not None else None
            if word_id is not None and row is None:
                raise ValueError("单词已不存在，请刷新。")
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(str(error))
            return
        self.editing_id = word_id
        self._restoring = True
        self.editor_title.setText("编辑单词" if row else "新增单词")
        for field, key in ((self.word, "word"), (self.phonetic, "phonetic"), (self.book, "book")):
            field.setText(row[key] if row else "")
        self.meaning.setPlainText(row["meaning"] if row else "")
        self.example.setPlainText(row["example"] if row else "")
        self.editor_status.clear()
        try:
            draft = store.load_workspace(self._word_draft_key())
            if draft and all(isinstance(draft.get(key), str) and len(draft[key]) <= 4000
                             for key in ("word", "meaning", "phonetic", "example", "book")):
                self.word.setText(draft["word"])
                self.meaning.setPlainText(draft["meaning"])
                self.phonetic.setText(draft["phonetic"])
                self.example.setPlainText(draft["example"])
                self.book.setText(draft["book"])
                self.editor_status.setText("已恢复上次未保存的单词草稿。")
        except sqlite3.Error as error:
            self.editor_status.setText(f"读取草稿失败：{error}")
        self._restoring = False
        self._editing_active = True
        self.views.setCurrentWidget(self.editor)
        self.word.setFocus()

    def save_word(self):
        if self._translation_busy:
            return
        try:
            vocabulary.save_word(self._editor_values(), self.editing_id, draft_key=self._word_draft_key())
        except (sqlite3.Error, ValueError) as error:
            self.editor_status.setText(str(error))
            return
        self.status.setText("单词已保存。")
        self._editing_active = False
        self._autosave.stop()
        self.show_library()

    def delete_word(self):
        word_id = self.selected_id()
        if word_id is None:
            return
        if QMessageBox.question(self, "删除单词", "删除此单词及其复习进度？") != QMessageBox.StandardButton.Yes:
            return
        try:
            vocabulary.delete_word(word_id)
        except sqlite3.Error as error:
            self.status.setText(f"删除失败：{error}")
            return
        self.status.setText("单词已删除。")
        self.refresh()

    def import_file(self, path=None):
        if self._translation_busy:
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "导入单词表", "", "词表 (*.txt *.csv)")
        if not path:
            return
        try:
            rows = vocabulary.read_word_file(path)
            existing = {row["word"].casefold(): row for row in vocabulary.list_words()}
            for row in rows:
                previous = existing.get(row["word"].casefold())
                if previous:
                    for key in ("meaning", "phonetic", "example"):
                        row[key] = row[key] or previous[key]
                row["book"] = row["book"] or Path(path).stem[:100]
            if any(not row["meaning"] for row in rows):
                if self.import_table.rowCount() and QMessageBox.question(
                    self, "替换词表草稿", "已有未完成的词表草稿。用新词表替换？选择取消可继续原草稿。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                ) != QMessageBox.StandardButton.Yes:
                    return
                self.show_import_draft(rows, Path(path).name)
                return
            added, skipped = vocabulary.import_rows(rows)
        except (OSError, UnicodeError, csv.Error, sqlite3.Error, ValueError) as error:
            self.status.setText(f"导入失败，未写入单词：{error}")
            return
        self.status.setText(f"已导入 {added} 个单词，跳过 {skipped} 个重复项；已有释义及复习进度保留。")
        self.refresh()

    def start_study(self):
        try:
            if self.study.words and self.study.index < len(self.study.words):
                self.views.setCurrentWidget(self.study)
                return
            if store.load_workspace("vocabulary:study"):
                if self.study.resume():
                    self.views.setCurrentWidget(self.study)
                else:
                    self.status.setText(self.study.status.text())
                return
            words = vocabulary.list_words(self.search.text().strip(), self.book_filter.currentData(),
                                          self.scope.currentData(), self.limit.value())
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(f"无法开始背诵：{error}")
            return
        if not words:
            self.status.setText("当前范围没有单词，请添加单词或调整搜索、单词本和复习范围。")
            return
        self.views.setCurrentWidget(self.study)
        self.study.begin(words, self.mode.currentData())

    def end_study(self):
        if QMessageBox.question(self, "结束本轮背诵", "结束本轮并放弃未记录的卡片？已记录的复习次数保留。") != QMessageBox.StandardButton.Yes:
            return
        try:
            store.save_workspace("vocabulary:study", None)
        except sqlite3.Error as error:
            self.status.setText(f"结束失败：{error}")
            return
        self.study._checkpoint.stop()
        self.study.words = []
        self.show_library()

    def reset(self):
        self._autosave.stop()
        self.study._checkpoint.stop()
        self._restoring = True
        self._editing_active = False
        self.cancel_translation()
        self.speech.stop()
        self.import_table.setRowCount(0)
        self.resume_import.hide()
        self.study.words = []
        self.search.clear()
        self.scope.setCurrentIndex(0)
        self.status.clear()
        self._restoring = False
        self.restore_import_draft()
        self.show_library()
