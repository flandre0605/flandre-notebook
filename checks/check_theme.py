"""Run with .venv/Scripts/python.exe checks/check_theme.py [preview-directory]."""

import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont, QFontDatabase, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.database import store
from app.ui.main_window import MainWindow
from app.ui.recognition_draft_dialog import RecognitionDraftDialog
from app.ui.theme import ICON_DIR


def check(preview_directory=None):
    app = QApplication.instance() or QApplication([])
    if sys.platform == "win32":
        for font in ("msyh.ttc", "msyhbd.ttc"):
            QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    for name in ("chevron-down", "chevron-up", "check", "image"):
        assert not QPixmap(f"{ICON_DIR}/{name}.svg").isNull()
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda: connection(database)), patch(
            "app.ui.main_window.GlobalScreenshotHotkey"
        ):
            store.save_question(dict(stem="已知 x + 3 = 8，求 x。", subject="数学", answer="5"))
            window = MainWindow()
            window.show()

            def capture(name):
                QTest.qWait(220)
                if preview_directory:
                    assert window.grab().save(str(preview_directory / f"pink-{name}.png"))

            window.manage_profiles()
            settings = window._profiles_dialog
            assert settings.empty_hint.isVisible()
            assert any(button.objectName() == "navButtonActive" and key == "settings"
                       for button, key in window._navigation_buttons)
            settings.name.setText("我的模型服务")
            settings.timeout.setValue(60)
            settings.vision.setChecked(True)
            for width, height in ((1040, 680), (1280, 820)):
                window.resize(width, height)
                app.processEvents()
                assert window.width() == width and window.height() == height
                for field in (settings.name, settings.timeout, settings.screenshot_shortcut,
                              settings.save_button, settings.delete_button):
                    assert settings.rect().contains(field.geometry())
                capture(f"settings-{width}")
            recognition = window.start_image_recognition()
            zone = recognition.drop_zone
            zone._set_dragging(True)
            assert zone.property("dragging") is True
            zone._set_dragging(False)
            assert zone.property("dragging") is False
            assert not recognition.recognize_button.isEnabled()
            capture("recognition")
            window.start_practice()
            capture("practice")
            window._practice_setup.accept()
            run = window._page_dialogs["practice_run"]
            run.user_answer.setPlainText("5")
            run.submit_answer()
            capture("practice-answer")
            draft = RecognitionDraftDialog(None, Path(ICON_DIR).parent / "flandre_icon.png", [
                dict(stem="已知 x + 3 = 8，求 x。", subject="数学", question_type="填空题",
                     answer="5", explanation="等式两边同时减去 3，得 x = 5。"),
                dict(stem="已知 2x = 6，求 x。", subject="数学", answer="3"),
            ], window)
            window._embed_dialog_page("draft-preview", draft, "核对识题草稿", nav_key="recognition")
            window._show_page("draft-preview")
            window.resize(1040, 680)
            app.processEvents()
            assert window.width() == 1040 and window.height() == 680
            capture("draft")
            assert draft.image.pixmap().width() <= draft.image.width()
            assert draft.image.pixmap().height() <= draft.image.height()
            assert len(draft.values()) == 2
            window.close()
    print("Theme check passed (SVG assets, settings layout and drag feedback; temporary database only).")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
