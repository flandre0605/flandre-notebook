import random
import sqlite3
import tempfile
from pathlib import Path
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.database import store
from app.services import backup, attachments
from app.ui.attachments_dialog import AttachmentsDialog
from app.ui.history_dialog import HistoryDialog
from app.ui.image_recognition_dialog import ImageRecognitionDialog
from app.ui.practice_dialog import PracticeDialog, PracticeSetupDialog
from app.ui.profiles_dialog import ProfilesDialog
from app.ui.screenshot import GlobalScreenshotHotkey, ScreenshotOverlay


STYLE = """
QMainWindow, QDialog { background: #f5f7fb; }
QLabel { color: #273449; }
QLabel#pageTitle { color: #17243a; font-size: 27px; font-weight: 700; }
QLabel#pageSubtitle, QLabel#muted { color: #8490a3; font-size: 12px; }
QLabel#resultCount, QLabel#cardCaption { color: #7c899d; font-size: 12px; }
QLabel#statValue { color: #18263d; font-size: 25px; font-weight: 700; }
QLabel#brandMark { background: #4369df; color: white; border-radius: 12px; font-size: 18px; font-weight: 700; }
QFrame#sidebar { background: #ffffff; border-right: 1px solid #e8edf4; }
QFrame#toolbarCard, QFrame#tableCard, QFrame#emptyCard, QFrame#statCard {
    background: #ffffff; border: 1px solid #e6ebf2; border-radius: 12px;
}
QFrame#statAccentBlue { background: #4e74e8; border-radius: 2px; }
QFrame#statAccentRed { background: #e67579; border-radius: 2px; }
QFrame#statAccentAmber { background: #e7aa45; border-radius: 2px; }
QLineEdit, QPlainTextEdit, QComboBox {
    background: #ffffff; border: 1px solid #dfe5ee; border-radius: 8px;
    padding: 8px 10px; color: #273449; selection-background-color: #dce7ff;
}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover { border-color: #c8d2e1; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 1px solid #809bea; }
QComboBox { min-height: 22px; }
QComboBox::drop-down { border: 0; width: 25px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #dfe5ee; selection-background-color: #edf2ff; }
QPushButton {
    background: #ffffff; color: #46536a; border: 1px solid #dfe5ee;
    border-radius: 8px; padding: 8px 13px; font-weight: 600;
}
QPushButton:hover { background: #f6f8fc; border-color: #cbd5e3; }
QPushButton:disabled { color: #aab3c0; background: #f7f8fa; }
QPushButton#primaryButton { background: #4369df; color: #ffffff; border-color: #4369df; }
QPushButton#primaryButton:hover { background: #365bcf; }
QPushButton#softButton { background: #eef3ff; color: #3759b2; border-color: #e2eaff; }
QPushButton#dangerButton { color: #bd5962; }
QPushButton#navButton, QPushButton#navButtonActive, QPushButton#navUtility {
    text-align: left; border: 0; padding: 11px 13px; font-weight: 500;
}
QPushButton#navButton, QPushButton#navUtility { background: transparent; color: #67758a; }
QPushButton#navButton:hover, QPushButton#navUtility:hover { background: #f4f6fa; color: #2c3a52; }
QPushButton#navButtonActive { background: #edf2ff; color: #365dcc; font-weight: 700; }
QTableWidget {
    background: #ffffff; alternate-background-color: #fafbfd;
    border: none; color: #344158; selection-background-color: #edf2ff;
    selection-color: #233d78; outline: 0;
}
QHeaderView::section {
    background: #f7f9fc; color: #7c899d; border: none;
    border-bottom: 1px solid #e9edf3; padding: 11px 12px; font-weight: 600;
}
QTableWidget::item { padding-left: 10px; border: none; }
QTableWidget::item:hover { background: #f7f9fd; }
QTableWidget::item:selected { background: #edf2ff; color: #233d78; }
QStatusBar { background: transparent; color: #8a95a5; font-size: 11px; padding: 3px 10px; }
QDialogButtonBox QPushButton { min-width: 82px; }
QCheckBox { color: #46536a; spacing: 8px; }
QToolTip { color: #f8faff; background: #26344b; border: 0; padding: 6px 8px; }
"""


