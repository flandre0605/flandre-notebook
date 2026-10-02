"""Home navigation and real learning counts; temporary data, no screenshot/API."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.database import store, vocabulary
from app.ui.main_window import MainWindow


def check(preview=None):
    app = QApplication.instance() or QApplication([])
    for name in ("msyh.ttc", "msyhbd.ttc"):
        QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{name}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        db = Path(directory) / "questions.db"
        store.initialize(db)
        with patch.object(store, "_connection", lambda: connection(db)), patch(
            "app.ui.main_window.GlobalScreenshotHotkey"
        ), patch.object(MainWindow, "capture_screenshot") as capture:
            window = MainWindow()
            window.show()
            QTest.qWait(220)
            assert window.page_stack.currentWidget() is window._pages["home"]
            assert "还没有学习内容" in window.home_reminder.text()
            for size in ((1040, 680), (1280, 820)):
                window.resize(*size)
                QTest.qWait(220)
                assert window._pages["home"].horizontalScrollBar().maximum() == 0
            window.home_actions["capture"].click()
            capture.assert_called_once()
            assert window.page_stack.currentWidget() is window._pages["home"]
            window.home_actions["practice"].click()
            assert window.page_stack.currentWidget() is window._pages["practice_setup"]
            window.show_home()
            window.home_actions["library"].click()
            assert window.page_stack.currentWidget() is window._pages["library"]
            store.save_question(dict(stem="求 1+1。", subject="数学", answer="2", is_wrong=True))
            window.show_home()
            assert window.home_stats["total"].text() == "1" and window.home_stats["wrong"].text() == "1"
            window.home_actions["vocabulary"].click()
            assert window.page_stack.currentWidget() is window._pages["vocabulary"]
            vocabulary.save_word(dict(word="review", meaning="复习"))
            window.show_home()
            assert window.home_stats["words"].text() == "1" and "1 个新词" in window.home_reminder.text()
            assert any(button.objectName() == "navButtonActive" and key == "home"
                       for button, key in window._navigation_buttons)
            if preview:
                QTest.qWait(230)
                assert window.grab().save(str(preview))
            window.close()
    print("PASS: default functional home, empty/updated counts, all feature routes, sidebar and small layout")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
