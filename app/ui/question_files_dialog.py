from pathlib import Path
import sqlite3
import csv

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
                              QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout)

from app.services import question_files
from app.ui.motion import AnimatedButton
from app.ui.options_editor import OptionsEditor
from app.question_data import QUESTION_LABELS


class QuestionFilesDialog(QDialog):
    def __init__(self, filters, on_import, parent=None):
        super().__init__(parent)
        self.filters = filters
        self.on_import = on_import
        self.rows = []
        self.setStyleSheet(parent.styleSheet() if parent else "")
        layout = QVBoxLayout(self)
        caption = QLabel("JSON / CSV 交换题目文字，PDF 用于打印。图片、练习进度和模型配置请使用完整备份。")
        caption.setWordWrap(True)
        caption.setObjectName("muted")
        layout.addWidget(caption)
        actions = QHBoxLayout()
        choose = AnimatedButton("选择文件并核对")
        choose.clicked.connect(self.choose_file)
        self.import_button = AnimatedButton("确认导入")
        self.import_button.setObjectName("primaryButton")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.confirm_import)
        actions.addWidget(choose)
        actions.addWidget(self.import_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.table = QTableWidget(0, len(question_files.FIELDS))
        self.table.setHorizontalHeaderLabels([QUESTION_LABELS[field] + (" *" if field == "stem" else "（0/1）" if field == "is_wrong" else "")
                                             for field in question_files.FIELDS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 260)
        for column in range(1, self.table.columnCount()):
            self.table.setColumnWidth(column, 115)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.itemChanged.connect(lambda: self.import_button.setEnabled(self.table.rowCount() > 0))
        layout.addWidget(self.table, 1)
        self.options_toggle = AnimatedButton("编辑选中题目的选项")
        self.options_toggle.setCheckable(True)
        self.options_toggle.setEnabled(False)
        layout.addWidget(self.options_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.options_editor = OptionsEditor()
        self.options_editor.hide()
        self.options_toggle.toggled.connect(self.options_editor.setVisible)
        self.options_editor.changed.connect(self._save_options)
        self.table.currentCellChanged.connect(self._load_options)
        layout.addWidget(self.options_editor)
        hint = QLabel("导入前可双击修改单元格；完全相同的题目会跳过，已有题目和复习记录保留。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        export = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItem("导出当前题库筛选结果", "filtered")
        self.scope.addItem("导出全部题目", "all")
        self.format = QComboBox()
        for name in ("JSON", "CSV", "PDF"):
            self.format.addItem(name, name.lower())
        self.solutions = QCheckBox("PDF 包含答案、解析与笔记")
        self.solutions.setChecked(True)
        self.solutions.setEnabled(False)
        self.format.currentIndexChanged.connect(lambda: self.solutions.setEnabled(self.format.currentData() == "pdf"))
        save = AnimatedButton("导出到文件")
        save.clicked.connect(self.export_file)
        export.addWidget(self.scope)
        export.addWidget(self.format)
        export.addWidget(self.solutions)
        export.addStretch()
        export.addWidget(save)
        layout.addLayout(export)
        self.status = QLabel("选择 JSON 或 CSV 文件开始；每次最多 5 MB / 5000 道题目。")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入题库文字", "", "题库文件 (*.json *.csv)")
        if not path:
            return
        try:
            rows = question_files.read_questions(path)
        except (OSError, ValueError, UnicodeError, csv.Error) as error:
            self.status.setText(f"读取失败：{error}。原有草稿和题库没有修改。")
            return
        self.rows = rows
        self.table.setCurrentCell(-1, -1)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, field in enumerate(question_files.FIELDS):
                item = QTableWidgetItem(str(row[field]) if field != "options" else f"{len(row[field])} 个选项")
                if field == "options":
                    item.setData(Qt.ItemDataRole.UserRole, row[field])
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setToolTip(str(row[field]))
                self.table.setItem(index, column, item)
        self.table.setCurrentCell(0, 0)
        self.import_button.setEnabled(True)
        self.status.setText(f"已读取 {len(rows)} 道题目，请核对后点击确认导入。")

    def confirm_import(self):
        rows = [{field: (self.table.item(index, column).data(Qt.ItemDataRole.UserRole) if field == "options"
                        else self.table.item(index, column).text())
                 for column, field in enumerate(question_files.FIELDS)} for index in range(self.table.rowCount())]
        try:
            added, skipped = question_files.import_questions(rows)
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(f"导入失败：{error}。本次没有写入题目，请修改后重试。")
            return
        self.import_button.setEnabled(False)
        self.status.setText(f"导入完成：新增 {added} 道，跳过 {skipped} 道重复题目。")
        self.on_import()

    def _load_options(self, *_):
        row = self.table.currentRow()
        item = self.table.item(row, question_files.FIELDS.index("options")) if row >= 0 else None
        self.options_toggle.setEnabled(item is not None)
        self.options_editor.setEnabled(item is not None)
        self.options_editor.set_options(item.data(Qt.ItemDataRole.UserRole) if item else {})

    def _save_options(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, question_files.FIELDS.index("options"))
        options = self.options_editor.options()
        item.setData(Qt.ItemDataRole.UserRole, options)
        item.setText(f"{len(options)} 个选项")
        self.import_button.setEnabled(True)

    def export_file(self):
        suffix = self.format.currentData()
        path, _ = QFileDialog.getSaveFileName(self, "导出题目", f"我的题库.{suffix}", f"{suffix.upper()} 文件 (*.{suffix})")
        if not path:
            return
        if Path(path).suffix.lower() != f".{suffix}":
            path += f".{suffix}"
        try:
            rows = question_files.export_rows(**(self.filters if self.scope.currentData() == "filtered" else {}))
            question_files.write_questions(path, rows, self.solutions.isChecked())
        except (sqlite3.Error, OSError, ValueError) as error:
            self.status.setText(f"导出失败：{error}")
            return
        self.status.setText(f"已导出 {len(rows)} 道题目到：{path}")
