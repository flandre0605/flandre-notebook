import sqlite3
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from app.database import store
from app.services.grading import grade_answer
from app.ui.motion import AnimatedButton
from app.ui.theme import TEXT


class PracticeSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("开始练习")
        self.resize(380, 190)

        self.mode = QComboBox()
        self.mode.addItem("全部题目", "all")
        self.mode.addItem("仅错题", "wrong")
        self.mode.addItem("到期复习", "due")
        self.subject = QComboBox()
        self.subject.addItem("全部学科", "")
        self.random_order = QCheckBox("随机排列题目")
        self.use_library_filters = QCheckBox("沿用题库的搜索、题型和状态筛选")
        self.filter_hint = QLabel()
        self.filter_hint.setWordWrap(True)
        self.filter_hint.setObjectName("muted")
        self.filter_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#b84d58;font-size:12px;")

        form = QFormLayout()
        form.setVerticalSpacing(16)
        form.setHorizontalSpacing(20)
        form.addRow("练习学科", self.subject)
        form.addRow("练习范围", self.mode)
        form.addRow("", self.random_order)
        form.addRow("", self.use_library_filters)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("开始练习")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("返回题库")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        card = QFrame()
        card.setMaximumWidth(650)
        card.setObjectName("formCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(20)
        heading = QLabel("选择本轮练习的题目")
        heading.setObjectName("detailTitle")
        caption = QLabel("学科与范围可以组合，例如“数学 + 仅错题”。默认不受题库其他筛选影响。")
        caption.setObjectName("muted")
        caption.setWordWrap(True)
        card_layout.addWidget(heading)
        card_layout.addWidget(caption)
        card_layout.addLayout(form)
        card_layout.addWidget(self.filter_hint)
        card_layout.addWidget(self.status)
        card_layout.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)
        layout.addStretch()

    def refresh_subjects(self):
        selected = self.subject.currentData()
        try:
            subjects, _ = store.question_filter_options()
        except sqlite3.Error as error:
            self.status.setText(f"无法读取学科列表：{error}")
            return
        self.subject.clear()
        self.subject.addItem("全部学科", "")
        for subject in subjects:
            self.subject.addItem(subject, subject)
        self.subject.setCurrentIndex(max(0, self.subject.findData(selected)))
        self.status.clear()

    def values(self):
        return (
            self.mode.currentData(), self.subject.currentData(),
            self.random_order.isChecked(), self.use_library_filters.isChecked(),
        )


