from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class LearningHeatmap(QFrame):
    COLORS = ("#f8edf2", "#f2cddd", "#e8a5c0", "#cf7599", "#b54b72")
    LEVEL_NAMES = ("0 次", "1–4 次", "5–9 次", "10–19 次", "20 次及以上")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("learningHeatmap")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        title = QLabel("近 90 天学习足迹")
        title.setObjectName("sectionTitle")
        self.date_range = QLabel()
        self.date_range.setObjectName("muted")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.date_range)
        layout.addLayout(heading)

        self.calendar = QWidget()
        self.grid = QGridLayout(self.calendar)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(5)
        layout.addWidget(self.calendar, 0, Qt.AlignmentFlag.AlignHCenter)

        footer = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        footer.addWidget(self.summary, 1)
        legend = QHBoxLayout()
        legend.setSpacing(4)
        legend.addWidget(QLabel("少"))
        for color, name in zip(self.COLORS, self.LEVEL_NAMES):
            square = self._square(color, 12)
            square.setToolTip(name)
            legend.addWidget(square)
        legend.addWidget(QLabel("多"))
        footer.addLayout(legend)
        layout.addLayout(footer)
        self.cells = {}

    @staticmethod
    def _square(color, size=26, today=False):
        square = QLabel()
        square.setFixedSize(size, size)
        border = "#913455" if today else "#efdce5"
        square.setStyleSheet(
            f"background: {color}; border: 1px solid {border}; border-radius: 4px;"
        )
        return square

    def set_daily(self, rows):
        while self.grid.count():
            widget = self.grid.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self.cells.clear()
        end = date.today()
        start = end - timedelta(days=89)
        first_monday = start - timedelta(days=start.weekday())
        self.date_range.setText(f"{start:%Y-%m-%d} — {end:%Y-%m-%d}")
        daily = {row["day"]: row for row in rows}
        for weekday, name in ((0, "周一"), (2, "周三"), (4, "周五")):
            label = QLabel(name)
            label.setObjectName("muted")
            self.grid.addWidget(label, weekday + 1, 0)

        attempts = active_days = 0
        previous_month = None
        months = {}
        for offset in range(90):
            day = start + timedelta(days=offset)
            column = (day - first_monday).days // 7 + 1
            if day.month != previous_month:
                months[column] = day.month
                previous_month = day.month
            row = daily.get(day.isoformat(), {})
            count = row.get("attempts", 0)
            correct = row.get("correct", 0)
            incorrect = row.get("incorrect", 0)
            judged = correct + incorrect
            accuracy = f"{correct / judged:.0%}" if judged else "—"
            level = sum(count >= threshold for threshold in (1, 5, 10, 20))
            square = self._square(self.COLORS[level], today=day == end)
            tooltip = (
                f"{day:%Y-%m-%d}" + ("（今天）" if day == end else "")
                + f"\n记录数：{count}\n正确：{correct}  ·  错误：{incorrect}"
                + f"\n跳过：{count - judged}\n正确率：{accuracy}"
            )
            square.setToolTip(tooltip)
            square.setAccessibleName(tooltip.replace("\n", "，"))
            self.grid.addWidget(square, day.weekday() + 1, column)
            self.cells[day.isoformat()] = square
            attempts += count
            active_days += bool(count)

        for column, month in months.items():
            label = QLabel(f"{month}月")
            label.setObjectName("muted")
            self.grid.addWidget(label, 0, column)
        self.summary.setText(
            f"近 90 天 {attempts} 次记录 · 学习 {active_days} 天"
            if attempts else "暂无练习记录，完成练习后会点亮方格。"
        )
