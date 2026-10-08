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
from PySide6.QtWidgets import QApplication, QPushButton
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
            assert all(label.text() == '0' for label in window.home_stats.values())
            assert store.list_questions() == [] and vocabulary.list_words() == []
            if preview:
                assert window.grab().save(str(preview.with_name('desktop-home-empty.png')))
            window.show_library()
            QTest.qWait(220)
            assert window.table.rowCount() == 0 and window.empty_title.isVisible()
            if preview:
                assert window.grab().save(str(preview.with_name('desktop-library-empty.png')))
            window.show_vocabulary()
            assert not any('示例' in button.text() for button in window.findChildren(QPushButton))
            from app.ui.cloud_account_dialog import CloudSignInDialog, CloudAccountDialog
            for dialog in (CloudSignInDialog(window), CloudAccountDialog(window)):
                assert not any('部署' in button.text() for button in dialog.findChildren(QPushButton))
                dialog.deleteLater()
            window.show_home()
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
            for name in ('question_template.csv', 'vocabulary_template.csv'):
                assert len((Path(__file__).resolve().parents[1] / 'assets' / name).read_text(encoding='utf-8').splitlines()) == 1
            assert not (Path(__file__).resolve().parents[1] / 'assets/vocabulary_template.txt').read_bytes()
            window.close()
    print("PASS: default functional home, empty/updated counts, all feature routes, sidebar and small layout")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
