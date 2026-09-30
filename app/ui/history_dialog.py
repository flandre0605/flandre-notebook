import sqlite3

from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.database import store


class HistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("练习记录")
        self.resize(900, 560)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["时间（UTC）", "学科", "题目", "结果", "掌握程度", "用时", "错因"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 3, 4, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(self.table)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self.refresh()

    def refresh(self):
        try:
            rows = store.list_attempts()
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法读取练习记录：\n{error}")
            return
        result_names = {"correct": "正确", "incorrect": "错误", "skipped": "跳过"}
        mastery_names = {"mastered": "已掌握", "unsure": "还不熟", "unknown": "不会"}
        self.table.setRowCount(len(rows))
        for index, attempt in enumerate(rows):
            values = (
                attempt["answered_at"],
                attempt["subject"],
                attempt["stem"].replace("\n", " "),
                result_names[attempt["result"]],
                mastery_names[attempt["mastery"]],
                f"{attempt['duration_seconds']} 秒",
                attempt["mistake_reason"],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 2:
                    item.setToolTip(attempt["stem"])
                self.table.setItem(index, column, item)
