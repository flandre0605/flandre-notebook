"""Default model selection in temporary settings and data; no API or speech calls."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtWidgets import QApplication, QComboBox
from app.database import store
from app.services import attachments, recognition_drafts
from app.ui.image_recognition_dialog import ImageRecognitionDialog
from app.ui.model_selection import fill_model_choices
from app.ui.profiles_dialog import ProfilesDialog
from app.ui.vocabulary_page import VocabularyPage
from app.ui.theme import STYLE
from check_vocabulary_enrichment import SilentSpeech


def check():
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("FlandreChecks")
    app.setApplicationName(f"ModelSelection-{os.getpid()}")
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root))
        database = root / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda: connection(database)), \
             patch.object(store, "DATA_DIR", root), \
             patch.object(attachments, "ATTACHMENTS_DIR", root / "attachments"), \
             patch("app.ui.vocabulary_page.Pronunciation", SilentSpeech):
            for identity, name, vision, enabled in (("a", "A text", False, True), ("b", "B vision", True, True),
                                                    ("c", "C vision", True, True), ("d", "D disabled", True, False)):
                store.save_profile(dict(name=name, model_id=identity, base_url="https://example.com/v1",
                                        endpoint_path="/chat/completions", timeout_seconds=5,
                                        vision_enabled=vision, enabled=enabled), identity)
            settings = ProfilesDialog()
            assert settings.default_vision.findData("a") == -1
            assert settings.default_vision.findData("d") == -1
            settings.default_vision.setCurrentIndex(settings.default_vision.findData("c"))
            settings.default_text.setCurrentIndex(settings.default_text.findData("a"))
            settings.save_defaults_button.click()
            assert "已保存" in settings.default_status.text()
            assert Path(QSettings().fileName()).is_relative_to(root)
            with patch.object(store, "get_profile", side_effect=sqlite3.OperationalError("read failed")):
                settings._save_default_models()
            assert "未保存" in settings.default_status.text()
            assert QSettings().value("default_models/vision") == "c"
            persisted = subprocess.check_output([sys.executable, "-c",
                "import sys; from PySide6.QtCore import QSettings; "
                "QSettings.setDefaultFormat(QSettings.Format.IniFormat); "
                "QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,sys.argv[1]); "
                "s=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,'FlandreChecks',sys.argv[2]); "
                "assert s.value('default_models/vision')=='c'; "
                "assert s.value('default_models/text')=='a'; print('persisted')",
                str(root), app.applicationName()])
            assert persisted.strip() == b"persisted"
            reopened = ProfilesDialog()
            assert reopened.default_vision.currentData() == "c" and reopened.default_text.currentData() == "a"
            if len(sys.argv) > 1:
                reopened.setStyleSheet(STYLE)
                reopened.resize(900, 600)
                reopened.settings_tabs.setCurrentIndex(1)
                reopened.show()
                app.processEvents()
                assert reopened.grab().save(sys.argv[1])
            recognition = ImageRecognitionDialog()
            assert recognition.profile.currentData() == "c"
            words = VocabularyPage(None)
            assert words.profile.currentData() == "a"
            words.profile.setCurrentIndex(words.profile.findData("b"))
            QSettings().setValue("default_models/text", "c")
            words.refresh_profiles()
            assert words.profile.currentData() == "b"  # Keep an active task's manual selection.
            words.edit_word()
            assert words.profile.currentData() == "c"  # A new task observes updated defaults.
            words.profile.setCurrentIndex(words.profile.findData("b"))
            words.show_import_draft([dict(word="example", meaning="", phonetic="", example="", book="")], "demo.txt")
            assert words.profile.currentData() == "c"
            original = root / "original.png"
            image = QImage(30, 20, QImage.Format.Format_RGB32)
            image.fill(0xffffff)
            assert image.save(str(original))
            key, _, _ = recognition_drafts.create(original, "b")
            resumed = ImageRecognitionDialog(resume_key=key)
            assert resumed.profile.currentData() == "b"  # A draft owns its original model choice.
            resumed.close()
            recognition.close()
            words.close()
            # Disable a default after choosing it; saving must revalidate rather than accept stale UI.
            with connection(database) as db:
                db.execute("UPDATE model_profiles SET enabled=0 WHERE id='c'")
            reopened._save_default_models()
            assert "不可用" in reopened.default_status.text()
            fallback = QComboBox()
            fill_model_choices(fallback, "vision")
            assert fallback.currentData() == "b"
            store.delete_profile("c")
            fill_model_choices(fallback, "text")
            assert fallback.currentData() == "b"
            reopened._reload()
            reopened.default_vision.setCurrentIndex(0)
            reopened.default_text.setCurrentIndex(0)
            reopened._save_default_models()
            assert QSettings().value("default_models/vision") == ""
            assert QSettings().value("default_models/text") == ""
            with patch.object(store, "list_profiles", side_effect=sqlite3.OperationalError("read failed")):
                words.refresh_profiles()
            assert words.profile.currentData() is None and "read failed" in words.profile.toolTip()
            for identity in ("a", "b", "d"):
                store.delete_profile(identity)
            empty = ImageRecognitionDialog()
            assert not empty.recognize_button.isEnabled() and not empty.profiles
            assert empty.profile.currentData() is None
            empty.close()
            settings.close()
            reopened.close()
            QSettings().clear()
    print("Default model checks passed: persistence, capabilities, manual choice, draft recovery, stale/default fallback, empty/error states.")


if __name__ == "__main__":
    check()
