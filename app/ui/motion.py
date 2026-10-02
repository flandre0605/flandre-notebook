from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QPushButton
from shiboken6 import isValid
from app.ui.theme import ACCENT


class ContentFade(QObject):
    """One temporary effect per window, so page and child fades never overlap."""

    def __init__(self, parent):
        super().__init__(parent)
        self._target = None
        self.animation = QPropertyAnimation(self)
        self.animation.setPropertyName(b"opacity")
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.finish)

    def play(self, widget):
        self.finish()
        if not widget.isVisible():
            return
        self._target = widget
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        self.animation.setTargetObject(effect)
        self.animation.setStartValue(0.65)
        self.animation.setEndValue(1.0)
        self.animation.start()

    def finish(self):
        self.animation.stop()
        self.animation.setTargetObject(None)
        widget, self._target = self._target, None
        if widget is not None and isValid(widget):
            widget.setGraphicsEffect(None)


class AnimatedButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._hover = 0.0
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(140)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_hover(self, value):
        self._hover = float(value)
        self.update()

    def _animate_hover(self, value):
        self._hover_animation.stop()
        if self._hover == value:
            return
        self._hover_animation.setStartValue(self._hover)
        self._hover_animation.setEndValue(value)
        self._hover_animation.start()

    def enterEvent(self, event):
        if self.isEnabled():
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled() else Qt.CursorShape.ArrowCursor)
            if not self.isEnabled():
                self._hover_animation.stop()
                self._set_hover(0.0)
        super().changeEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._hover <= 0 or not self.isEnabled():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#ffffff" if self.objectName() == "primaryButton" else ACCENT)
        color.setAlpha(round(22 * self._hover))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 7, 7)
        painter.end()
