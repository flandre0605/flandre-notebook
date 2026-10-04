"""Opt-in packaged runtime acceptance; requires an explicit, empty test workspace."""
import json
import os
from pathlib import Path
import sys
import traceback
import ctypes
from ctypes import wintypes


def verify_package(app, window, report_path):
    from PySide6.QtCore import QElapsedTimer, QSettings, QThread
    from PySide6.QtGui import QImage
    from app.database import store
    from app.paths import PROJECT_ROOT
    from app.services import attachments, backup, credentials, question_files
    from app.ui.math_text import _formula_image
    from app.ui.pronunciation import Pronunciation

    report = dict(frozen=bool(getattr(sys, "frozen", False)), ok=False)
    report_path = Path(report_path)
    speech = None
    try:
        if not os.environ.get("FLANDRE_DATA_DIR") or store.list_questions() or store.list_profiles():
            raise ValueError("Runtime verification requires a new FLANDRE_DATA_DIR workspace.")
        root = store.DATA_DIR
        for resource in ("flandre_icon.png", "flandre_icon.ico", "flandre_pet_chibi.png", "ui", "question_template.csv",
                         "vocabulary_template.csv", "vocabulary_template.txt"):
            assert (PROJECT_ROOT / "assets" / resource).exists(), resource
        for expression in ("happy", "thinking", "sad", "sleepy", "surprised"):
            sprite = QImage(str(PROJECT_ROOT / "assets" / "pet_expressions" / f"{expression}.png"))
            assert not sprite.isNull() and sprite.hasAlphaChannel(), expression
        credentials._require_secure_backend()  # Discover the backend without reading or writing a credential.
        report["credential_backend"] = type(credentials.keyring.get_keyring()).__name__
        from app.ui.profiles_dialog import ProfilesDialog
        from app.ui.image_recognition_dialog import ImageRecognitionDialog
        from app.ui.model_selection import fill_model_choices
        from PySide6.QtWidgets import QComboBox
        for identity, vision in (("probe-text", False), ("probe-vision", True)):
            store.save_profile(dict(name=identity, model_id="fixture", base_url="https://example.com/v1",
                                    endpoint_path="/chat/completions", timeout_seconds=5,
                                    vision_enabled=vision, enabled=True), identity)
        defaults = ProfilesDialog(window)
        defaults.default_vision.setCurrentIndex(defaults.default_vision.findData("probe-vision"))
        defaults.default_text.setCurrentIndex(defaults.default_text.findData("probe-text"))
        defaults._save_default_models()
        recognition = ImageRecognitionDialog(parent=window)
        assert recognition.profile.currentData() == "probe-vision"
        text_choice = QComboBox()
        fill_model_choices(text_choice, "text")
        assert text_choice.currentData() == "probe-text"
        recognition.close()
        defaults.close()
        report["default_models"] = True
        width, height, formula = _formula_image(r"\frac{1}{2}+x^2", False)
        assert width > 0 and height > 0 and formula
        question_id = store.save_question(dict(stem=r"Select $x^2$", question_type="单选题",
                                              answer="A", subject="数学", grade="Grade12", notes=r"A local reminder $x^2$",
                                              options={"A": "yes", "B": "no"}))
        original = root / "probe.png"
        image = QImage(24, 24, QImage.Format.Format_RGB32)
        image.fill(0xffeeee)
        assert image.save(str(original))
        attachments.import_image(question_id, original)
        rows = question_files.export_rows()
        question_files.write_questions(root / "probe.pdf", rows)
        assert (root / "probe.pdf").read_bytes().startswith(b"%PDF")
        archive = backup.create_backup(root / "probe.zip")
        backup.restore_backup(archive)
        assert store.get_question(question_id)["grade"] == "Grade12"
        assert store.get_question(question_id)["notes"] == r"A local reminder $x^2$"
        window.show_library()
        window._open_practice([store.get_question(question_id)])
        practice = window._page_dialogs["practice_run"]
        assert not practice.notes_toggle.isVisible() and not practice.notes_view.isVisible()
        practice._choice_buttons["A"].click()
        practice.submit_answer()
        assert practice.result_choice.currentData() == "correct"
        practice.notes_toggle.click()
        assert practice.notes_view.isVisible() and "local reminder" in practice.notes_view.toPlainText()
        practice.is_wrong.setChecked(True)
        assert store.get_question(question_id)["is_wrong"] == 0
        speech = Pronunciation(window)
        report["speech_engine"] = speech.engine.engine() if speech.engine else "unavailable"
        report["english_voices"] = len(speech.voices)
        assert report["speech_engine"] == "sapi", "Windows SAPI speech plugin is missing"
        if speech.voices:
            states = []
            speech.engine.setVolume(0)  # Exercise actual synthesis without playing unexpected audio.
            speech.engine.stateChanged.connect(states.append)
            speech.set_speed(3)
            assert abs(speech.engine.rate() - 0.3) < 0.001
            assert speech.say("hello")
            timer = QElapsedTimer()
            timer.start()
            while timer.elapsed() < 5000 and not (speech.engine.State.Speaking in states and
                                                  speech.engine.state() == speech.engine.State.Ready):
                app.processEvents()
                QThread.msleep(10)
            assert speech.engine.State.Speaking in states and speech.engine.state() == speech.engine.State.Ready
            report["silent_speech_completed"] = True
        if app.platformName() == "windows":
            assert window.set_screenshot_shortcut("Ctrl+Alt+F23")
            received = []
            hotkey = window._screenshot_hotkey
            hotkey.callback = lambda: received.append(True)
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            user32.PostMessageW.restype = wintypes.BOOL
            assert user32.PostMessageW(wintypes.HWND(int(window.winId())), hotkey.WM_HOTKEY, hotkey.HOTKEY_ID, 0)
            timer = QElapsedTimer()
            timer.start()
            while timer.elapsed() < 1000 and not received:
                app.processEvents()
                QThread.msleep(10)
            assert received, "The registered native hotkey did not dispatch to its callback"
            report["native_hotkey_dispatch"] = True
        window._motion.finish()
        app.processEvents()
        assert practice.result_choice.geometry().bottom() < practice.mastery.geometry().top()
        window._practice_scroll.ensureWidgetVisible(practice.record_button)
        app.processEvents()
        assert window.grab().save(str(root / "runtime-preview.png"))
        window.enter_mini_practice()
        mini = window._mini_practice_window
        mini.resize(440, 420)
        app.processEvents()
        mini.scroll.ensureWidgetVisible(practice.record_button)
        app.processEvents()
        assert mini.scroll.horizontalScrollBar().maximum() == 0
        assert mini.scroll.viewport().rect().contains(practice.record_button.mapTo(mini.scroll.viewport(), practice.record_button.rect().center()))
        assert mini.grab().save(str(root / "mini-preview.png"))
        window.restore_mini_practice()
        window._motion.finish()
        window.resize(1040, 680)
        app.processEvents()
        window._practice_scroll.ensureWidgetVisible(practice.record_button)
        app.processEvents()
        assert window._practice_scroll.horizontalScrollBar().maximum() == 0
        assert window._practice_scroll.viewport().rect().contains(practice.record_button.mapTo(window._practice_scroll.viewport(), practice.record_button.rect().center()))
        assert window.grab().save(str(root / "small-preview.png"))
        practice.record_and_continue()
        assert store.get_question(question_id)["is_wrong"] == 1
        report.update(personal_fields=True, practice_marker=True, practice_scroll=True)
        report.update(ok=True, data_dir=str(root), formula=True, pdf=True, backup=True, structured_practice=True)
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if speech:
            speech.stop()
        window.close()
        QSettings().clear()  # main() uses an isolated application name for this invocation.
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
