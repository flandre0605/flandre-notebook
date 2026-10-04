import sqlite3
from PySide6.QtCore import Qt

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QHeaderView,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.database import store
from app.ui.learning_heatmap import LearningHeatmap


class HistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("练习记录")
        self.resize(900, 560)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["时间（UTC）", "学科", "题目", "我的作答", "结果", "掌握程度", "用时", "错因"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 4, 5, 6, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        tabs = QTabWidget()
        statistics = QWidget()
        stats_layout = QVBoxLayout(statistics)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("sectionTitle")
        stats_layout.addWidget(self.summary)
        self.subject_table = QTableWidget(0, 5)
        self.subject_table.setHorizontalHeaderLabels(["学科", "已判定作答", "正确率", "跳过", "累计用时"])
        self.heatmap = LearningHeatmap()
        self.subject_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.subject_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.subject_table.verticalHeader().hide()
        self.subject_table.setShowGrid(False)
        self.subject_table.setAlternatingRowColors(True)
        stats_layout.addWidget(self.subject_table, 1)
        stats_layout.addWidget(self.heatmap)
        self.suggestion = QLabel()
        self.suggestion.setWordWrap(True)
        self.suggestion.setTextFormat(Qt.TextFormat.PlainText)
        stats_layout.addWidget(self.suggestion)
        note = QLabel("正确率 = 正确 ÷（正确 + 错误）；跳过不计入分母。统计包含所有题目练习记录，自评结果也计入；单词复习另行保存。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        stats_layout.addWidget(note)
        tabs.addTab(statistics, "学习统计")
        tabs.addTab(self.table, "最近 500 条记录")
        layout.addWidget(tabs)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self.refresh()

    def refresh(self):
        try:
            rows = store.list_attempts()
            statistics = store.learning_statistics()
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法读取练习记录：\n{error}")
            return
        self._show_statistics(statistics)
        result_names = {"correct": "正确", "incorrect": "错误", "skipped": "跳过"}
        mastery_names = {"mastered": "已掌握", "unsure": "还不熟", "unknown": "不会"}
        self.table.setRowCount(len(rows))
        for index, attempt in enumerate(rows):
            values = (
                attempt["answered_at"],
                attempt["subject"],
                attempt["stem"].replace("\n", " "),
                attempt["user_answer"].replace("\n", " "),
                result_names[attempt["result"]],
                mastery_names[attempt["mastery"]],
                f"{attempt['duration_seconds']} 秒",
                attempt["mistake_reason"],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (2, 3):
                    item.setToolTip(
                        attempt["stem"] if column == 2 else attempt["user_answer"]
                    )
                self.table.setItem(index, column, item)

    @staticmethod
    def _accuracy(row):
        count = row["correct"] + row["incorrect"]
        return f"{row['correct'] / count:.0%}" if count else "—"

    def _show_statistics(self, statistics):
        total = statistics["total"]
        self.summary.setText(f"累计 {total['attempts']} 次记录  ·  正确率 {self._accuracy(total)}"
                             f"  ·  学习 {total['days']} 天  ·  用时 {total['seconds'] // 60} 分钟")
        subjects = sorted(statistics["subjects"], key=lambda row: (
            row["correct"] / (row["correct"] + row["incorrect"]) if row["correct"] + row["incorrect"] else 2))
        self.subject_table.setRowCount(len(subjects))
        for index, row in enumerate(subjects):
            values = (row["subject"] or "未分类", row["correct"] + row["incorrect"], self._accuracy(row),
                      row["skipped"], f"{row['seconds'] // 60} 分钟")
            for column, value in enumerate(values):
                self.subject_table.setItem(index, column, QTableWidgetItem(str(value)))
        self.heatmap.set_daily(statistics["daily"])
        eligible = [row for row in subjects if row["correct"] + row["incorrect"] >= 3 and row["incorrect"]]
        text = (f"可优先复习：{eligible[0]['subject'] or '未分类'}（已判定至少 3 次的学科中正确率最低）。"
                if eligible else "再积累一些作答记录后，这里会提示可优先复习的学科。")
        if statistics["reasons"]:
            text += "\n常见错因：" + "；".join(f"{row['mistake_reason']}（{row['count']} 次）" for row in statistics["reasons"])
        self.suggestion.setText(text)