class QuestionDialog(QDialog):
    def __init__(self, question=None, parent=None, on_save=None):
        super().__init__(parent)
        self.on_save = on_save
        self.setWindowTitle("编辑题目" if question else "新增题目")
        self.resize(600, 560)
        self.setStyleSheet(STYLE)

        self.stem = QPlainTextEdit()
        self.stem.setMinimumHeight(105)
        self.stem.setPlaceholderText("输入题干")
        self.subject = QLineEdit()
        self.subject.setMinimumHeight(38)
        self.question_type = QLineEdit()
        self.question_type.setMinimumHeight(38)
        self.answer = QPlainTextEdit()
        self.answer.setMinimumHeight(65)
        self.answer.setPlaceholderText("标准答案；多个可接受答案用 | 分隔")
        self.explanation = QPlainTextEdit()
        self.explanation.setMinimumHeight(85)
        self.is_wrong = QCheckBox("标记为错题")

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.addRow("题干 *", self.stem)
        form.addRow("学科", self.subject)
        form.addRow("题型", self.question_type)
        form.addRow("答案", self.answer)
        form.addRow("解析", self.explanation)
        form.addRow("", self.is_wrong)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_if_valid)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(18)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if question:
            self.stem.setPlainText(question["stem"])
            self.subject.setText(question["subject"])
            self.question_type.setText(question["question_type"])
            self.answer.setPlainText(question["answer"])
            self.explanation.setPlainText(question["explanation"])
            self.is_wrong.setChecked(bool(question["is_wrong"]))

    def _save_if_valid(self):
        if not self.stem.toPlainText().strip():
            QMessageBox.warning(self, "缺少题干", "请先输入题干。")
            return
        if self.on_save and not self.on_save(self.values()):
            return
        self.accept()

    def values(self) -> dict[str, str | int]:
        return {
            "stem": self.stem.toPlainText(),
            "subject": self.subject.text(),
            "question_type": self.question_type.text(),
            "answer": self.answer.toPlainText(),
            "explanation": self.explanation.toPlainText(),
            "is_wrong": int(self.is_wrong.isChecked()),
        }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI 错题本")
        self.resize(1280, 820)
        self.setMinimumSize(1040, 680)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(222)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 22, 15, 18)
        sidebar_layout.setSpacing(7)

        brand_row = QHBoxLayout()
        brand_mark = QLabel("知")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(42, 42)
        brand_text = QVBoxLayout()
        brand_title = QLabel("AI 错题本")
        brand_title.setStyleSheet("font-size:15px;font-weight:700;color:#1e2b40;")
        brand_caption = QLabel("PERSONAL STUDY SPACE")
        brand_caption.setStyleSheet("font-size:8px;color:#9aa5b5;letter-spacing:1px;")
        brand_text.addWidget(brand_title)
        brand_text.addWidget(brand_caption)
        brand_row.addWidget(brand_mark)
        brand_row.addLayout(brand_text)
        brand_row.addStretch()
        sidebar_layout.addLayout(brand_row)
        sidebar_layout.addSpacing(26)

        section_label = QLabel("学习空间")
        section_label.setStyleSheet("color:#9aa5b5;font-size:11px;padding:0 10px 5px;")
        sidebar_layout.addWidget(section_label)

        def add_nav(text, callback, active=False, utility=False):
            button = QPushButton(text)
            button.setObjectName(
                "navButtonActive" if active else "navUtility" if utility else "navButton"
            )
            button.setMinimumHeight(43)
            button.clicked.connect(callback)
            sidebar_layout.addWidget(button)
            return button

        add_nav("▦  我的题库", self.refresh, active=True)
        add_nav("✦  AI 识题", self.recognize_selected)
        screenshot_button = add_nav("▣  截图识题", self.capture_screenshot)
        screenshot_button.setToolTip("全局快捷键：Ctrl+Alt+S")
        add_nav("▶  开始练习", self.start_practice)
        add_nav("◷  练习记录", self.show_history)
        sidebar_layout.addSpacing(18)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color:#edf0f5;")
        sidebar_layout.addWidget(divider)
        sidebar_layout.addSpacing(8)
        section_label = QLabel("管理")
        section_label.setStyleSheet("color:#9aa5b5;font-size:11px;padding:0 10px 5px;")
        sidebar_layout.addWidget(section_label)
        add_nav("⚙  模型服务", self.manage_profiles, utility=True)
        add_nav("↓  备份数据", self.create_backup, utility=True)
        add_nav("↻  恢复备份", self.restore_backup, utility=True)
        sidebar_layout.addStretch()

        local_badge = QFrame()
        local_badge.setStyleSheet(
            "background:#f5f7fb;border:1px solid #edf0f5;border-radius:9px;"
        )
        local_layout = QVBoxLayout(local_badge)
        local_layout.setContentsMargins(12, 10, 12, 10)
        local_title = QLabel("●  本地空间")
        local_title.setStyleSheet("color:#31815d;font-size:11px;font-weight:700;")
        local_caption = QLabel("题库数据保存在此设备")
        local_caption.setObjectName("muted")
        local_layout.addWidget(local_title)
        local_layout.addWidget(local_caption)
        sidebar_layout.addWidget(local_badge)

        title = QLabel("我的题库")
        title.setObjectName("pageTitle")
        subtitle = QLabel("整理错题，按计划复习，让每次练习都看得见进步。")
        subtitle.setObjectName("pageSubtitle")
        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        self.add_button = QPushButton("＋  新增题目")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setMinimumHeight(42)
        self.recognize_button = QPushButton("✦  AI 识题")
        self.recognize_button.setObjectName("softButton")
        self.recognize_button.setMinimumHeight(42)
        self.add_button.clicked.connect(self.add_question)
        self.recognize_button.clicked.connect(self.recognize_selected)
        page_header = QHBoxLayout()
        page_header.addLayout(title_block)
        page_header.addStretch()
        page_header.addWidget(self.recognize_button)
        page_header.addWidget(self.add_button)

        self.stat_values = {}
        stats = QHBoxLayout()
        stats.setSpacing(12)
        for key, caption, accent in (
            ("total", "题库题目", "statAccentBlue"),
            ("wrong", "已标记错题", "statAccentRed"),
            ("due", "当前待复习", "statAccentAmber"),
        ):
            card = QFrame()
            card.setObjectName("statCard")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(0, 13, 16, 13)
            card_layout.setSpacing(14)
            color_bar = QFrame()
            color_bar.setObjectName(accent)
            color_bar.setFixedWidth(4)
            card_text = QVBoxLayout()
            card_text.setSpacing(2)
            value = QLabel("0")
            value.setObjectName("statValue")
            label = QLabel(caption)
            label.setObjectName("cardCaption")
            card_text.addWidget(value)
            card_text.addWidget(label)
            card_layout.addWidget(color_bar)
            card_layout.addLayout(card_text)
            card_layout.addStretch()
            stats.addWidget(card, 1)
            self.stat_values[key] = value

        self.search = QLineEdit()
        self.search.setMinimumHeight(40)
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("搜索题干关键词…")

        self.subject_filter = QComboBox()
        self.subject_filter.setMinimumWidth(130)
        self.type_filter = QComboBox()
        self.type_filter.setMinimumWidth(130)
        self.state_filter = QComboBox()
        self.state_filter.setMinimumWidth(150)
        for label, value in (
            ("全部状态", "all"),
            ("错题", "wrong"),
            ("未练习", "unreviewed"),
            ("已掌握", "mastered"),
            ("还不熟", "unsure"),
            ("不会", "unknown"),
        ):
            self.state_filter.addItem(label, value)

        self.attach_button = QPushButton("图片附件")
        self.edit_button = QPushButton("编辑")
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.attach_button.clicked.connect(self.manage_attachments)
        self.edit_button.clicked.connect(self.edit_question)
        self.delete_button.clicked.connect(self.delete_question)

        toolbar = QFrame()
        toolbar.setObjectName("toolbarCard")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(14, 13, 14, 13)
        toolbar_layout.setSpacing(12)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        filters = QHBoxLayout()
        filters.setSpacing(9)
        filter_label = QLabel("筛选条件")
        filter_label.setStyleSheet("color:#7c899d;font-size:12px;font-weight:600;")
        filters.addWidget(filter_label)
        filters.addWidget(self.subject_filter)
        filters.addWidget(self.type_filter)
        filters.addWidget(self.state_filter)
        filters.addStretch()
        filters.addWidget(self.attach_button)
        filters.addWidget(self.edit_button)
        filters.addWidget(self.delete_button)
        toolbar_layout.addLayout(search_row)
        toolbar_layout.addLayout(filters)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["学科", "题型", "题目内容", "标记"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(54)
        header = self.table.horizontalHeader()
        header.setFixedHeight(42)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_question())
        self.table.selectionModel().selectionChanged.connect(self._update_actions)
        self.search.textChanged.connect(self.refresh)
        self.subject_filter.currentIndexChanged.connect(self.refresh)
        self.type_filter.currentIndexChanged.connect(self.refresh)
        self.state_filter.currentIndexChanged.connect(self.refresh)
        self._refresh_filter_options()

        table_card = QFrame()
        table_card.setObjectName("tableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(8, 8, 8, 8)
        table_layout.addWidget(self.table)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("font-size: 13px; line-height: 1.5;")
        self.empty_title = QLabel("从第一道题开始")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet("font-size:18px;font-weight:700;color:#273449;")
        self.empty_action = QPushButton("＋  新增题目")
        self.empty_action.setObjectName("primaryButton")
        self.empty_action.clicked.connect(self._empty_action)
        empty_card = QFrame()
        empty_card.setObjectName("emptyCard")
        empty_layout = QVBoxLayout(empty_card)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_label)
        empty_layout.addWidget(self.empty_action, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)

        self.content = QStackedWidget()
        self.content.addWidget(empty_card)
        self.content.addWidget(table_card)

        list_header = QHBoxLayout()
        list_title = QLabel("题目列表")
        list_title.setStyleSheet("font-size:15px;font-weight:700;color:#273449;")
        self.result_count = QLabel("共 0 道题")
        self.result_count.setObjectName("resultCount")
        list_header.addWidget(list_title)
        list_header.addStretch()
        list_header.addWidget(self.result_count)

        list_section = QVBoxLayout()
        list_section.setSpacing(10)
        list_section.addLayout(list_header)
        list_section.addWidget(self.content, 1)

        central = QWidget()
        central.setObjectName("centralPage")
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(sidebar)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 18)
        layout.setSpacing(15)
        layout.addLayout(page_header)
        layout.addLayout(stats)
        layout.addWidget(toolbar)
        layout.addLayout(list_section, 1)
        shell.addWidget(page, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("本地模式 · 题库数据保存在此设备    |    Ctrl+Alt+S 截图识题")
        self._screenshot_overlays = []
        self._screenshot_hotkey = GlobalScreenshotHotkey(self, self.capture_screenshot)
        if not self._screenshot_hotkey.registered:
            self.statusBar().showMessage(
                "本地模式 · 题库数据保存在此设备    |    Ctrl+Alt+S（仅应用打开时可用）"
            )
            screenshot_button.setToolTip("快捷键仅在本应用打开时可用：Ctrl+Alt+S")
        self.refresh()
        self._update_actions()

    def capture_screenshot(self):
        if self._screenshot_overlays:
            return
        for screen in QGuiApplication.screens():
            screenshot = screen.grabWindow(0)
            if screenshot.isNull():
                continue
            overlay = ScreenshotOverlay(screen, screenshot)
            overlay.captured.connect(self._screenshot_captured)
            overlay.cancelled.connect(self._cancel_screenshot)
            self._screenshot_overlays.append(overlay)
        if not self._screenshot_overlays:
            QMessageBox.warning(self, "截图失败", "无法读取当前屏幕，请改用图片选择或粘贴。")
            return
        for overlay in self._screenshot_overlays:
            overlay.show()
            overlay.raise_()
        self._screenshot_overlays[0].activateWindow()
        self._screenshot_overlays[0].setFocus()

    def _cancel_screenshot(self):
        for overlay in self._screenshot_overlays:
            overlay.close()
        self._screenshot_overlays.clear()

    def _screenshot_captured(self, image):
        self._cancel_screenshot()
        with tempfile.TemporaryDirectory(prefix="mistake-notebook-capture-") as directory:
            image_path = Path(directory) / "question.png"
            if not image.save(str(image_path), "PNG"):
                QMessageBox.warning(self, "截图失败", "无法保存截图，请重试或改用图片选择。")
                return
            self.start_image_recognition(image_path, auto_recognize=True)

    def closeEvent(self, event):
        self._cancel_screenshot()
        self._screenshot_hotkey.close()
        super().closeEvent(event)

    def refresh(self):
        try:
            rows = store.list_questions(
                self.search.text().strip(),
                self.subject_filter.currentData(),
                self.type_filter.currentData(),
                self.state_filter.currentData(),
            )
            summary = store.question_summary()
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法读取本地题库：\n{error}")
            return
        for key, value in zip(("total", "wrong", "due"), summary):
            self.stat_values[key].setText(f"{value:,}")
        filtered = bool(
            self.search.text().strip()
            or self.subject_filter.currentData()
            or self.type_filter.currentData()
            or self.state_filter.currentData() != "all"
        )
        self.result_count.setText(f"找到 {len(rows)} 道题" if filtered else f"共 {len(rows)} 道题")
        self.table.setRowCount(len(rows))
        for row_index, question in enumerate(rows):
            values = [
                question["subject"],
                question["question_type"],
                question["stem"].replace("\n", " "),
                "● 错题" if question["is_wrong"] else "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(question["stem"] if column == 2 else value)
                if column == 3 and question["is_wrong"]:
                    item.setForeground(Qt.GlobalColor.darkRed)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, question["id"])
                self.table.setItem(row_index, column, item)
        if rows:
            self.content.setCurrentIndex(1)
        else:
            self.empty_title.setText("没有匹配的题目" if filtered else "从第一道题开始")
            self.empty_label.setText(
                "调整关键词或筛选条件，或者一键清除筛选。"
                if filtered
                else "题目会保存在本机，之后可随时搜索、练习和复习。"
            )
            self.empty_action.setText("清除筛选" if filtered else "＋  新增题目")
            self.empty_action.setObjectName("softButton" if filtered else "primaryButton")
            self.empty_action.style().unpolish(self.empty_action)
            self.empty_action.style().polish(self.empty_action)
            self.content.setCurrentIndex(0)
        self._update_actions()

    def _empty_action(self):
        filtered = bool(
            self.search.text().strip()
            or self.subject_filter.currentData()
            or self.type_filter.currentData()
            or self.state_filter.currentData() != "all"
        )
        if not filtered:
            self.add_question()
            return
        self.search.clear()
        self.subject_filter.setCurrentIndex(0)
        self.type_filter.setCurrentIndex(0)
        self.state_filter.setCurrentIndex(0)

    def _update_actions(self, *_):
        has_selection = self._selected_id() is not None
        self.attach_button.setEnabled(has_selection)
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    def _refresh_filter_options(self):
        selected_subject = self.subject_filter.currentData()
        selected_type = self.type_filter.currentData()
        subjects, types = store.question_filter_options()
        for combo, label, values, selected in (
            (self.subject_filter, "全部学科", subjects, selected_subject),
            (self.type_filter, "全部题型", types, selected_type),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(label, "")
            for value in values:
                combo.addItem(value, value)
            index = combo.findData(selected)
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def add_question(self):
        QuestionDialog(parent=self, on_save=self._save_new_question).exec()

    def _save_new_question(self, values):
        try:
            store.save_question(values)
        except sqlite3.Error as error:
            QMessageBox.critical(self, "保存失败", f"题目没有保存：\n{error}")
            return False
        self._refresh_filter_options()
        self.refresh()
        return True

    def edit_question(self):
        question_id = self._selected_id()
        if question_id is None:
            return
        question = store.get_question(question_id)
        if question is None:
            self.refresh()
            return
        QuestionDialog(
            question,
            self,
            on_save=lambda values: self._save_existing_question(question_id, values),
        ).exec()

    def _save_existing_question(self, question_id, values):
        try:
            store.save_question(values, question_id)
        except sqlite3.Error as error:
            QMessageBox.critical(self, "保存失败", f"题目没有保存：\n{error}")
            return False
        self._refresh_filter_options()
        self.refresh()
        return True

    def delete_question(self):
        question_id = self._selected_id()
        if question_id is None:
            return
        answer = QMessageBox.question(self, "删除题目", "确定删除选中的题目吗？")
        if answer == QMessageBox.StandardButton.Yes:
            try:
                orphaned = attachments.delete_question_images(question_id)
            except sqlite3.Error as error:
                QMessageBox.critical(self, "删除失败", f"题目没有删除：\n{error}")
                return
            self._refresh_filter_options()
            self.refresh()
            if orphaned:
                QMessageBox.warning(
                    self,
                    "题目已删除",
                    "部分图片文件无法清理，可稍后手动删除：\n" + "\n".join(orphaned),
                )

    def manage_attachments(self):
        question_id = self._selected_id()
        if question_id is None:
            return
        AttachmentsDialog(question_id, self).exec()

    def recognize_selected(self):
        self.start_image_recognition()

    def start_image_recognition(self, image_path=None, auto_recognize=False):
        dialog = ImageRecognitionDialog(image_path, self, auto_recognize=auto_recognize)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_filter_options()
            self.refresh()

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.start_image_recognition(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()

    def start_practice(self):
        setup = PracticeSetupDialog(self)
        if setup.exec() != QDialog.DialogCode.Accepted:
            return
        mode, random_order = setup.values()
        try:
            questions = store.practice_questions(
                mode,
                self.search.text().strip(),
                self.subject_filter.currentData(),
                self.type_filter.currentData(),
                self.state_filter.currentData(),
            )
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法生成练习题：\n{error}")
            return
        if not questions:
            QMessageBox.information(self, "没有待练习题目", "这个范围目前没有题目。")
            return
        if random_order:
            random.shuffle(questions)
        PracticeDialog(questions, self).exec()
        self.refresh()

    def show_history(self):
        HistoryDialog(self).exec()

    def manage_profiles(self):
        ProfilesDialog(self).exec()

    def create_backup(self):
        default_path = store.DATA_DIR / "错题本备份.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, "备份题库和图片", str(default_path), "错题本备份 (*.zip)"
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        destination = Path(path)
        if destination.exists() and QMessageBox.question(
            self, "覆盖备份", f"文件已存在，确定覆盖吗？\n{destination}"
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            backup.create_backup(destination)
        except (OSError, sqlite3.Error, ValueError) as error:
            QMessageBox.critical(self, "备份失败", str(error))
            return
        QMessageBox.information(self, "备份完成", f"题库和图片已备份到：\n{destination}")

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择题库备份", str(store.DATA_DIR), "错题本备份 (*.zip)"
        )
        if not path:
            return
        answer = QMessageBox.warning(
            self,
            "确认恢复",
            "恢复会替换当前题库和图片。应用会先在 data 目录保存一份当前数据备份。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            recovery = backup.restore_backup(path)
        except (OSError, sqlite3.Error, ValueError, zipfile.BadZipFile) as error:
            QMessageBox.critical(self, "恢复失败", str(error))
            return
        self.refresh()
        QMessageBox.information(self, "恢复完成", f"当前数据已恢复。恢复前备份保存在：\n{recovery}")
