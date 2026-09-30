import random
import sqlite3
from pathlib import Path
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
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


STYLE = """
QMainWindow, QDialog { background: #f4f6fa; }
QLabel { color: #263248; }
QLabel#pageTitle { color: #182338; font-size: 25px; font-weight: 700; }
QLabel#pageSubtitle, QLabel#muted { color: #7b8799; font-size: 12px; }
QLabel#resultCount { color: #67748a; font-size: 12px; }
QFrame#toolbarCard, QFrame#tableCard, QFrame#emptyCard {
    background: #ffffff; border: 1px solid #e7ebf2; border-radius: 12px;
}
QLineEdit, QPlainTextEdit {
    background: #ffffff; border: 1px solid #dfe5ee; border-radius: 8px;
    padding: 9px 11px; color: #263248; selection-background-color: #dce8ff;
}
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #6d91e8; }
QPushButton {
    background: #ffffff; color: #46536a; border: 1px solid #dfe5ee;
    border-radius: 8px; padding: 9px 15px; font-weight: 600;
}
QPushButton:hover { background: #f5f7fb; border-color: #cbd4e2; }
QPushButton:disabled { color: #aab3c0; background: #f7f8fa; }
QPushButton#primaryButton { background: #4169d8; color: #ffffff; border-color: #4169d8; }
QPushButton#primaryButton:hover { background: #345bc8; }
QPushButton#practiceButton { background: #e9f5ef; color: #27734b; border-color: #d5ecdf; }
QPushButton#practiceButton:hover { background: #def0e6; }
QPushButton#dangerButton { color: #b84d58; }
QTableWidget {
    background: #ffffff; alternate-background-color: #fafbfd;
    border: none; color: #344158; selection-background-color: #e9f0ff;
    selection-color: #233d78; outline: 0;
}
QHeaderView::section {
    background: #f8f9fc; color: #778399; border: none;
    border-bottom: 1px solid #e9edf3; padding: 10px 12px; font-weight: 600;
}
QTableWidget::item { padding-left: 10px; border: none; }
QStatusBar { background: transparent; color: #8a95a5; font-size: 11px; }
QDialogButtonBox QPushButton { min-width: 82px; }
QCheckBox { color: #46536a; spacing: 8px; }
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
        self.resize(1120, 720)
        self.setMinimumSize(820, 560)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self._build_menus()

        title = QLabel("我的题库")
        title.setObjectName("pageTitle")
        subtitle = QLabel("把做过的题整理好，让每次复习都更有方向。")
        subtitle.setObjectName("pageSubtitle")
        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        self.result_count = QLabel("共 0 道题")
        self.result_count.setObjectName("resultCount")
        page_header = QHBoxLayout()
        page_header.addLayout(title_block)
        page_header.addStretch()
        page_header.addWidget(self.result_count, alignment=Qt.AlignmentFlag.AlignBottom)

        self.search = QLineEdit()
        self.search.setMinimumHeight(42)
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

        self.add_button = QPushButton("新增题目")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setMinimumHeight(42)
        self.attach_button = QPushButton("图片附件")
        self.recognize_button = QPushButton("AI 识题")
        self.practice_button = QPushButton("开始练习")
        self.practice_button.setObjectName("practiceButton")
        self.history_button = QPushButton("练习记录")
        self.edit_button = QPushButton("编辑")
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.add_button.clicked.connect(self.add_question)
        self.attach_button.clicked.connect(self.manage_attachments)
        self.recognize_button.clicked.connect(self.recognize_selected)
        self.practice_button.clicked.connect(self.start_practice)
        self.history_button.clicked.connect(self.show_history)
        self.edit_button.clicked.connect(self.edit_question)
        self.delete_button.clicked.connect(self.delete_question)

        toolbar = QFrame()
        toolbar.setObjectName("toolbarCard")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(14, 12, 14, 12)
        toolbar_layout.setSpacing(10)
        actions = QHBoxLayout()
        actions.setSpacing(9)
        actions.addWidget(self.search, 1)
        actions.addWidget(self.add_button)
        actions.addWidget(self.attach_button)
        actions.addWidget(self.recognize_button)
        actions.addWidget(self.practice_button)
        actions.addWidget(self.history_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(QLabel("筛选"))
        filters.addWidget(self.subject_filter)
        filters.addWidget(self.type_filter)
        filters.addWidget(self.state_filter)
        filters.addStretch()
        toolbar_layout.addLayout(actions)
        toolbar_layout.addLayout(filters)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["学科", "题型", "题干", "错题"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
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
        self.empty_label.setStyleSheet("font-size: 14px; line-height: 1.5;")
        empty_card = QFrame()
        empty_card.setObjectName("emptyCard")
        empty_layout = QVBoxLayout(empty_card)
        empty_layout.addWidget(self.empty_label)

        self.content = QStackedWidget()
        self.content.addWidget(empty_card)
        self.content.addWidget(table_card)

        central = QWidget()
        central.setObjectName("centralPage")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 26, 30, 16)
        layout.setSpacing(18)
        layout.addLayout(page_header)
        layout.addWidget(toolbar)
        layout.addWidget(self.content, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("本地保存 · data/questions.db")
        self.refresh()
        self._update_actions()

    def refresh(self):
        try:
            rows = store.list_questions(
                self.search.text().strip(),
                self.subject_filter.currentData(),
                self.type_filter.currentData(),
                self.state_filter.currentData(),
            )
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法读取本地题库：\n{error}")
            return
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
            self.empty_label.setText(
                "没有找到符合条件的题目\n可以更换关键词或筛选条件。"
                if filtered
                else "这里还没有题目\n点击「新增题目」开始整理你的错题。"
            )
            self.content.setCurrentIndex(0)
        self._update_actions()

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

    def start_image_recognition(self, image_path=None):
        dialog = ImageRecognitionDialog(image_path, self)
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

    def _build_menus(self):
        settings_menu = self.menuBar().addMenu("设置")
        profiles_action = QAction("模型服务…", self)
        profiles_action.triggered.connect(self.manage_profiles)
        settings_menu.addAction(profiles_action)
        data_menu = self.menuBar().addMenu("数据")
        backup_action = QAction("备份数据…", self)
        restore_action = QAction("从备份恢复…", self)
        backup_action.triggered.connect(self.create_backup)
        restore_action.triggered.connect(self.restore_backup)
        data_menu.addAction(backup_action)
        data_menu.addAction(restore_action)

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
