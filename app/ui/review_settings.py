import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from app.database import store
from app.ui.motion import AnimatedButton


class ReviewSettings(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("题目复习间隔")
        title.setObjectName("detailTitle")
        note = QLabel("按本次掌握程度安排下一次复习，0 天表示立即到期。修改只影响之后记录的作答，已有到期时间保留；单词复习继续使用自己的规则。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(note)
        self.inputs = {}
        form = QFormLayout()
        for key, label in (("mastered", "已掌握"), ("unsure", "还不熟"), ("unknown", "不会")):
            spin = QSpinBox()
            spin.setRange(0, 365)
            spin.setSuffix(" 天")
            self.inputs[key] = spin
            form.addRow(label, spin)
        layout.addLayout(form)
        button = AnimatedButton("保存复习设置")
        button.setObjectName("primaryButton")
        button.clicked.connect(self.save)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.reload()

    def reload(self):
        try:
            intervals = store.review_intervals()
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(f"读取失败：{error}")
            return
        for key, spin in self.inputs.items():
            spin.setValue(intervals[key])
        self.status.clear()

    def save(self):
        try:
            store.save_review_intervals({key: spin.value() for key, spin in self.inputs.items()})
        except (sqlite3.Error, ValueError) as error:
            self.status.setText(f"保存失败：{error}")
            return
        self.status.setText("复习设置已保存，将用于之后记录的作答。")
