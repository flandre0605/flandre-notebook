"""Temporary-data checks for structured choices, review settings and pending work recovery."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import zipfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from app.database import store, vocabulary
from app.question_data import parse_options, validate_question
from app.services import attachments, backup, question_files, recognition_drafts
from app.services.grading import grade_answer
from app.ui.main_window import MainWindow
from app.ui.practice_dialog import PracticeDialog
from check_vocabulary_enrichment import SilentSpeech


def rejects(call):
    try:
        call()
    except (ValueError, sqlite3.Error):
        return
    raise AssertionError("Invalid operation succeeded")


def check(previews=None):
    app = QApplication.instance() or QApplication([])
    for font in ("msyh.ttc", "msyhbd.ttc"):
        QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    if previews:
        previews.mkdir(parents=True, exist_ok=True)
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda path=database: connection(path)), \
             patch.object(store, "DATA_DIR", root), patch.object(store, "DATABASE_PATH", database), \
             patch.object(attachments, "ATTACHMENTS_DIR", root / "attachments"), \
             patch.object(backup, "ATTACHMENTS_DIR", root / "attachments"), \
             patch("app.ui.main_window.GlobalScreenshotHotkey"), \
             patch("app.ui.vocabulary_page.Pronunciation", SilentSpeech), \
             patch("app.ui.image_recognition_dialog.recognize_image") as model, \
             patch("app.ui.vocabulary_page.translate_words") as translation:
            options = {"A": "one", "B": "two", "C": r"$x^2$"}
            question = validate_question(dict(stem="Select two", question_type="多选题", options=options, answer="AC"))
            rejects(lambda: parse_options({"A": "only"}))
            rejects(lambda: parse_options({"a": "bad", "B": "two"}))
            assert grade_answer("单选题", "A", "A", "{}") is True
            assert grade_answer("多选题", "AC", "C,A", options) is True
            assert grade_answer("多选题", "AC", "AB", options) is False
            assert grade_answer("多选题", "AC", "AA", options) is None
            assert grade_answer("单选题", "A", "one", options) is True
            question_id = store.save_question(question)
            for suffix in ("json", "csv"):
                path = root / f"questions.{suffix}"
                question_files.write_questions(path, [question])
                assert question_files.read_questions(path) == [question]
            assert question_files.import_questions([dict(question, options=dict(reversed(list(options.items()))))]) == (0, 1)
            store.save_review_intervals(dict(mastered=10, unsure=2, unknown=0))
            store.record_attempt(question_id, "correct", 10, "mastered")
            with connection(database) as db:
                previous = dict(db.execute("SELECT * FROM review_state").fetchone())
                assert db.execute("SELECT julianday(due_at) - julianday(last_reviewed_at) FROM review_state").fetchone()[0] == 10
            store.save_review_intervals(dict(mastered=3, unsure=1, unknown=0))
            with connection(database) as db:
                assert dict(db.execute("SELECT * FROM review_state").fetchone()) == previous
            rejects(lambda: store.save_review_intervals(dict(mastered=True, unsure=1, unknown=0)))
            window = MainWindow()
            window.show()
            window._open_practice([store.get_question(question_id)])
            practice = window._page_dialogs["practice_run"]
            practice.submit_answer()
            assert not practice._submitted
            practice._choice_buttons["A"].click()
            practice._choice_buttons["C"].click()
            practice.submit_answer()
            assert practice.result_choice.currentData() == "correct"
            assert practice.choice_scroll.isEnabled() and not practice._choice_buttons["A"].isEnabled()
            practice.save_progress()
            single_id = store.save_question(dict(stem="Select one", question_type="单选题", options={"A": "one", "B": "two"}, answer="B"))
            single = PracticeDialog([store.get_question(single_id)], window)
            single._choice_buttons["A"].click()
            single._choice_buttons["B"].click()
            assert not single._choice_buttons["A"].isChecked() and single.user_answer.toPlainText() == "B"
            single.submit_answer()
            assert single.result_choice.currentData() == "correct"
            single._checkpoint.stop()
            single.deleteLater()
            window.manage_profiles()
            review_settings = window._profiles_dialog.review_settings
            review_settings.inputs["mastered"].setValue(9)
            review_settings.save()
            assert store.review_intervals()["mastered"] == 9
            window._show_page("practice_run")
            assert "9 天" in practice.mastery.itemText(practice.mastery.findData("mastered"))
            if previews:
                QTest.qWait(240)
                assert window.grab().save(str(previews / "choice-practice.png"))
            window.show_vocabulary()
            page = window.vocabulary_page
            alpha = vocabulary.save_word(dict(word="alpha", meaning="第一个"))
            beta = vocabulary.save_word(dict(word="beta", meaning="第二个"))
            page.show_import_draft([dict(word="gamma", meaning="伽马", phonetic="", example="已补全例句", book="词表"),
                                    dict(word="delta", meaning="", phonetic="", example="", book="词表")], "missing-source.txt")
            page.import_table.item(0, 1).setText("保留修改")
            page.show_library()
            page.edit_word(alpha)
            page.meaning.setPlainText("未保存的词条释义")
            page.show_library()
            page.study.begin([vocabulary.get_word(alpha), vocabulary.get_word(beta)], "spelling")
            page.study.answer.setText("alpha")
            page.study.reveal()
            page.study.record("known")
            page.study.answer.setText("bet")
            image = root / "original.png"
            pixels = QImage(200, 120, QImage.Format.Format_RGB32)
            pixels.fill("white")
            assert pixels.save(str(image))
            popup = window.start_image_recognition(image)
            popup._recognized([question, dict(stem="Second question", answer="2")])
            popup.draft_editor.stem.setPlainText("核对后的题干")
            popup.draft_editor.question_selector.setCurrentIndex(1)
            popup.save_progress()
            first_key = popup.session_key
            saved_image = popup.image_path
            second_key, second_state, _ = recognition_drafts.create(image, "")
            assert len(recognition_drafts.keys()) == 2
            window.close()
            assert saved_image.exists() and image.exists()
            window = MainWindow()
            window.show()
            window.show_vocabulary()
            page = window.vocabulary_page
            assert page.import_table.item(0, 1).text() == "保留修改"
            assert page.import_table.item(0, 3).text() == "已补全例句"
            assert page.views.currentWidget() is page.library
            page.edit_word(alpha)
            assert page.meaning.toPlainText() == "未保存的词条释义"
            page.save_word()
            assert store.load_workspace(f"vocabulary:word:{alpha}") is None
            page.start_study()
            assert page.study.index == 1 and page.study.answer.text() == "bet" and not page.study.revealed
            page.study.reveal()
            assert page.study.correct is False
            with patch.object(store, "_write_workspace", side_effect=sqlite3.OperationalError("checkpoint failed")):
                page.study.record("forgot")
            assert vocabulary.get_word(beta)["review_count"] == 0 and page.study.index == 1
            page.study.record("forgot")
            assert vocabulary.get_word(beta)["review_count"] == 1 and store.load_workspace("vocabulary:study") is None
            popup = window.start_image_recognition(resume_key=first_key)
            assert popup.draft_editor.current_index == 1
            assert popup.draft_editor.values()[0]["stem"] == "核对后的题干"
            assert not model.called and not translation.called
            if previews:
                QTest.qWait(240)
                assert popup.grab().save(str(previews / "recognition-recovery.png"))
            popup.save_progress()
            snapshot = root / "snapshot.zip"
            window._save_workspaces()
            backup.create_backup(snapshot)
            with connection(database) as db:
                db.execute("CREATE TRIGGER fail_batch BEFORE INSERT ON questions WHEN NEW.stem = 'Second question' BEGIN SELECT RAISE(ABORT, 'failed'); END")
            count = len(store.list_questions())
            popup._save_draft(popup.draft_editor)
            assert len(store.list_questions()) == count and store.load_workspace(first_key) is not None
            with connection(database) as db:
                db.execute("DROP TRIGGER fail_batch")
            popup._save_draft(popup.draft_editor)
            assert len(store.list_questions()) == count + 2 and store.load_workspace(first_key) is None and not saved_image.exists()
            recovery = backup.restore_backup(snapshot)
            assert recovery.exists() and recognition_drafts.load(first_key)[1].exists()
            window.vocabulary_page.reset()
            assert page.import_table.rowCount() == 2
            damaged = root / "missing-draft-image.zip"
            with zipfile.ZipFile(snapshot) as source, zipfile.ZipFile(damaged, "w") as target:
                for item in source.infolist():
                    if item.filename != store.load_workspace(first_key)["image"]:
                        target.writestr(item, source.read(item.filename))
            rejects(lambda: backup.restore_backup(damaged))
            popup = window.start_image_recognition(resume_key=first_key)
            popup.draft_editor.question_selector.setCurrentIndex(0)
            popup.draft_editor.stem.setPlainText("旧窗口内容不得写回")
            with patch("app.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(snapshot), "")), \
                 patch("app.ui.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.Yes), \
                 patch("app.ui.main_window.QMessageBox.information"):
                window.restore_backup()
            QTest.qWait(700)
            assert not window._recognition_dialogs
            assert recognition_drafts.load(first_key)[0]["drafts"][0]["stem"] == "核对后的题干"
            recognition_drafts.discard(second_key, second_state)
            assert store.load_workspace(second_key) is None
            window.close()
            QTest.qWait(30)
    print("PASS: structured options, review rules, word/image drafts, restart, atomic progress/import and ZIP recovery; no network/audio")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
