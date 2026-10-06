"""Run with .venv/Scripts/python.exe checks/check_recognition_popup.py; no real API calls."""
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFont, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.database import store
from app.services import attachments, recognition_drafts
from app.services.model_provider import ProviderError
from app.ui.main_window import MainWindow


def wait_until(condition):
    for _ in range(300):
        QTest.qWait(10)
        if condition():
            return
    raise AssertionError("Background request did not finish")


def check():
    app = QApplication.instance() or QApplication([])
    for font in ("msyh.ttc", "msyhbd.ttc"):
        QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda path=None: connection(path or database)), patch.object(
            store, "DATA_DIR", root
        ), patch.object(attachments, "ATTACHMENTS_DIR", root / "attachments"), patch(
            "app.ui.main_window.GlobalScreenshotHotkey"
        ):
            store.save_profile(dict(name="检查模型", base_url="https://example.com/v1", model_id="mock",
                                    endpoint_path="/chat/completions", timeout_seconds=5,
                                    enabled=True, vision_enabled=True), "mock")
            image = QImage(200, 100, QImage.Format.Format_RGB32)
            image.fill("white")
            external = root / "external.png"
            assert image.save(str(external), "PNG")
            window = MainWindow()
            window.show()
            assert all(key != "recognition" for _button, key in window._navigation_buttons)
            assert window.recognize_button.text() == "截图识题"
            window.manage_profiles()
            original_page = window.page_stack.currentWidget()
            drafts = [dict(stem="第一题", subject="数学", question_type="填空题", answer="1", explanation="解析"),
                      dict(stem="第二题", subject="英语", answer="B")]
            with patch("app.ui.image_recognition_dialog.recognize_image", return_value=drafts) as request:
                window.showMinimized()
                window._screenshot_captured(image.copy())
                popup = window._recognition_dialogs[-1]
                screenshot = popup.image_path
                assert popup.isWindow() and popup.isVisible() and screenshot.exists()
                assert not window.isMinimized()
                assert window.page_stack.currentWidget() is original_page
                assert window.start_image_recognition() is popup
                wait_until(lambda: popup.draft_editor is not None)
                original_screenshot = screenshot
                screenshot = popup.image_path
                assert screenshot.exists()
                assert request.call_count == 1 and len(store.list_questions()) == 0
                editor = popup.draft_editor
                popup.set_image(str(external))
                assert popup.image_path == screenshot
                editor.stem.setPlainText("核对后的第一题")
                editor.question_selector.setCurrentIndex(1)
                assert editor.values()[0]["stem"] == "核对后的第一题"
                editor._accept_if_valid()
                assert len(store.list_questions()) == 2 and not screenshot.exists() and not original_screenshot.exists()
                assert window.page_stack.currentWidget() is original_page
                assert not window._recognition_dialogs and external.exists()
                for question in store.list_questions():
                    records = store.list_attachments(question["id"])
                    assert len(records) == 1 and attachments.attachment_file(records[0]["relative_path"]).exists()
            release, started = Event(), Event()

            def blocked(_profile, path):
                started.set()
                assert release.wait(3)
                assert Path(path).exists()  # closing keeps source alive until worker finishes
                return drafts

            with patch("app.ui.image_recognition_dialog.recognize_image", side_effect=blocked) as request:
                window._screenshot_captured(image.copy())
                popup = window._recognition_dialogs[-1]
                screenshot = popup.image_path
                wait_until(started.is_set)
                original_screenshot = screenshot
                screenshot = popup.image_path
                assert not popup.paste_button.isEnabled() and not popup.drop_zone.acceptDrops()
                popup.recognize()
                popup.set_image(str(external))
                assert popup.image_path == screenshot and request.call_count == 1
                popup.close()
                assert not popup.isVisible() and screenshot.exists() and popup._dismissed
                release.set()
                wait_until(lambda: popup not in window._recognition_dialogs)
                assert screenshot.exists() and not original_screenshot.exists() and len(store.list_questions()) == 2
                assert store.load_workspace(popup.session_key) is not None
                assert window.page_stack.currentWidget() is original_page
            with patch("app.ui.image_recognition_dialog.recognize_image", side_effect=ProviderError("HTTP 502", "details")):
                popup = window.start_image_recognition(external, auto_recognize=True)
                wait_until(lambda: "HTTP 502" in popup.status.text())
                assert popup.isVisible() and popup.recognize_button.isEnabled() and popup.paste_button.isEnabled()
                assert popup.image_path.exists() and external.exists()
                assert popup.details_button.isVisible()
                popup.details_button.click()
                assert popup.response_details.isVisible() and popup.response_details.toPlainText() == "details"
                popup.details_button.click()
                assert not popup.response_details.isVisible()
                assert not any(key.startswith("recognition") for key in window._pages)
                popup.reject()
                assert not window._recognition_dialogs and len(store.list_questions()) == 2
            markdown = (Path(__file__).parent / 'fixtures/recognition_limit_markdown.md').read_text(encoding='utf-8')
            with patch('app.ui.image_recognition_dialog.recognize_image', side_effect=ProviderError('旧格式响应', markdown)) as request:
                popup = window.start_image_recognition(external, auto_recognize=True)
                wait_until(lambda: '旧格式响应' in popup.status.text())
                key = popup.session_key
                assert recognition_drafts.load(key)[0]['raw_response'] == markdown
                popup.close()
                popup = window.start_image_recognition(resume_key=key)
                assert popup.response_details.toPlainText() == markdown and request.call_count == 1
                popup.recover_text_button.click()
                assert popup.draft_editor is not None and len(popup.draft_editor.values()) == 1
                assert request.call_count == 1 and len(store.list_questions()) == 2
                assert r'\begin{cases}' in popup.draft_editor.values()[0]['answer']
                state, original = recognition_drafts.load(key)
                assert state['raw_response'] == markdown and original.exists()
                popup.draft_editor._accept_if_valid()
                assert len(store.list_questions()) == 3 and not original.exists()
                assert external.exists() and request.call_count == 1
            # A response from one image must not be reused after choosing another.
            popup = window.start_image_recognition(external)
            popup.response_details.setPlainText(markdown)
            popup.set_image(str(external))
            assert not popup.response_details.toPlainText()
            popup.close()
            popup = window.start_image_recognition(external)
            window.close()
            assert not popup.isVisible() and not window._recognition_dialogs
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    print("PASS: screenshot popup, multi-question save, late-result protection, stored response/restart/local recovery, original-image import and shutdown")


if __name__ == "__main__":
    check()
