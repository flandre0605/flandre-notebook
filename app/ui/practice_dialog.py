import sqlite3
import time
import re

from PySide6.QtCore import Qt, Signal, QTimer, QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.database import store
from app.question_data import choice_mode, parse_options, question_text
from app.services.grading import grade_answer
from app.ui.motion import AnimatedButton
from app.ui.math_text import MathLabel, MathBrowser
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
        self.mini_mode = QCheckBox("以小窗模式开始（默认置顶）")
        self.use_library_filters = QCheckBox("沿用题库的搜索、题型和状态筛选")
        self.filter_hint = QLabel()
        self.filter_hint.setWordWrap(True)
        self.filter_hint.setObjectName("muted")
        self.filter_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#b84d58;font-size:12px;")
        self.limit = QSpinBox()
        self.limit.setRange(1, 200)
        self.limit.setValue(20)

        form = QFormLayout()
        form.setVerticalSpacing(16)
        form.setHorizontalSpacing(20)
        form.addRow("练习学科", self.subject)
        form.addRow("练习范围", self.mode)
        form.addRow("每轮题数（最多）", self.limit)
        form.addRow("", self.random_order)
        form.addRow("", self.mini_mode)
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

    def __init__(self, questions, parent=None, resume=None):
        super().__init__(parent)
        self.questions = questions[:]
        self.index = 0
        self.started_at = time.monotonic()
        self.correct_count = 0
        self.recorded_count = 0
        self._submitted = False
        self.setWindowTitle("练习中")
        self.resize(760, 620)
        self.setMinimumSize(600, 480)

        self.progress = QLabel()
        self.progress.setObjectName("muted")
        self.progress.setStyleSheet("font-weight: 600;")
        self.stem = MathLabel()
        self.stem.setWordWrap(True)
        self.stem.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stem.setObjectName("practiceStem")
        self.images_button = AnimatedButton("查看题目图片")
        self.images_button.clicked.connect(self.show_images)

        self.user_answer = QPlainTextEdit()
        self.user_answer.setPlaceholderText("写下你的思路或答案；点击“记录并继续”后会保存在练习记录中")
        self.user_answer.setMaximumHeight(100)
        self.choice_scroll = QScrollArea()
        self.choice_scroll.setObjectName("choiceScroll")
        self.choice_scroll.setWidgetResizable(True)
        self.choice_scroll.setMaximumHeight(230)
        self.choice_body = QWidget()
        self.choice_body.setObjectName("choiceBody")
        self.choice_body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.choice_layout = QVBoxLayout(self.choice_body)
        self.choice_scroll.setWidget(self.choice_body)
        self._choice_buttons = {}
        self._choice_mode = ""
        self.choice_group = None
        self.user_answer.textChanged.connect(self._sync_choices)
        self.reveal_button = AnimatedButton("提交并查看答案")
        self.reveal_button.setObjectName("primaryButton")
        self.reveal_button.clicked.connect(self.submit_answer)

        self.solution = MathLabel()
        self.solution.setWordWrap(True)
        self.solution.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.solution.setObjectName("practiceSolution")
        self.notes_toggle = AnimatedButton("查看个人笔记")
        self.notes_toggle.setCheckable(True)
        self.notes_view = MathBrowser()
        self.notes_view.setMaximumHeight(140)
        self.notes_toggle.toggled.connect(self._toggle_notes)
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
        self.is_wrong = QCheckBox("标记为错题（记录时保存）")
        self.refresh_review_labels()
        self.mistake_reason = QPlainTextEdit()
        self.mistake_reason.setPlaceholderText("错因（可选）")
        self.mistake_reason.setMaximumHeight(60)

        details = QFormLayout()
        details.setVerticalSpacing(10)
        details.setHorizontalSpacing(16)
        details.addRow("作答结果", self.result_choice)
        details.addRow("掌握程度", self.mastery)
        details.addRow("", self.is_wrong)
        details.addRow("错因", self.mistake_reason)
        self.record_button = AnimatedButton("记录并继续")
        self.record_button.setObjectName("primaryButton")
        self.record_button.clicked.connect(self.record_and_continue)

        self.solution.setVisible(False)
        self.notes_toggle.hide()
        self.notes_view.hide()
        self.is_wrong.hide()
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
        layout.addWidget(self.choice_scroll)
        layout.addWidget(self.user_answer)
        layout.addWidget(self.reveal_button)
        layout.addWidget(self.solution)
        layout.addWidget(self.notes_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.notes_view)
        layout.addWidget(self.judgement)
        layout.addLayout(details)
        layout.addWidget(self.record_button)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self.show_question()
        self._checkpoint = QTimer(self)
        self._checkpoint.setSingleShot(True)
        self._checkpoint.setInterval(600)
        self._checkpoint.timeout.connect(self.save_progress)
        self.user_answer.textChanged.connect(lambda: self._checkpoint.start())
        self.mistake_reason.textChanged.connect(lambda: self._checkpoint.start())
        self.result_choice.currentIndexChanged.connect(self._result_changed)
        self.mastery.currentIndexChanged.connect(lambda: self._checkpoint.start())
        self.is_wrong.toggled.connect(lambda: self._checkpoint.start())
        if resume:
            self.index = resume["index"]
            self.correct_count = resume["correct_count"]
            self.recorded_count = resume["recorded_count"]
            self.show_question()
            self.user_answer.setPlainText(resume["answer"])
            if resume["submitted"]:
                self.submit_answer()
                if self.result_choice.isEnabled():
                    self.result_choice.setCurrentIndex(max(0, self.result_choice.findData(resume["result"])))
                self.mastery.setCurrentIndex(max(0, self.mastery.findData(resume["mastery"])))
                self.mistake_reason.setPlainText(resume["mistake"])
                self.is_wrong.setChecked(resume.get("is_wrong", bool(self.questions[self.index]["is_wrong"]) or resume["result"] == "incorrect"))
            self.started_at = time.monotonic() - resume["elapsed"]
        self.save_progress()

    def session_state(self):
        return dict(ids=[question["id"] for question in self.questions], index=self.index,
                    question_content=[self.questions[self.index][field] for field in ("stem", "answer", "question_type")] +
                                     [parse_options(dict(self.questions[self.index]).get("options", {}))],
                    correct_count=self.correct_count, recorded_count=self.recorded_count,
                    answer=self.user_answer.toPlainText(), mistake=self.mistake_reason.toPlainText(),
                    submitted=self._submitted, result=self.result_choice.currentData(), mastery=self.mastery.currentData(),
                    is_wrong=self.is_wrong.isChecked(),
                    elapsed=max(0, int(time.monotonic() - self.started_at)))

    def save_progress(self):
        self._checkpoint.stop()
        if self.index >= len(self.questions):
            return
        try:
            if any(len(editor.toPlainText()) > 20000 for editor in (self.user_answer, self.mistake_reason)):
                raise ValueError("答案和错因分别最多 20000 字，请精简后保存。")
            store.save_workspace("practice", self.session_state())
        except (sqlite3.Error, ValueError) as error:
            self.judgement.setText(f"进度自动保存失败：{error}。请保留窗口并稍后重试。")
            self.judgement.show()

    def show_question(self):
        self._submitted = False
        self.user_answer.setReadOnly(False)
        question = self.questions[self.index]
        self.progress.setText(
            f"第 {self.index + 1} 题 / 共 {len(self.questions)} 题 · {question['subject'] or '未分类'}" +
            (f" · {dict(question).get('grade')}" if dict(question).get("grade") else "")
        )
        self._build_choices(question)
        self.stem.setText(question["stem"] if self._choice_mode else question_text(question))
        self.user_answer.clear()
        self.mistake_reason.clear()
        self.result_choice.setCurrentIndex(0)
        self.result_choice.setEnabled(True)
        self.mastery.setCurrentIndex(0)
        self.is_wrong.setChecked(bool(question["is_wrong"]))
        self.is_wrong.hide()
        self.notes_toggle.setChecked(False)
        self.notes_toggle.hide()
        self.notes_view.hide()
        self.notes_view.setPlainText(dict(question).get("notes", ""))
        self.judgement.setStyleSheet(f"font-weight: 600; color: {TEXT};")
        self.solution.setVisible(False)
        self.judgement.setVisible(False)
        self.result_choice.setVisible(False)
        self.mastery.setVisible(False)
        self.mistake_reason.setVisible(False)
        self.record_button.setVisible(False)
        self.reveal_button.setVisible(True)
        self.started_at = time.monotonic()
        self.refresh_review_labels()
        try:
            has_images = bool(store.list_attachments(question["id"]))
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法读取题目图片：\n{error}")
            has_images = False
        self.images_button.setVisible(has_images)
        self.content_changed.emit()

    def refresh_review_labels(self):
        intervals = store.review_intervals()
        for key, label in (("unsure", "还不熟"), ("mastered", "已掌握"), ("unknown", "不会")):
            days = intervals[key]
            suffix = f"{days} 天后复习" if days else "立即复习"
            self.mastery.setItemText(self.mastery.findData(key), f"{label}（{suffix}）")

    def _toggle_notes(self, checked):
        self.notes_view.setVisible(checked and self._submitted)
        self.notes_toggle.setText("收起个人笔记" if checked else "查看个人笔记")
        self.content_changed.emit()

    def _result_changed(self):
        if self._submitted and self.result_choice.currentData() == "incorrect":
            self.is_wrong.setChecked(True)
        self._checkpoint.start()

    def _build_choices(self, question):
        self._choice_buttons = {}
        while self.choice_layout.count():
            item = self.choice_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if self.choice_group:
            self.choice_group.deleteLater()
        self.choice_group = QButtonGroup(self.choice_body)
        options = parse_options(dict(question).get("options", {}))
        self._choice_mode = choice_mode(question["question_type"]) if options else ""
        self.choice_group.setExclusive(self._choice_mode == "single")
        for label, text in options.items() if self._choice_mode else []:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(6, 4, 6, 4)
            button = QRadioButton(label) if self._choice_mode == "single" else QCheckBox(label)
            button.setAccessibleName(f"选项 {label}")
            self.choice_group.addButton(button)
            body = MathLabel()
            body.setWordWrap(True)
            body.setMinimumWidth(0)
            body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            body.setText(text)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignTop)
            layout.addWidget(body, 1)
            self.choice_layout.addWidget(row)
            self._choice_buttons[label] = button
            button.toggled.connect(self._choice_changed)
        self.choice_scroll.setVisible(bool(self._choice_mode))
        self.choice_scroll.setEnabled(True)
        self.user_answer.setVisible(not self._choice_mode)

    def _choice_changed(self, checked):
        if self._choice_mode == "single" and not checked:
            return
        self.user_answer.setPlainText("".join(label for label, button in self._choice_buttons.items() if button.isChecked()))

    def _sync_choices(self):
        if not self._choice_mode or not self.choice_group:
            return
        answer = re.sub(r"[,，、;；\s]", "", self.user_answer.toPlainText().upper())
        if not set(answer) <= self._choice_buttons.keys() or len(answer) != len(set(answer)) or (self._choice_mode == "single" and len(answer) != 1):
            answer = ""
        self.choice_group.setExclusive(False)
        for label, button in self._choice_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(label in answer)
        self.choice_group.setExclusive(self._choice_mode == "single")

    def submit_answer(self):
        if self.index >= len(self.questions) or self._submitted:
            return
        if self._choice_mode and not any(button.isChecked() for button in self._choice_buttons.values()):
            self.judgement.setText("请先选择选项。")
            self.judgement.show()
            return
        self._submitted = True
        question = self.questions[self.index]
        answer = question["answer"].strip() or "暂无标准答案"
        explanation = question["explanation"].strip() or "暂无解析"
        self.solution.setText(f"答案：{answer}\n\n解析：{explanation}")
        self.solution.setVisible(True)
        auto_result = grade_answer(
            question["question_type"], question["answer"], self.user_answer.toPlainText(), dict(question).get("options")
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
        if self.result_choice.currentData() == "incorrect":
            self.is_wrong.setChecked(True)
        self.is_wrong.show()
        self.notes_toggle.setVisible(bool(dict(question).get("notes")))
        self.mastery.setVisible(True)
        self.mistake_reason.setVisible(True)
        self.record_button.setVisible(True)
        self.reveal_button.setVisible(False)
        self.user_answer.setReadOnly(True)
        for button in self._choice_buttons.values():
            button.setEnabled(False)
        self.content_changed.emit()
        if hasattr(self, "_checkpoint"):
            self.save_progress()

    def show_images(self):
        self.images_requested.emit(self.questions[self.index]["id"])

    def record_and_continue(self):
        if self.index >= len(self.questions) or not self._submitted:
            return
        question = self.questions[self.index]
        result = self.result_choice.currentData()
        next_state = self.session_state()
        next_state.update(index=self.index + 1, recorded_count=self.recorded_count + 1,
                          correct_count=self.correct_count + int(result == "correct"),
                          answer="", mistake="", submitted=False, elapsed=0, result="correct", mastery="unsure")
        if self.index + 1 < len(self.questions):
            next_state["is_wrong"] = bool(self.questions[self.index + 1]["is_wrong"])
            next_state["question_content"] = [self.questions[self.index + 1][field] for field in ("stem", "answer", "question_type")] + \
                                             [parse_options(dict(self.questions[self.index + 1]).get("options", {}))]
        try:
            store.record_attempt(
                question["id"],
                result,
                int(time.monotonic() - self.started_at),
                self.mastery.currentData(),
                self.mistake_reason.toPlainText(),
                self.user_answer.toPlainText(),
                session_state=next_state,
                is_wrong=self.is_wrong.isChecked(),
            )
        except (sqlite3.Error, ValueError) as error:
            self.judgement.setText(f"记录失败，本题没有保存：{error}")
            self.judgement.setStyleSheet("font-weight:600;color:#b84d58;")
            self.judgement.setVisible(True)
            return

        self._checkpoint.stop()

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
                self.images_button, self.choice_scroll, self.user_answer, self.reveal_button, self.solution,
                self.judgement, self.result_choice, self.mastery, self.mistake_reason,
                self.notes_toggle, self.notes_view, self.is_wrong,
            ):
                widget.hide()
            self.record_button.setText("返回题库")
            self.record_button.clicked.disconnect(self.record_and_continue)
            self.record_button.clicked.connect(self.accept)
            self.content_changed.emit()
            return
        self.show_question()
        self.user_answer.setReadOnly(False)
        self._checkpoint.stop()

    def done(self, result):
        self.save_progress()
        super().done(result)


