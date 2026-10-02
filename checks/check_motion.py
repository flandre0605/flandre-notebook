"""Run with .venv/Scripts/python.exe checks/check_motion.py."""

import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPointF
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from app.ui.motion import AnimatedButton, ContentFade


def check():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    layout = QVBoxLayout(root)
    child = QLabel("Content")
    button = AnimatedButton("Action")
    layout.addWidget(child)
    layout.addWidget(button)
    root.show()
    app.processEvents()
    fade = ContentFade(root)
    for _ in range(5):
        fade.play(root)
        assert root.graphicsEffect() is not None
        fade.play(child)
        assert root.graphicsEffect() is None
        assert child.graphicsEffect() is not None
        assert not root.grab().isNull()
    QTest.qWait(260)
    assert fade.animation.state() == QAbstractAnimation.State.Stopped
    assert root.graphicsEffect() is None and child.graphicsEffect() is None
    fade.play(child)
    child.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    fade.finish()
    assert fade._target is None
    app.processEvents()
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    geometry = button.geometry()
    point = QPointF(button.rect().center())
    app.sendEvent(button, QEnterEvent(point, point, point))
    button._hover_animation.setCurrentTime(70)
    assert 0 < button._hover < 1
    button.click()
    assert clicked == [True]
    app.sendEvent(button, QEvent(QEvent.Type.Leave))
    QTest.qWait(220)
    assert button._hover == 0
    assert button.geometry() == geometry
    app.sendEvent(button, QEnterEvent(point, point, point))
    button.setEnabled(False)
    button.click()
    assert clicked == [True] and button._hover == 0
    app.sendEvent(button, QEvent(QEvent.Type.Leave))
    assert button._hover_animation.state() == QAbstractAnimation.State.Stopped
    root.close()
    print("Motion check passed (interruptions, cleanup, hover and click behavior).")


if __name__ == "__main__":
    check()
