"""Run with .venv/Scripts/python.exe checks/check_mini_practice.py [preview.png]."""

import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QFont, QFontDatabase, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

from app.database import store
from app.ui.main_window import MainWindow
from app.ui.mini_practice_window import PET_EXPRESSIONS


def expression_preview(mini, path):
    preview = QWidget()
    preview.setObjectName("expressionPreview")
    preview.setStyleSheet("""
        QWidget#expressionPreview { background: #fff8fb; }
        QFrame#expressionCard { background: white; border: 1px solid #ecd5df; border-radius: 14px; }
        QLabel { color: #503845; border: none; background: transparent; }
    """)
    layout = QVBoxLayout(preview)
    layout.setContentsMargins(22, 18, 22, 20)
    heading = QLabel("芙兰 · 桌宠表情")
    heading.setStyleSheet("font-size: 21px; font-weight: 700;")
    layout.addWidget(heading)
    grid = QGridLayout()
    grid.setSpacing(12)
    descriptions = (
        ("待机", "等待开始练习"), ("开心", "悬停 / 答对"), ("思考", "正在输入答案"),
        ("委屈", "这题答错了"), ("困倦", "收起后闲置 45 秒"), ("惊讶", "被拖动时"),
    )
    for index, (name, (title, caption)) in enumerate(zip(PET_EXPRESSIONS, descriptions)):
        card = QFrame()
        card.setObjectName("expressionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 12)
        face = QLabel()
        face.setPixmap(mini._pet_icons[name].pixmap(mini.pet_button.iconSize()))
        face.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 15px; font-weight: 700;")
        hint = QLabel(caption)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("font-size: 11px; color: #806772;")
        for widget in (face, label, hint):
            card_layout.addWidget(widget)
        grid.addWidget(card, index // 3, index % 3)
    layout.addLayout(grid)
    preview.resize(570, 530)
    preview.show()
    QApplication.processEvents()
    assert preview.grab().save(str(path))
    preview.close()


def check(preview_path=None):
    app = QApplication.instance() or QApplication([])
    sprite = QImage(str(Path(__file__).resolve().parents[1] / "assets" / "flandre_pet_chibi.png"))
    assert not sprite.isNull() and sprite.hasAlphaChannel()
    assert sprite.pixelColor(0, 0).alpha() == 0
    assert sprite.pixelColor(sprite.width() // 2, sprite.height() // 2).alpha() > 0
    for name in PET_EXPRESSIONS[1:]:
        variant = QImage(str(Path(__file__).resolve().parents[1] / "assets" / "pet_expressions" / f"{name}.png"))
        assert not variant.isNull() and variant.hasAlphaChannel(), name
        assert abs(variant.width() - sprite.width()) <= 2 and abs(variant.height() - sprite.height()) <= 2, name
        assert variant.pixelColor(0, 0).alpha() == 0, name
    if sys.platform == "win32":
        for font in ("msyh.ttc", "msyhbd.ttc"):
            QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda: connection(database)), patch(
            "app.ui.main_window.GlobalScreenshotHotkey"
        ):
            for stem, answer in (("求方程 2x = 6 的解。", "3"), ("已知 x + 3 = 8，求 x。", "5")):
                store.save_question(dict(stem=stem, subject="数学", question_type="填空题",
                                         answer=answer, explanation="等式两边同时减去 3，得到 x = 5。"))
            window = MainWindow()
            window.show()
            app.processEvents()
            geometry = window.geometry()
            window.enter_mini_practice()
            assert window._mini_practice_window is None
            window.start_practice()
            window._practice_setup.mini_mode.setChecked(True)
            window._practice_setup.accept()
            run = window._page_dialogs["practice_run"]
            mini = window._mini_practice_window
            QTest.qWait(220)
            assert mini.isVisible() and not window.isVisible()
            assert mini.scroll.widget() is run
            assert mini.width() == 480 and mini.height() <= 640
            assert mini.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
            assert mini.windowFlags() & Qt.WindowType.FramelessWindowHint
            assert mini.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            assert mini.grab().toImage().pixelColor(0, 0).alpha() == 0
            QCoreApplication.sendEvent(mini.pet_button, QEvent(QEvent.Type.Leave))
            assert mini._expression == "idle"
            assert all(not icon.pixmap(mini.pet_button.iconSize()).isNull() for icon in mini._pet_icons.values())
            if preview_path:
                expression_preview(mini, preview_path.with_name("pet-expression-preview.png"))
            run.user_answer.setPlainText("5")
            QCoreApplication.sendEvent(mini.pet_button, QEvent(QEvent.Type.Leave))
            assert mini._expression == "thinking"
            QCoreApplication.sendEvent(mini.pet_button, QEnterEvent(QPointF(), QPointF(), QPointF()))
            assert mini._expression == "happy"
            QCoreApplication.sendEvent(mini.pet_button, QEvent(QEvent.Type.Leave))
            assert mini._expression == "thinking"
            expanded_size = mini.size()
            QTest.mouseClick(mini.pet_button, Qt.MouseButton.LeftButton)
            app.processEvents()
            assert mini.size().width() == 172 and mini.size().height() == 180
            assert not mini.panel.isVisible() and mini.pet_button.isVisible()
            assert mini.grab().toImage().pixelColor(0, 0).alpha() == 0
            assert not store.list_attempts() and run.user_answer.toPlainText() == "5"
            QCoreApplication.sendEvent(mini.pet_button, QEvent(QEvent.Type.Leave))
            mini._sleep_timer.setInterval(20)
            mini._refresh_expression()
            QTest.qWait(50)
            assert mini._expression == "sleepy" and not mini._sleep_timer.isActive()
            QCoreApplication.sendEvent(mini.pet_button, QEnterEvent(QPointF(), QPointF(), QPointF()))
            assert mini._expression == "happy" and not mini._sleeping
            mini._sleep_timer.setInterval(45000)
            QCoreApplication.sendEvent(mini.pet_button, QEvent(QEvent.Type.Leave))
            assert mini._expression == "thinking" and mini._sleep_timer.isActive()
            mini.pin_button.click()
            mini.pin_button.click()
            assert mini.size().width() == 172 and not mini.panel.isVisible()
            origin = mini.pos()
            local = mini.pet_button.rect().center()
            global_pos = mini.pet_button.mapToGlobal(local)
            for kind, offset, button, buttons in (
                (QEvent.Type.MouseButtonPress, QPoint(), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
                (QEvent.Type.MouseMove, QPoint(-80, 60), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
                (QEvent.Type.MouseButtonRelease, QPoint(-80, 60), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
            ):
                QCoreApplication.sendEvent(mini.pet_button, QMouseEvent(
                    kind, QPointF(local + offset), QPointF(global_pos + offset), button, buttons,
                    Qt.KeyboardModifier.NoModifier,
                ))
                if kind == QEvent.Type.MouseMove:
                    assert mini._expression == "surprised"
            assert mini.pos() == origin + QPoint(-80, 60) and not mini.panel.isVisible()
            if preview_path:
                assert mini.grab().save(str(preview_path.with_name(preview_path.stem + "-pet.png")))
            QTest.mouseClick(mini.pet_button, Qt.MouseButton.LeftButton)
            app.processEvents()
            assert mini.panel.isVisible() and mini.size() == expanded_size
            assert run.user_answer.toPlainText() == "5" and run.index == 0
            mini.pin_button.click()
            assert not mini.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
            mini.pin_button.click()
            assert mini.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
            assert run.user_answer.toPlainText() == "5"
            mini.close()
            app.processEvents()
            assert window.isVisible() and window._mini_practice_window is None
            assert window.geometry() == geometry
            assert window._page_dialogs["practice_run"] is run
            assert run.minimumWidth() == 600 and run.minimumHeight() == 480
            assert run.user_answer.toPlainText() == "5" and run.index == 0
            assert not store.list_attempts()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert isValid(run)

            run.submit_answer()
            window.mini_practice_button.click()
            mini = window._mini_practice_window
            QTest.qWait(220)
            QCoreApplication.sendEvent(mini.pet_button, QEvent(QEvent.Type.Leave))
            assert mini._expression == "happy"
            assert run.solution.isVisible() and run.result_choice.currentData() == "correct"
            mini.resize(440, 420)
            app.processEvents()
            assert mini.scroll.verticalScrollBar().maximum() > 0
            assert mini.scroll.horizontalScrollBar().maximum() == 0
            stem, solution = run.stem.text(), run.solution.text()
            run.stem.setText("阅读题目并写出你的计算过程。\n" * 40)
            run.solution.setText("解析：逐步整理等式并核对结果。\n" * 40)
            QTest.qWait(40)
            assert mini.scroll.verticalScrollBar().maximum() > 1000
            mini.scroll.ensureWidgetVisible(run.record_button)
            app.processEvents()
            assert mini.scroll.viewport().rect().contains(
                run.record_button.mapTo(mini.scroll.viewport(), run.record_button.rect().center())
            )
            run.stem.setText(stem)
            run.solution.setText(solution)
            mini.resize(480, 640)
            QTest.qWait(220)
            mini.scroll.verticalScrollBar().setValue(0)
            if preview_path:
                assert mini.grab().save(str(preview_path))
            run.record_and_continue()
            assert run.index == 1 and len(store.list_attempts()) == 1
            QCoreApplication.sendEvent(mini.pet_button, QEvent(QEvent.Type.Leave))
            assert mini._expression == "idle"
            run.user_answer.setPlainText("999")
            run.submit_answer()
            assert mini._expression == "sad" and len(store.list_attempts()) == 1
            run.result_choice.setCurrentIndex(run.result_choice.findData("skipped"))
            assert mini._expression == "thinking"
            run.show_question()
            assert mini._expression == "idle"
            mini.restore_button.click()
            assert not mini._sleep_timer.isActive()
            assert window._mini_practice_window is None and window.isVisible()
            assert run.index == 1
            window.enter_mini_practice()
            mini = window._mini_practice_window
            mini.activateWindow()
            run.user_answer.setFocus()
            QTest.qWait(40)
            QTest.keyClick(run.user_answer, Qt.Key.Key_Escape)
            assert window.isVisible() and window._mini_practice_window is None
            assert "practice_run" in window._pages and run.index == 1
            window.enter_mini_practice()
            mini = window._mini_practice_window
            mini.collapse_button.click()
            QCoreApplication.sendEvent(mini.pet_button, QEvent(QEvent.Type.ContextMenu))
            assert window.isVisible() and window._mini_practice_window is None
            QCoreApplication.sendEvent(mini.pet_button, QEvent(QEvent.Type.Leave))
            assert not mini._sleep_timer.isActive()
            assert run.index == 1
            window.enter_mini_practice()
            mini = window._mini_practice_window
            mini.collapse_button.click()
            mini.activateWindow()
            mini.pet_button.setFocus()
            QTest.qWait(40)
            QTest.keyClick(mini.pet_button, Qt.Key.Key_Escape)
            assert window.isVisible() and window._mini_practice_window is None
            window.enter_mini_practice()
            run.images_requested.emit(run.questions[run.index]["id"])
            assert window.isVisible() and window._mini_practice_window is None
            assert window.page_stack.currentWidget() == window._pages["attachments"]
            window._page_dialogs["attachments"].accept()
            assert window.page_stack.currentWidget() == window._pages["practice_run"]
            window.enter_mini_practice()
            window.start_image_recognition()
            assert window.isVisible() and window._mini_practice_window is None
            assert run.index == 1
            window.start_practice()
            window.enter_mini_practice()
            run.user_answer.setPlainText("3")
            run.submit_answer()
            run.record_and_continue()
            assert run.recorded_count == 2 and len(store.list_attempts()) == 2
            run.record_button.click()
            assert window.isVisible() and window._mini_practice_window is None
            assert "practice_run" not in window._pages
            window.start_practice()
            window._practice_setup.accept()
            assert window._mini_practice_window is not None
            window.close()
            app.processEvents()
            assert not window.isVisible() and window._mini_practice_window is None
    print("Mini practice check passed (six expressions, hover/drag/sleep/wake and grading reactions, collapse/expand, state, pin, restore, scrolling, completion and shutdown; temporary database only).")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
