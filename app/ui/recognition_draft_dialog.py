from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QVBoxLayout,
)


class RecognitionDraftDialog(QDialog):
    def __init__(self, question, image_path, draft, parent=None):
        super().__init__(parent)
        self.setWindowTitle("检查 AI 识题草稿")
        self.resize(980, 700)
        self.setStyleSheet("QDialog{background:#f4f6fa;} QLineEdit,QPlainTextEdit{background:white;border:1px solid #dfe5ee;border-radius:7px;padding:7px;}")
        self.image = QLabel("原图")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(350, 300)
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            self.image.setPixmap(pixmap.scaled(440, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.stem = QPlainTextEdit()
        self.stem.setPlainText(draft.get("stem", ""))
        self.stem.setMinimumHeight(110)
        self.subject = QLineEdit(draft.get("subject", ""))
        self.question_type = QLineEdit(draft.get("question_type", ""))
        self.answer = QPlainTextEdit()
        self.answer.setPlainText(draft.get("answer", ""))
        self.answer.setMinimumHeight(65)
        self.explanation = QPlainTextEdit()
        self.explanation.setPlainText(draft.get("explanation", ""))
        self.explanation.setMinimumHeight(100)
        self.is_wrong = QCheckBox("标记为错题")
        self.is_wrong.setChecked(bool(question["is_wrong"]) if question is not None else True)
        form = QFormLayout()
        for label, field in (("题干 *", self.stem), ("学科", self.subject), ("题型", self.question_type), ("答案", self.answer), ("解析", self.explanation)):
            form.addRow(label, field)
        form.addRow("", self.is_wrong)
        content = QHBoxLayout()
        content.addWidget(self.image, 1)
        content.addLayout(form, 2)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "确认并更新题目" if question is not None else "确认并收录题目"
        )
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        instruction = (
            "AI 生成的是草稿，请核对题干、答案和解析；确认后才会更新题目。"
            if question is not None
            else "AI 生成的是草稿，请核对题干、答案和解析；确认后才会新增题目并保存原图。"
        )
        layout.addWidget(QLabel(instruction))
        layout.addLayout(content, 1)
        layout.addWidget(self.buttons)
        self.question = question

    def _accept_if_valid(self):
        if not self.stem.toPlainText().strip():
            QMessageBox.warning(self, "缺少题干", "识别结果没有题干，请补充后再保存。")
            return
        self.accept()

    def values(self):
        return {
            "stem": self.stem.toPlainText(),
            "subject": self.subject.text(),
            "question_type": self.question_type.text(),
            "answer": self.answer.toPlainText(),
            "explanation": self.explanation.toPlainText(),
            "is_wrong": int(self.is_wrong.isChecked()),
        }
