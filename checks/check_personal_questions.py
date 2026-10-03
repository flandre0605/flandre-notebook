"""Grade, local notes and practice wrong markers, with isolated temporary data only."""
import csv
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch
import zipfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.database import store
from app.question_data import QUESTION_LABELS, validate_question
from app.services import attachments, backup, model_provider, question_files, recognition_drafts
from app.ui.main_window import MainWindow
from app.ui.practice_dialog import load_practice_progress


def rejects(call):
    try:
        call()
    except (ValueError, sqlite3.Error):
        return
    raise AssertionError("Invalid input or transaction accepted")


def pdf_text(path):
    pdf = QPdfDocument()
    pdf.load(str(path))
    text = "\n".join(pdf.getAllText(index).text() for index in range(pdf.pageCount()))
    pdf.close()
    return text


def check():
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("FlandreChecks")
    app.setApplicationName(f"PersonalQuestions-{os.getpid()}")
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "questions.db"
        old = root / "v9.db"
        store.initialize(old)
        with connection(old) as db:
            db.execute("INSERT INTO questions(stem,answer) VALUES('v9 original','42')")
            db.execute("ALTER TABLE questions DROP COLUMN grade")
            db.execute("ALTER TABLE questions DROP COLUMN notes")
            db.execute("PRAGMA user_version=9")
        before = old.read_bytes()
        store.initialize(old)
        with connection(old) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 10
            assert db.execute("SELECT stem,answer,grade,notes FROM questions").fetchone()[:] == ("v9 original", "42", "", "")
        # Upgrade errors roll back added fields and the version.
        broken = root / "broken.db"
        store.initialize(broken)
        with connection(broken) as db:
            db.execute("ALTER TABLE questions DROP COLUMN grade")
            db.execute("PRAGMA user_version=9")
        rejects(lambda: store.initialize(broken))
        with connection(broken) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 9
            assert "grade" not in {row[1] for row in db.execute("PRAGMA table_info(questions)")}
        store.initialize(database)
        with patch.object(store, "_connection", lambda path=None: connection(path or database)), \
             patch.object(store, "DATA_DIR", root), patch.object(store, "DATABASE_PATH", database), \
             patch.object(attachments, "ATTACHMENTS_DIR", root / "attachments"), \
             patch.object(backup, "ATTACHMENTS_DIR", root / "attachments"), \
             patch("app.ui.main_window.GlobalScreenshotHotkey"):
            question = validate_question(dict(stem="Calculate 1+1", subject="数学", question_type="填空题",
                                              answer="2", grade="Grade12", notes="INTERNAL_NOTE_Q89Z\n=keep this line"))
            rejects(lambda: validate_question(dict(question, grade="x" * 101)))
            rejects(lambda: validate_question(dict(question, grade="two\nlines")))
            rejects(lambda: validate_question(dict(question, notes=12)))
            rejects(lambda: validate_question(dict(question, notes="x" * 20001)))
            assert validate_question(dict(stem="old file"))["notes"] == ""
            identity = store.save_question(question)
            store.save_question(dict(stem="Calculate 1+1 again"), identity)
            assert store.get_question(identity)["notes"] == question["notes"]
            assert store.list_questions(search="Grade12") and store.list_questions(search="INTERNAL_NOTE_Q89Z")
            rows = question_files.export_rows()
            for suffix in ("json", "csv"):
                file = root / f"rows.{suffix}"
                question_files.write_questions(file, rows)
                assert question_files.read_questions(file) == rows
            translated = root / "chinese.csv"
            with translated.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(QUESTION_LABELS.values()))
                writer.writeheader()
                writer.writerow({QUESTION_LABELS[key]: json.dumps(value, ensure_ascii=False) if key == "options" else value
                                 for key, value in question.items()})
            assert question_files.read_questions(translated) == [question]
            full_pdf, practice_pdf = root / "full.pdf", root / "practice.pdf"
            question_files.write_questions(full_pdf, rows, True)
            question_files.write_questions(practice_pdf, rows, False)
            assert "Grade12" in pdf_text(full_pdf) and "INTERNAL_NOTE_Q89Z" in pdf_text(full_pdf)
            assert "Grade12" in pdf_text(practice_pdf) and "INTERNAL_NOTE_Q89Z" not in pdf_text(practice_pdf)
            original = root / "original.png"
            image = QImage(30, 20, QImage.Format.Format_RGB32)
            image.fill(0xffffff)
            assert image.save(str(original))
            with patch.object(model_provider, "_request", return_value=json.dumps({"questions": [dict(question, notes="Invented note")]})) as request:
                assert model_provider.recognize_image({}, original)[0]["notes"] == ""
                assert "INTERNAL_NOTE_Q89Z" not in json.dumps(request.call_args.args[1])
            store.save_profile(dict(name="Fixture", model_id="fixture", base_url="https://example.com/v1",
                                    endpoint_path="/chat/completions", timeout_seconds=5,
                                    enabled=True, vision_enabled=True), "fixture")
            window = MainWindow()
            window.show()
            try:
                window.add_question()
                editor = window._page_dialogs["question"]
                editor.stem.setPlainText("Personal draft")
                editor.metadata_inputs["grade"].setText("高二")
                editor.notes.setPlainText("自己的思路 $x^2$")
                editor.save_draft()
                window._discard_page("question")
                window.add_question()
                editor = window._page_dialogs["question"]
                assert editor.metadata_inputs["grade"].text() == "高二" and "自己的思路" in editor.notes.toPlainText()
                editor._save_if_valid()
                saved = next(row for row in store.list_questions() if row["stem"] == "Personal draft")
                window.table.selectRow(next(i for i in range(window.table.rowCount()) if window.table.item(i, 0).data(256) == saved["id"]))
                assert "高二" in window.preview_meta.text() and "自己的思路" in window.preview_notes.toPlainText()
                with patch("app.ui.image_recognition_dialog.recognize_image", return_value=[dict(stem="Model draft")]) as request:
                    popup = window.start_image_recognition(original)
                    popup._recognized([dict(stem="Model draft")])
                    review = popup.draft_editor
                    review.grade.setText("初一")
                    review.notes.setPlainText("Hand-reviewed note")
                    review.question_selector.setCurrentIndex(0)
                    popup.save_progress()
                    previous_key = popup.session_key
                    previous_state = store.load_workspace(previous_key)
                    popup._return_to_input(review)
                    popup.recognize()
                    for _ in range(300):
                        QTest.qWait(10)
                        if popup.draft_editor:
                            break
                    assert request.call_count == 1 and popup.session_key != previous_key
                    assert store.load_workspace(previous_key) == previous_state
                    popup.close()
                    restored = window.start_image_recognition(resume_key=previous_key)
                    restored._continue_draft()
                    assert restored.draft_editor.grade.text() == "初一"
                    assert restored.draft_editor.notes.toPlainText() == "Hand-reviewed note"
                    restored.draft_editor._accept_if_valid()
                    assert any(store.get_question(row["id"])["notes"] == "Hand-reviewed note" for row in store.list_questions())
                window._open_practice([store.get_question(identity)])
                practice = window._page_dialogs["practice_run"]
                assert not practice.notes_toggle.isVisible() and not practice.notes_view.isVisible()
                practice.user_answer.setPlainText("3")
                practice.submit_answer()
                assert practice.is_wrong.isChecked()
                practice.notes_toggle.click()
                assert practice.notes_view.isVisible() and "INTERNAL_NOTE_Q89Z" in practice.notes_view.toPlainText()
                practice.is_wrong.setChecked(False)
                window._motion.finish()
                window.resize(1040, 680)
                QTest.qWait(30)
                scroll = window._practice_scroll
                assert scroll.verticalScrollBar().maximum() > 0 and scroll.horizontalScrollBar().maximum() == 0
                assert practice.result_choice.geometry().bottom() < practice.mastery.geometry().top()
                scroll.ensureWidgetVisible(practice.record_button)
                app.processEvents()
                assert scroll.viewport().rect().contains(practice.record_button.mapTo(scroll.viewport(), practice.record_button.rect().center()))
                window.enter_mini_practice()
                mini = window._mini_practice_window
                mini.resize(440, 420)
                QTest.qWait(30)
                mini.scroll.ensureWidgetVisible(practice.record_button)
                app.processEvents()
                assert mini.scroll.horizontalScrollBar().maximum() == 0
                assert mini.scroll.viewport().rect().contains(practice.record_button.mapTo(mini.scroll.viewport(), practice.record_button.rect().center()))
                window.restore_mini_practice()
                assert window._practice_scroll.widget() is practice and practice.notes_view.isVisible() and not practice.is_wrong.isChecked()
                practice.save_progress()
                progress = load_practice_progress()
                assert progress[1]["is_wrong"] is False
                store.save_workspace("practice", dict(progress[1], is_wrong="false"))
                assert load_practice_progress() is None
                legacy = dict(progress[1])
                legacy.pop("is_wrong")
                store.save_workspace("practice", legacy)
                assert load_practice_progress() is not None
                store.save_workspace("practice", progress[1])
                window._discard_page("practice_run")
                window._open_practice(progress[0], progress[1])
                practice = window._page_dialogs["practice_run"]
                assert practice._submitted and not practice.is_wrong.isChecked()
                practice.is_wrong.setChecked(True)
                with connection(database) as db:
                    db.execute("CREATE TRIGGER fail_progress BEFORE DELETE ON workspace_state BEGIN SELECT RAISE(ABORT, 'fail'); END")
                practice.record_and_continue()
                assert practice.index == 0 and not store.list_attempts()
                assert store.get_question(identity)["is_wrong"] == 0
                with connection(database) as db:
                    db.execute("DROP TRIGGER fail_progress")
                    assert db.execute("SELECT COUNT(*) FROM review_state WHERE question_id=?", (identity,)).fetchone()[0] == 0
                practice.is_wrong.setChecked(False)
                practice.record_and_continue()
                assert practice.index == 1 and len(store.list_attempts()) == 1
                assert store.get_question(identity)["is_wrong"] == 0
                store.record_attempt(identity, "incorrect", 0, "unknown")
                assert store.get_question(identity)["is_wrong"] == 1  # Existing callers retain automatic marking.
                store.record_attempt(identity, "correct", 0, "mastered", is_wrong=False)
                assert store.get_question(identity)["is_wrong"] == 0
                rejects(lambda: store.record_attempt(identity, "correct", 0, "mastered", is_wrong="false"))
                subjective = store.save_question(dict(stem="Explain why", question_type="解答题", answer="Reference"))
                window._open_practice([store.get_question(subjective)])
                practice = window._page_dialogs["practice_run"]
                practice.user_answer.setPlainText("My reasoning")
                practice.submit_answer()
                assert practice.result_choice.isEnabled() and not practice.is_wrong.isChecked()
                practice.result_choice.setCurrentIndex(practice.result_choice.findData("incorrect"))
                assert practice.is_wrong.isChecked()
                practice.is_wrong.setChecked(False)
                practice.record_and_continue()
                assert store.get_question(subjective)["is_wrong"] == 0
                unavailable = window.start_image_recognition(original)
                with connection(database) as db:
                    db.execute("UPDATE model_profiles SET enabled=0")
                with patch("app.ui.image_recognition_dialog.recognize_image") as request:
                    unavailable.recognize()
                    assert not unavailable._recognizing and not unavailable.recognize_button.isEnabled()
                    assert request.call_count == 0 and "已不可用" in unavailable.status.text()
                unavailable.close()
                archive = backup.create_backup(root / "roundtrip.zip")
                backup.restore_backup(archive)
                assert store.get_question(identity)["notes"] == question["notes"]
                # A historical v9 ZIP upgrades only its staged copy.
                old_zip = root / "v9.zip"
                with zipfile.ZipFile(old_zip, "w") as archive:
                    archive.writestr("database.sqlite3", before)
                backup.restore_backup(old_zip)
                assert store.get_question(1)["grade"] == "" and store.get_question(1)["notes"] == ""
                bad = root / "bad.db"
                store.initialize(bad)
                with connection(bad) as db:
                    db.execute("INSERT INTO questions(stem,notes) VALUES('bad',?)", ("x" * 20001,))
                with zipfile.ZipFile(root / "bad.zip", "w") as archive:
                    archive.write(bad, "database.sqlite3")
                rejects(lambda: backup.restore_backup(root / "bad.zip"))
                assert store.get_question(1)["stem"] == "v9 original"
            finally:
                window.close()
                QSettings().clear()
    print("Personal question checks passed: v9 upgrade/rollback, grade/notes editors/search/files/PDF/ZIP, protected re-recognition, notes hidden, wrong-marker recovery and atomic recording.")


if __name__ == "__main__":
    check()
