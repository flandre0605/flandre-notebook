from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.ui.motion import AnimatedButton
from app.ui.theme import STYLE


class MiniPracticeWindow(QWidget):
    restore_requested = Signal()

    def __init__(self, practice, parent):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("小窗练习 · AI 错题本")
        self.setObjectName("miniPracticeWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(440, 420)
        self.resize(480, 640)
        self._minimum = practice.minimumSize()
        self._margins = practice.layout().contentsMargins()
        self._spacing = practice.layout().spacing()
        practice.setMinimumSize(0, 0)
        practice.layout().setContentsMargins(16, 14, 16, 16)
        practice.layout().setSpacing(10)

        icon = QLabel()
        icon.setPixmap(QPixmap(str(Path(__file__).resolve().parents[2] / "assets" / "flandre_icon.png")).scaled(
            30, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        title = QLabel("小窗练习")
        title.setObjectName("sectionTitle")
        self.pin_button = AnimatedButton("已置顶")
        self.pin_button.setObjectName("softButton")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(True)
        self.pin_button.setToolTip("让练习小窗保持在其他窗口上方")
        self.pin_button.toggled.connect(self._set_pinned)
        self.restore_button = AnimatedButton("展开")
        self.restore_button.setToolTip("返回完整界面，保留当前作答（Esc）")
        self.restore_button.clicked.connect(self.restore_requested.emit)
        escape = QShortcut(QKeySequence("Esc"), self)
        escape.activated.connect(self.restore_requested.emit)
        header = QHBoxLayout()
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.pin_button)
        header.addWidget(self.restore_button)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("miniPracticeScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(practice)
        hint = QLabel("关闭小窗或按 Esc 返回完整界面，当前作答会保留。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(hint)

    def _set_pinned(self, pinned):
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        self.pin_button.setText("已置顶" if pinned else "置顶")
        self.pin_button.setObjectName("softButton" if pinned else "")
        self.pin_button.style().unpolish(self.pin_button)
        self.pin_button.style().polish(self.pin_button)
        self.show()
        self.setGeometry(geometry)

    def take_practice(self):
        practice = self.scroll.takeWidget()
        practice.setMinimumSize(self._minimum)
        practice.layout().setContentsMargins(self._margins)
        practice.layout().setSpacing(self._spacing)
        return practice

    def closeEvent(self, event):
        event.ignore()
        self.restore_requested.emit()
