from pathlib import Path
import math
import random

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut, QTransform
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizeGrip, QVBoxLayout, QWidget,
)

from app.ui.motion import AnimatedButton
from app.ui.pet_walk import WALK_FRAME_MS, WALK_FRAMES, WALK_STRIDE, walking_frames
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
        self._collapsed_anchor = None
        self._expanded_origin = None
        self._selected = False
        self._has_landed = False
        self._motion_mode = None
        self._movement = QPropertyAnimation(self, b"pos", self)
        self._movement.finished.connect(self._motion_finished)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._wander)
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
        self._motion_icons = {}
        walk = walking_frames(assets / "pet_walk_user.png")
        if walk:
            self._motion_icons["walk", False] = [QIcon(frame) for frame in walk]
            self._motion_icons["walk", True] = [QIcon(frame.transformed(QTransform().scale(-1, 1))) for frame in walk]
        for mode, filename, columns, rows, first, count in (
            ("fly", "pet_motion.png", 4, 2, 4, 4),
        ):
            sheet = QPixmap(str(assets / filename))
            if sheet.isNull():
                continue
            width, height = sheet.width() // columns, sheet.height() // rows
            frames = [sheet.copy(index % columns * width, index // columns * height, width, height)
                      for index in range(first, first + count)]
            self._motion_icons[mode, False] = [QIcon(frame) for frame in frames]
            self._motion_icons[mode, True] = [QIcon(frame.transformed(QTransform().scale(-1, 1))) for frame in frames]
        self._facing_left = False
        self._movement.valueChanged.connect(lambda _: self._render_pet())
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
        self._render_pet()
        self._sleep_timer.stop()
        if self._collapsed and not self._hovered and self._drag_origin is None and not self._sleeping:
            self._sleep_timer.start()

    def _render_pet(self):
        if not hasattr(self, "_motion_icons"):
            return
        mode = "fly" if self._motion_mode == "fall" else self._motion_mode
        frames = self._motion_icons.get((mode, self._facing_left))
        if frames:
            interval = WALK_FRAME_MS if mode == "walk" else 120
            self.pet_button.setIcon(frames[(self._movement.currentTime() // interval) % len(frames)])
        else:
            icon = self._pet_icons[self._expression or "idle"]
            self.pet_button.setIcon(icon if not icon.isNull() else self._pet_icons["idle"])

    def _fall_asleep(self):
        if self._collapsed and not self._hovered and self._drag_origin is None:
            self._stop_motion()
            self._sleeping = True
            self._refresh_expression()
            self._resume_motion()

    def collapsed_position(self):
        if self._collapsed:
            return self.pos()
        if self._collapsed_anchor is not None:
            return (self._collapsed_anchor + self.pos() - self._expanded_origin
                    + QPoint(self.width() - self._expanded_size.width(), 0))
        return self.pos() + QPoint(self.width() - 172, 0)

    def place_pet(self, position):
        self._collapsed_anchor = QPoint(position)
        self._expanded_size = self.size()
        area = (QGuiApplication.screenAt(position + QPoint(86, 90)) or self.screen()).availableGeometry()
        self.move(self._bounded_position(position + QPoint(172 - self.width(), 0), area))
        self._expanded_origin = self.pos()
        self._has_landed = True

    def toggle_collapsed(self):
        self._stop_motion()
        if not self._collapsed:
            position = self.collapsed_position()
            self._expanded_size = self.size()
            self.panel.hide()
            self.setMinimumSize(172, 180)
            self.resize(172, 180)
            self.move(position)
        else:
            self._collapsed_anchor = self.pos()
            self.panel.show()
            self.setMinimumSize(440, 420)
            self.resize(self._expanded_size)
            self.move(self._collapsed_anchor + QPoint(172 - self.width(), 0))
            self._has_landed = True
        self._collapsed = not self._collapsed
        self._sleeping = False
        self._refresh_expression()
        self._keep_on_screen()
        if not self._collapsed:
            self._expanded_origin = self.pos()
        self._resume_motion()

    def _available_geometry(self):
        screen = QGuiApplication.screenAt(self.pet_button.mapToGlobal(self.pet_button.rect().center())) or self.screen()
        return screen.availableGeometry()

    def _bounded_position(self, position, available=None):
        available = available if available is not None else self._available_geometry()
        return QPoint(
            max(available.left(), min(position.x(), available.right() - self.width() + 1)),
            max(available.top(), min(position.y(), available.bottom() - self.height() + 1)),
        )

    def _keep_on_screen(self):
        self.move(self._bounded_position(self.pos()))

    def _stop_motion(self):
        self._movement.stop()
        self._idle_timer.stop()
        self._motion_mode = None
        self._render_pet()

    def _can_move(self):
        return (self._practice is not None and self.isVisible() and self._collapsed
                and not self._selected and not self._hovered and self._drag_origin is None)

    def _resume_motion(self):
        if not self._can_move() or self._motion_mode is not None:
            return
        if self._sleeping:
            self._idle_timer.start(15000)
        else:
            ground = self._bounded_position(QPoint(self.x(), self._available_geometry().bottom() - self.height() - 11))
            if not self._has_landed or self.y() != ground.y():
                self._animate("fall", [(0, self.pos()), (1, ground)], 1000, QEasingCurve.Type.OutBounce)
            else:
                self._idle_timer.start(random.randint(6000, 10000))

    def _animate(self, mode, points, duration, easing=QEasingCurve.Type.Linear):
        self._movement.stop()
        self._idle_timer.stop()
        self._motion_mode = mode
        self._facing_left = points[-1][1].x() < points[0][1].x()
        self._movement.setKeyValues(points)
        self._movement.setDuration(duration)
        self._movement.setEasingCurve(easing)
        self._movement.start()
        self._render_pet()

    def _motion_finished(self):
        self._has_landed = True
        self._motion_mode = None
        self._render_pet()
        self._keep_on_screen()
        self._resume_motion()

    def _wander(self):
        if not self._can_move() or self._motion_mode is not None:
            return
        if self._sleeping:
            self._sleeping = False
            self._refresh_expression()
        area = self._available_geometry()
        start = self.pos()
        ground = self._bounded_position(QPoint(start.x(), area.bottom() - self.height() - 11), area)
        if start.y() != ground.y():
            self._resume_motion()
            return
        flying = random.choice((False, True))
        distance = random.choice((-1, 1)) * random.randint(100, 240)
        target = self._bounded_position(start + QPoint(distance, 0), area)
        if target.x() == start.x():
            target = self._bounded_position(start - QPoint(distance, 0), area)
        if target.x() == start.x() and not flying:
            self._resume_motion()
            return
        if flying:
            target.setY(self._bounded_position(QPoint(target.x(), area.bottom() - self.height() - 11), area).y())
        points = [(0, start), (1, target)]
        if flying:
            height = random.randint(100, 240)
            points = []
            for frame in range(21):
                progress = frame / 20
                x = start.x() + (target.x() - start.x()) * progress
                y = start.y() + (target.y() - start.y()) * progress - math.sin(math.pi * progress) * height
                points.append((progress, self._bounded_position(QPoint(round(x), round(y)), area)))
        # Keep the illustrated step cycle and window movement on the same clock.
        cycle = WALK_FRAME_MS * WALK_FRAMES
        duration = 2600 if flying else max(1, round(abs(target.x() - start.x()) / WALK_STRIDE * cycle))
        self._animate("fly" if flying else "walk", points, duration)

    def event(self, event):
        result = super().event(event)
        if hasattr(self, "_movement"):
            if event.type() == QEvent.Type.WindowActivate:
                self._selected = True
                self._stop_motion()
            elif event.type() == QEvent.Type.WindowDeactivate:
                self._selected = False
                self._resume_motion()
        return result

    def hideEvent(self, event):
        self._stop_motion()
        self._sleep_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_expression()
        self._resume_motion()

    def eventFilter(self, watched, event):
        if watched in (self.pet_button, self.header):
            if event.type() == QEvent.Type.Enter and watched is self.pet_button:
                self._stop_motion()
                self._hovered = True
                self._sleeping = False
                self._refresh_expression()
            elif event.type() == QEvent.Type.Leave and watched is self.pet_button:
                self._hovered = False
                self._refresh_expression()
                self._resume_motion()
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._stop_motion()
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
                    if self._dragged:
                        self._has_landed = True
                    self._refresh_expression()
                    if clicked and watched is self.pet_button:
                        self.toggle_collapsed()
                    self._resume_motion()
                    return True
            if event.type() == QEvent.Type.ContextMenu and watched is self.pet_button:
                self.restore_requested.emit()
                return True
        return super().eventFilter(watched, event)

    def _set_pinned(self, pinned):
        self._stop_motion()
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        self.pin_button.setText("已置顶" if pinned else "置顶")
        self.pin_button.setObjectName("softButton" if pinned else "")
        self.pin_button.style().unpolish(self.pin_button)
        self.pin_button.style().polish(self.pin_button)
        self.show()
        self.setGeometry(geometry)

    def take_practice(self):
        self._stop_motion()
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
