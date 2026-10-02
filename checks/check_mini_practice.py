"""Run with .venv/Scripts/python.exe checks/check_mini_practice.py [preview.png]."""

import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from app.database import store
from app.ui.main_window import MainWindow


def check(preview_path=None):
    app = QApplication.instance() or QApplication([])
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
            run.user_answer.setPlainText("5")
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
            mini.restore_button.click()
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
    print("Mini practice check passed (state, pin, restore, scrolling, completion and shutdown; temporary database only).")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
