from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)


class RecognitionDraftDialog(QDialog):
    def __init__(self, question, image_path, draft, parent=None):
        super().__init__(parent)
        self.drafts = draft if isinstance(draft, list) else [draft]
        self.drafts = [dict(item) for item in self.drafts]
        self.current_index = 0
        self.question = question
        self.setWindowTitle(f"检查 AI 识题草稿（{len(self.drafts)} 道）")
        self.resize(980, 700)
        self.setStyleSheet("QDialog{background:#f4f6fa;} QLineEdit,QPlainTextEdit{background:white;border:1px solid #dfe5ee;border-radius:7px;padding:7px;}")
        self.image = QLabel("原图")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(350, 300)
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            self.image.setPixmap(pixmap.scaled(440, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.stem = QPlainTextEdit()
        self.stem.setMinimumHeight(110)
        self.subject = QLineEdit()
        self.question_type = QLineEdit()
        self.answer = QPlainTextEdit()
        self.answer.setMinimumHeight(65)
        self.explanation = QPlainTextEdit()
        self.explanation.setMinimumHeight(100)
        self.is_wrong = QCheckBox("标记为错题")
        self.is_wrong.setChecked(bool(question["is_wrong"]) if question is not None else True)

        self.question_selector = QComboBox()
        for index in range(len(self.drafts)):
            self.question_selector.addItem(f"第 {index + 1} 题", index)
        self.question_selector.setVisible(len(self.drafts) > 1)
        self.remove_draft_button = QPushButton("移除此题")
        self.remove_draft_button.setVisible(len(self.drafts) > 1)
        self.remove_draft_button.clicked.connect(self._remove_current_draft)
        form = QFormLayout()
        for label, field in (("题干 *", self.stem), ("学科", self.subject), ("题型", self.question_type), ("答案", self.answer), ("解析", self.explanation)):
            form.addRow(label, field)
        form.addRow("", self.is_wrong)
        content = QHBoxLayout()
        content.addWidget(self.image, 1)
        content.addLayout(form, 2)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setObjectName("primaryButton")
        save_button.setMinimumHeight(38)
        save_button.setText(
            "确认并更新题目" if question is not None else f"确认并收录 {len(self.drafts)} 道题"
        )
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        instruction = (
            "AI 生成的是草稿，请核对后确认更新。"
            if question is not None
            else f"识别到 {len(self.drafts)} 道题。可逐题核对，确认后统一收录并保存原图。"
        )
        review_row = QHBoxLayout()
        self.instruction_label = QLabel(instruction)
        self.progress_label = QLabel()
        self.progress_label.setStyleSheet(
            "background:#edf2ff;color:#365dcc;border-radius:10px;padding:5px 10px;font-weight:600;"
        )
        review_row.addWidget(self.instruction_label, 1)
        review_row.addWidget(self.progress_label)
        review_row.addWidget(self.question_selector)
        review_row.addWidget(self.remove_draft_button)
        layout.addLayout(review_row)
        layout.addLayout(content, 1)
        layout.addWidget(self.buttons)
        self._load_draft(0)
        self._update_progress()
        self.question_selector.currentIndexChanged.connect(self._switch_draft)

    def _load_draft(self, index):
        draft = self.drafts[index]
        self.stem.setPlainText(draft.get("stem", ""))
        self.subject.setText(draft.get("subject", ""))
        self.question_type.setText(draft.get("question_type", ""))
        self.answer.setPlainText(draft.get("answer", ""))
        self.explanation.setPlainText(draft.get("explanation", ""))
        self.is_wrong.setChecked(
            bool(draft.get("is_wrong", self.question["is_wrong"] if self.question else True))
        )

    def _save_current(self):
        if self.drafts:
            self.drafts[self.current_index] = self._field_values()

    def _switch_draft(self, index):
        if index < 0 or index == self.current_index:
            return
        self._save_current()
        self.current_index = index
        self._load_draft(index)
        self._update_progress()

    def _update_progress(self):
        self.progress_label.setText(f"题目 {self.current_index + 1} / {len(self.drafts)}")

    def _remove_current_draft(self):
        if len(self.drafts) <= 1:
            return
        if QMessageBox.question(self, "移除识别结果", "确定移除当前这道题吗？") != QMessageBox.StandardButton.Yes:
            return
        del self.drafts[self.current_index]
        selected = min(self.current_index, len(self.drafts) - 1)
        self.question_selector.blockSignals(True)
        self.question_selector.clear()
        for index in range(len(self.drafts)):
            self.question_selector.addItem(f"第 {index + 1} 题", index)
        self.question_selector.setCurrentIndex(selected)
        self.question_selector.blockSignals(False)
        self.current_index = selected
        self._load_draft(selected)
        self._update_progress()
        self.question_selector.setVisible(len(self.drafts) > 1)
        self.remove_draft_button.setVisible(len(self.drafts) > 1)
        self.instruction_label.setText(
            f"剩余 {len(self.drafts)} 道题。可逐题核对，确认后统一收录并保存原图。"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            f"确认并收录 {len(self.drafts)} 道题"
        )

    def _accept_if_valid(self):
        self._save_current()
        missing = next(
            (index for index, draft in enumerate(self.drafts) if not draft["stem"].strip()),
            None,
        )
        if missing is not None:
            self.question_selector.setCurrentIndex(missing)
            QMessageBox.warning(self, "缺少题干", f"第 {missing + 1} 道题没有题干，请补充后再收录。")
            return
        self.accept()

    def values(self):
        self._save_current()
        return self.drafts

    def _field_values(self):
        return {
            "stem": self.stem.toPlainText(),
            "subject": self.subject.text(),
            "question_type": self.question_type.text(),
            "answer": self.answer.toPlainText(),
            "explanation": self.explanation.toPlainText(),
            "is_wrong": int(self.is_wrong.isChecked()),
        }
