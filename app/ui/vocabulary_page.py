import csv
from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.database import vocabulary
from app.ui.motion import AnimatedButton
from app.ui.theme import ACCENT, MUTED


class WordStudy(QWidget):
    content_changed = Signal()
    back_requested = Signal()

    def __init__(self):
        super().__init__()
        self.words = []
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
        self.caption = QLabel()
        self.caption.setObjectName("muted")
        self.face = QLabel()
        self.face.setObjectName("wordFace")
        self.face.setMinimumHeight(100)
        self.phonetic = QLabel()
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

    def begin(self, words, mode):
        self.words = [dict(word) for word in words]
        self.mode = mode
        self.index = self.remembered = 0
        self.show_card()

    def show_card(self):
        self.revealed = False
        self.correct = None
        self.status.clear()
        self.answer.clear()
        self.answer.setReadOnly(False)
        for widget in (self.solution, self.example, self.forgot, self.hard, self.known):
            widget.hide()
        if self.index >= len(self.words):
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
            if spelling:
                self.answer.setFocus()
        self.content_changed.emit()

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
        self.content_changed.emit()

    def record(self, rating):
        if not self.revealed or self.index >= len(self.words):
            return
        if self.correct is False:
            rating = "forgot"
        try:
            vocabulary.record_review(self.words[self.index]["id"], rating)
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(f"保存失败，未进入下一词：{error}")
            return
        self.remembered += rating == "known"
        self.index += 1
        self.show_card()


class VocabularyPage(QDialog):
    content_changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("英语背单词")
        self.views = QStackedWidget()
        self.library = QWidget()
        self.editor = QWidget()
        self.study = WordStudy()
        for page in (self.library, self.editor, self.study):
            self.views.addWidget(page)
        self.study.back_requested.connect(self.show_library)
        self.study.content_changed.connect(self.content_changed.emit)
        self.views.currentChanged.connect(lambda _: self.content_changed.emit())
        self._build_library()
        self._build_editor()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.views)
        self.refresh()

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
        add = AnimatedButton("新增单词")
        add.setObjectName("softButton")
        add.clicked.connect(lambda: self.edit_word())
        self.edit_button = AnimatedButton("编辑")
        self.edit_button.clicked.connect(lambda: self.edit_word(self.selected_id()))
        self.delete_button = AnimatedButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self.delete_word)
        upload = AnimatedButton("导入 CSV")
        upload.setToolTip("表头：word,meaning,phonetic,example,book；仅前两列必填")
        upload.clicked.connect(self.import_file)
        sample = AnimatedButton("导入 10 个示例词")
        sample.clicked.connect(lambda: self.import_file(Path(__file__).resolve().parents[2] / "assets" / "vocabulary_template.csv"))
        actions = QHBoxLayout()
        for button in (add, self.edit_button, self.delete_button, upload, sample):
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
        self.empty_hint = QLabel("先添加单词或导入 CSV；也可以导入 10 个示例词，体验背诵流程。")
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
        start = AnimatedButton("开始背诵")
        start.setObjectName("primaryButton")
        start.clicked.connect(self.start_study)
        study_row = QHBoxLayout()
        study_row.addWidget(QLabel("背诵方式"))
        study_row.addWidget(self.mode, 1)
        study_row.addWidget(QLabel("本轮数量"))
        study_row.addWidget(self.limit)
        study_row.addWidget(start)
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
        self.meaning = QPlainTextEdit()
        self.meaning.setPlaceholderText("中文释义与词性，例如 v. 记得；想起")
        self.meaning.setMaximumHeight(100)
        self.phonetic = QLineEdit()
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
        for title, field in (("英文单词 *", self.word), ("中文释义 *", self.meaning),
                             ("音标", self.phonetic), ("例句", self.example), ("单词本", self.book)):
            form.addRow(title, field)
        self.editor_status = QLabel()
        self.editor_status.setWordWrap(True)
        self.editor_status.setTextFormat(Qt.TextFormat.PlainText)
        self.editor_status.setStyleSheet("color:#b84d58;")
        save = AnimatedButton("保存单词")
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
        layout.addWidget(card)
        layout.addStretch()

    def selected_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self):
        enabled = self.selected_id() is not None
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

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
            else "先添加单词或导入 CSV；也可以导入 10 个示例词，体验背诵流程。"
        )

    def show_library(self):
        self.views.setCurrentWidget(self.library)
        self.refresh()

    def edit_word(self, word_id=None):
        try:
            row = vocabulary.get_word(word_id) if word_id is not None else None
            if word_id is not None and row is None:
                raise ValueError("单词已不存在，请刷新。")
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(str(error))
            return
        self.editing_id = word_id
        self.editor_title.setText("编辑单词" if row else "新增单词")
        for field, key in ((self.word, "word"), (self.phonetic, "phonetic"), (self.book, "book")):
            field.setText(row[key] if row else "")
        self.meaning.setPlainText(row["meaning"] if row else "")
        self.example.setPlainText(row["example"] if row else "")
        self.editor_status.clear()
        self.views.setCurrentWidget(self.editor)
        self.word.setFocus()

    def save_word(self):
        try:
            vocabulary.save_word(dict(word=self.word.text(), meaning=self.meaning.toPlainText(),
                                      phonetic=self.phonetic.text(), example=self.example.toPlainText(),
                                      book=self.book.text()), self.editing_id)
        except (sqlite3.Error, ValueError) as error:
            self.editor_status.setText(str(error))
            return
        self.status.setText("单词已保存。")
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
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "导入单词 CSV", "", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            added, skipped = vocabulary.import_csv(path)
        except (OSError, UnicodeError, csv.Error, sqlite3.Error, ValueError) as error:
            self.status.setText(f"导入失败，未写入单词：{error}")
            return
        self.status.setText(f"已导入 {added} 个单词，跳过 {skipped} 个重复项；已有释义及复习进度保留。")
        self.refresh()

    def start_study(self):
        try:
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

    def reset(self):
        self.study.words = []
        self.search.clear()
        self.scope.setCurrentIndex(0)
        self.status.clear()
        self.show_library()