class PracticeDialog(QDialog):
    images_requested = Signal(int)
    content_changed = Signal()

    def __init__(self, questions, parent=None):
        super().__init__(parent)
        self.questions = questions[:]
        self.index = 0
        self.started_at = time.monotonic()
        self.correct_count = 0
        self.recorded_count = 0
        self.setWindowTitle("练习中")
        self.resize(760, 620)
        self.setMinimumSize(600, 480)

        self.progress = QLabel()
        self.progress.setObjectName("muted")
        self.progress.setStyleSheet("font-weight: 600;")
        self.stem = QLabel()
        self.stem.setWordWrap(True)
        self.stem.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stem.setObjectName("practiceStem")
        self.images_button = AnimatedButton("查看题目图片")
        self.images_button.clicked.connect(self.show_images)

        self.user_answer = QPlainTextEdit()
        self.user_answer.setPlaceholderText("写下你的思路或答案；点击“记录并继续”后会保存在练习记录中")
        self.user_answer.setMaximumHeight(100)
        self.reveal_button = AnimatedButton("提交并查看答案")
        self.reveal_button.setObjectName("primaryButton")
        self.reveal_button.clicked.connect(self.submit_answer)

        self.solution = QLabel()
        self.solution.setWordWrap(True)
        self.solution.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.solution.setObjectName("practiceSolution")
        self.judgement = QLabel()
        self.judgement.setWordWrap(True)
        self.judgement.setStyleSheet(f"font-weight: 600; color: {TEXT};")
        self.result_choice = QComboBox()
        self.result_choice.addItem("自评正确", "correct")
        self.result_choice.addItem("自评错误", "incorrect")
        self.result_choice.addItem("跳过", "skipped")
        self.mastery = QComboBox()
        self.mastery.addItem("还不熟（明天复习）", "unsure")
        self.mastery.addItem("已掌握（一周后复习）", "mastered")
        self.mastery.addItem("不会（继续列入复习）", "unknown")
        self.mistake_reason = QPlainTextEdit()
        self.mistake_reason.setPlaceholderText("错因（可选）")
        self.mistake_reason.setMaximumHeight(60)

        details = QFormLayout()
        details.addRow("作答结果", self.result_choice)
        details.addRow("掌握程度", self.mastery)
        details.addRow("错因", self.mistake_reason)
        self.record_button = AnimatedButton("记录并继续")
        self.record_button.setObjectName("primaryButton")
        self.record_button.clicked.connect(self.record_and_continue)

        self.solution.setVisible(False)
        self.judgement.setVisible(False)
        self.result_choice.setVisible(False)
        self.mastery.setVisible(False)
        self.mistake_reason.setVisible(False)
        self.record_button.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)
        layout.addWidget(self.progress)
        layout.addWidget(self.stem, 1)
        layout.addWidget(self.images_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.user_answer)
        layout.addWidget(self.reveal_button)
        layout.addWidget(self.solution)
        layout.addWidget(self.judgement)
        layout.addLayout(details)
        layout.addWidget(self.record_button)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self.show_question()

    def show_question(self):
        question = self.questions[self.index]
        self.progress.setText(
            f"第 {self.index + 1} 题 / 共 {len(self.questions)} 题 · {question['subject'] or '未分类'}"
        )
        self.stem.setText(question["stem"])
        self.user_answer.clear()
        self.solution.setVisible(False)
        self.judgement.setVisible(False)
        self.result_choice.setVisible(False)
        self.mastery.setVisible(False)
        self.mistake_reason.setVisible(False)
        self.record_button.setVisible(False)
        self.reveal_button.setVisible(True)
        self.started_at = time.monotonic()
        try:
            has_images = bool(store.list_attachments(question["id"]))
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法读取题目图片：\n{error}")
            has_images = False
        self.images_button.setVisible(has_images)
        self.content_changed.emit()

    def submit_answer(self):
        question = self.questions[self.index]
        answer = question["answer"].strip() or "暂无标准答案"
        explanation = question["explanation"].strip() or "暂无解析"
        self.solution.setText(f"答案：{answer}\n\n解析：{explanation}")
        self.solution.setVisible(True)
        auto_result = grade_answer(
            question["question_type"], question["answer"], self.user_answer.toPlainText()
        )
        if auto_result is None:
            self.judgement.setText("此题需要自评，请选择作答结果。")
            self.result_choice.setEnabled(True)
        else:
            self.judgement.setText(
                "系统判定：正确" if auto_result else "系统判定：与标准答案不一致"
            )
            self.result_choice.setCurrentIndex(0 if auto_result else 1)
            self.result_choice.setEnabled(False)
        self.judgement.setVisible(True)
        self.result_choice.setVisible(True)
        self.mastery.setVisible(True)
        self.mistake_reason.setVisible(True)
        self.record_button.setVisible(True)
        self.reveal_button.setVisible(False)
        self.content_changed.emit()

    def show_images(self):
        self.images_requested.emit(self.questions[self.index]["id"])

    def record_and_continue(self):
        question = self.questions[self.index]
        result = self.result_choice.currentData()
        try:
            store.record_attempt(
                question["id"],
                result,
                int(time.monotonic() - self.started_at),
                self.mastery.currentData(),
                self.mistake_reason.toPlainText(),
                self.user_answer.toPlainText(),
            )
        except (sqlite3.Error, ValueError) as error:
            self.judgement.setText(f"记录失败，本题没有保存：{error}")
            self.judgement.setStyleSheet("font-weight:600;color:#b84d58;")
            self.judgement.setVisible(True)
            return

        self.recorded_count += 1
        if result == "correct":
            self.correct_count += 1
        self.index += 1
        if self.index == len(self.questions):
            self.progress.setText("本轮练习已完成")
            self.stem.setText(
                f"已完成 {self.recorded_count} 题\n\n记录为正确：{self.correct_count} 题"
            )
            for widget in (
                self.images_button, self.user_answer, self.reveal_button, self.solution,
                self.judgement, self.result_choice, self.mastery, self.mistake_reason,
            ):
                widget.hide()
            self.record_button.setText("返回题库")
            self.record_button.clicked.disconnect(self.record_and_continue)
            self.record_button.clicked.connect(self.accept)
            self.content_changed.emit()
            return
        self.show_question()