def load_practice_progress():
    state = store.load_workspace("practice")
    if not state:
        return None
    try:
        ids = state["ids"]
        if not isinstance(ids, list) or not ids or len(ids) > 5000 or len(set(ids)) != len(ids):
            return None
        if any(type(value) is not int or value <= 0 for value in ids):
            return None
        index = state["index"]
        if type(index) is not int or not 0 <= index < len(ids):
            return None
        if any(type(state[key]) is not int or not 0 <= state[key] <= 100000000 for key in ("correct_count", "recorded_count", "elapsed")):
            return None
        if state["correct_count"] > state["recorded_count"] or state["recorded_count"] != index:
            return None
        if any(not isinstance(state[key], str) or len(state[key]) > 20000 for key in ("answer", "mistake", "result", "mastery")):
            return None
        if type(state["submitted"]) is not bool or state["result"] not in ("correct", "incorrect", "skipped") or state["mastery"] not in ("mastered", "unsure", "unknown"):
            return None
        if "is_wrong" in state and type(state["is_wrong"]) is not bool:
            return None
        questions = [store.get_question(question_id) for question_id in ids]
        if any(question is None for question in questions):
            return None
        if state.get("question_content") != [questions[index][field] for field in ("stem", "answer", "question_type")] + \
                                            [parse_options(dict(questions[index]).get("options", {}))]:
            state["submitted"] = False
        return questions, state
    except (KeyError, TypeError, ValueError):
        return None
