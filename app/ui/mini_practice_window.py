from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizeGrip, QVBoxLayout, QWidget,
)

from app.ui.motion import AnimatedButton
from app.ui.theme import STYLE


PET_EXPRESSIONS = ("idle", "happy", "thinking", "sad", "sleepy", "surprised")


class MiniPracticeWindow(QWidget):
    restore_requested = Signal()

    def __init__(self, practice, parent):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("小窗练习 · AI 错题本")
        self.setObjectName("miniPracticeWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(STYLE + """
            QWidget#miniPracticeWindow { background: transparent; }
            QFrame#petPracticeCard {
                background: #fff8fb; border: 1px solid #ecd5df; border-radius: 18px;
            }
            QPushButton#practicePet, QPushButton#practicePet:hover,
            QPushButton#practicePet:pressed {
                background: transparent; border: none; padding: 0;
            }
        """)
        self._collapsed = False
        self._drag_origin = None
        self._dragged = False
        self._hovered = False
        self._sleeping = False
        self._practice = practice
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.setInterval(45000)
        self._sleep_timer.timeout.connect(self._fall_asleep)
        self.setMinimumSize(440, 420)
        self.resize(480, 640)
        self._minimum = practice.minimumSize()
        self._margins = practice.layout().contentsMargins()
        self._spacing = practice.layout().spacing()
        practice.setMinimumSize(0, 0)
        practice.layout().setContentsMargins(16, 14, 16, 16)
        practice.layout().setSpacing(10)

        self.pet_button = QPushButton()
        self.pet_button.setObjectName("practicePet")
        assets = Path(__file__).resolve().parents[2] / "assets"
        self._pet_icons = {
            name: QIcon(str(assets / ("flandre_pet_chibi.png" if name == "idle"
                                    else f"pet_expressions/{name}.png")))
            for name in PET_EXPRESSIONS
        }
        self._expression = None
        self.pet_button.setIconSize(QSize(144, 156))
        self.pet_button.setFixedSize(156, 168)
        self.pet_button.setAccessibleName("芙兰：收起或展开练习")
        self.pet_button.setToolTip("拖动芙兰移动小窗，点击收起或展开练习；右键返回完整界面")
        self.pet_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pet_button.clicked.connect(self.toggle_collapsed)
        self.pet_button.installEventFilter(self)
        title = QLabel("小窗练习")
        title.setObjectName("sectionTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.pin_button = AnimatedButton("已置顶")
        self.pin_button.setObjectName("softButton")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(True)
        self.pin_button.setToolTip("让练习小窗保持在其他窗口上方")
        self.pin_button.toggled.connect(self._set_pinned)
        self.collapse_button = AnimatedButton("收起")
        self.collapse_button.setToolTip("收起答题卡，只留下芙兰，当前作答会保留")
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        self.restore_button = AnimatedButton("返回")
        self.restore_button.setToolTip("返回完整界面，保留当前作答（Esc）")
        self.restore_button.clicked.connect(self.restore_requested.emit)
        escape = QShortcut(QKeySequence("Esc"), self)
        escape.activated.connect(self.restore_requested.emit)
        self.header = QWidget()
        self.header.setCursor(Qt.CursorShape.SizeAllCursor)
        self.header.setToolTip("拖动这里移动小窗")
        self.header.installEventFilter(self)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.pin_button)
        header.addWidget(self.collapse_button)
        header.addWidget(self.restore_button)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("miniPracticeScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(practice)
        hint = QLabel("拖动芙兰移动 · 点击收起 / 展开 · Esc 返回")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(hint, 1)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setToolTip("拖动调整答题卡大小")
        footer.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom)
        self.panel = QFrame()
        self.panel.setObjectName("petPracticeCard")
        card = QVBoxLayout(self.panel)
        card.setContentsMargins(12, 12, 12, 10)
        card.setSpacing(10)
        card.addWidget(self.header)
        card.addWidget(self.scroll, 1)
        card.addLayout(footer)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(0)
        layout.addWidget(self.pet_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.panel, 1)
        practice.content_changed.connect(self._refresh_expression)
        practice.user_answer.textChanged.connect(self._refresh_expression)
        practice.result_choice.currentIndexChanged.connect(self._refresh_expression)
        self._refresh_expression()

    def _refresh_expression(self):
        if self._practice is None:
            return
        if self._dragged and self._drag_origin is not None:
            expression = "surprised"
        elif self._hovered:
            expression = "happy"
        elif self._sleeping:
            expression = "sleepy"
        elif self._practice.index >= len(self._practice.questions):
            expression = "happy"
        elif self._practice._submitted:
            expression = {"correct": "happy", "incorrect": "sad", "skipped": "thinking"}.get(
                self._practice.result_choice.currentData(), "thinking"
            )
        elif self._practice.user_answer.toPlainText().strip():
            expression = "thinking"
        else:
            expression = "idle"
        if expression != self._expression:
            self._expression = expression
            icon = self._pet_icons[expression]
            self.pet_button.setIcon(icon if not icon.isNull() else self._pet_icons["idle"])
        self._sleep_timer.stop()
        if self._collapsed and not self._hovered and self._drag_origin is None and not self._sleeping:
            self._sleep_timer.start()

    def _fall_asleep(self):
        if self._collapsed and not self._hovered and self._drag_origin is None:
            self._sleeping = True
            self._refresh_expression()

    def toggle_collapsed(self):
        anchor = self.geometry().topRight()
        if not self._collapsed:
            self._expanded_size = self.size()
            self.panel.hide()
            self.setMinimumSize(172, 180)
            self.resize(172, 180)
        else:
            self.panel.show()
            self.setMinimumSize(440, 420)
            self.resize(self._expanded_size)
        self._collapsed = not self._collapsed
        self._sleeping = False
        self._refresh_expression()
        self.move(anchor.x() - self.width() + 1, anchor.y())
        self._keep_on_screen()

    def _keep_on_screen(self):
        screen = QGuiApplication.screenAt(self.pet_button.mapToGlobal(self.pet_button.rect().center())) or self.screen()
        available = screen.availableGeometry()
        self.move(
            max(available.left(), min(self.x(), available.right() - self.width() + 1)),
            max(available.top(), min(self.y(), available.bottom() - self.height() + 1)),
        )

    def eventFilter(self, watched, event):
        if watched in (self.pet_button, self.header):
            if event.type() == QEvent.Type.Enter and watched is self.pet_button:
                self._hovered = True
                self._sleeping = False
                self._refresh_expression()
            elif event.type() == QEvent.Type.Leave and watched is self.pet_button:
                self._hovered = False
                self._refresh_expression()
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = event.globalPosition().toPoint()
                self._window_origin = self.pos()
                self._dragged = False
                self._sleeping = False
                self._refresh_expression()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_origin is not None:
                delta = event.globalPosition().toPoint() - self._drag_origin
                if delta.manhattanLength() >= QApplication.startDragDistance():
                    self._dragged = True
                if self._dragged:
                    self._refresh_expression()
                    self.move(self._window_origin + delta)
                    self._keep_on_screen()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._drag_origin is not None:
                    clicked = not self._dragged
                    self._drag_origin = None
                    self._refresh_expression()
                    if clicked and watched is self.pet_button:
                        self.toggle_collapsed()
                    return True
            if event.type() == QEvent.Type.ContextMenu and watched is self.pet_button:
                self.restore_requested.emit()
                return True
        return super().eventFilter(watched, event)

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
        self._sleep_timer.stop()
        self._practice.content_changed.disconnect(self._refresh_expression)
        self._practice.user_answer.textChanged.disconnect(self._refresh_expression)
        self._practice.result_choice.currentIndexChanged.disconnect(self._refresh_expression)
        self._practice = None
        practice = self.scroll.takeWidget()
        practice.setMinimumSize(self._minimum)
        practice.layout().setContentsMargins(self._margins)
        practice.layout().setSpacing(self._spacing)
        return practice

    def closeEvent(self, event):
        event.ignore()
        self.restore_requested.emit()
