"""Run with .venv/Scripts/python.exe checks/check_vocabulary.py [preview-directory]."""

from datetime import datetime
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from unittest.mock import patch
import zipfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

from app.database import store, vocabulary
from app.services import backup
from app.ui.main_window import MainWindow


def fails(call, error_type=ValueError):
    try:
        call()
    except error_type:
        return
    raise AssertionError("Invalid input was accepted")


def check(preview_directory=None):
    app = QApplication.instance() or QApplication([])
    if sys.platform == "win32":
        for font in ("msyh.ttc", "msyhbd.ttc"):
            QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "questions.db"
        store.initialize(database)
        with connection(database) as db:
            for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'sync_%'").fetchall():
                db.execute(f'DROP TRIGGER "{name}"')
            for table in ('mobile_inbox_drafts', 'mobile_inbox', 'sync_outbox', 'sync_imports', 'sync_attachments', 'sync_entities', 'sync_state'):
                db.execute(f'DROP TABLE {table}')
            db.execute("INSERT INTO questions (stem) VALUES ('旧题目必须保留')")
            db.execute("DROP TABLE vocabulary_words")
            db.execute("DROP TABLE workspace_state")
            db.execute("DROP TABLE review_preferences")
            for field in ("tags", "knowledge_points", "difficulty", "source", "options", "grade", "notes"):
                db.execute(f"ALTER TABLE questions DROP COLUMN {field}")
            db.execute("PRAGMA user_version = 5")
        legacy = root / "legacy.zip"
        with zipfile.ZipFile(legacy, "w") as archive:
            archive.write(database, "database.sqlite3")
        store.initialize(database)
        with patch.object(store, "_connection", lambda path=database: connection(path)), patch(
            "app.ui.main_window.GlobalScreenshotHotkey"
        ), patch.object(store, "DATABASE_PATH", database), patch.object(store, "DATA_DIR", root), patch.object(
            backup, "ATTACHMENTS_DIR", root / "attachments"
        ):
            store.initialize(database)
            assert store.get_question(1)["stem"] == "旧题目必须保留"
            assert vocabulary.summary_and_books()[0] == (0, 0, 0)
            fails(lambda: vocabulary.save_word(dict(word="", meaning="释义")))
            fails(lambda: vocabulary.save_word(dict(word="word", meaning="")))
            window = MainWindow()
            window.show()
            window.show_vocabulary()
            page = window.vocabulary_page
            assert not page.delete_button.isEnabled()
            page.start_study()
            assert page.views.currentWidget() is page.library and page.status.text()
            page.edit_word()
            page.word.setText("Remember")
            page.meaning.setPlainText("v. 记得；想起")
            page.example.setPlainText("Remember to bring your notebook.")
            page.book.setText("我的生词")
            page.save_word()
            word_id = vocabulary.list_words()[0]["id"]
            assert page.views.currentWidget() is page.library
            fails(lambda: vocabulary.save_word(dict(word="remember", meaning="重复")))
            for expected in (1, 3, 7, 14, 30, 30):
                vocabulary.record_review(word_id, "known")
                row = vocabulary.get_word(word_id)
                interval = datetime.fromisoformat(row["due_at"]) - datetime.fromisoformat(row["last_reviewed_at"])
                assert interval.days == expected
            page.edit_word(word_id)
            page.meaning.setPlainText("v. 记住；记得")
            page.save_word()
            assert vocabulary.get_word(word_id)["streak"] == 6
            vocabulary.record_review(word_id, "hard")
            assert vocabulary.get_word(word_id)["streak"] == 0
            vocabulary.record_review(word_id, "forgot")
            assert len(vocabulary.list_words(scope="due")) == 1
            fails(lambda: vocabulary.record_review(word_id, "invalid"))
            page.import_file(Path(__file__).resolve().parents[1] / "checks" / "fixtures" / "vocabulary_template.csv")
            assert len(vocabulary.list_words()) == 10
            assert vocabulary.get_word(word_id)["meaning"] == "v. 记住；记得"
            bad_csv = root / "bad.csv"
            bad_csv.write_text("word,meaning\nvalid,有效\nbroken,\n", encoding="utf-8")
            fails(lambda: vocabulary.import_csv(bad_csv))
            assert len(vocabulary.list_words()) == 10
            chinese = root / "chinese.csv"
            chinese.write_text("单词,释义,单词本\nKEEP GOING,继续；坚持下去,短语\n", encoding="gb18030")
            assert vocabulary.import_csv(chinese) == (0, 1)
            quoted = root / "quoted.csv"
            quoted.write_text('word,meaning,example\nunique,独特的,"Line one\nLine two"\n', encoding="utf-8-sig")
            assert vocabulary.import_csv(quoted) == (1, 0)
            assert vocabulary.list_words(search="unique")[0]["example"] == "Line one\nLine two"
            page.refresh()

            def capture(name):
                QTest.qWait(240)
                if preview_directory:
                    assert window.grab().save(str(preview_directory / f"vocabulary-{name}.png"))

            page.table.verticalScrollBar().setValue(0)
            capture("library")
            page.book_filter.setCurrentIndex(page.book_filter.findData("我的生词"))
            page.scope.setCurrentIndex(page.scope.findData("due"))
            page.start_study()
            assert len(page.study.words) == 1 and not page.study.solution.isVisible()
            page.study.record("known")
            assert page.study.index == 0
            page.study.reveal()
            capture("card")
            assert page.study.face.contentsRect().height() >= page.study.face.fontMetrics().height()
            page.study.record("known")
            assert page.study.index == 1 and page.study.progress.text() == "本轮完成"
            page.show_library()
            page.scope.setCurrentIndex(page.scope.findData("all"))
            page.mode.setCurrentIndex(page.mode.findData("spelling"))
            page.start_study()
            assert page.study.face.text() == "v. 记住；记得" and not page.study.phonetic.isVisible()
            page.study.reveal()
            assert not page.study.revealed
            page.study.answer.setText("wrong")
            page.study.reveal()
            assert page.study.correct is False and not page.study.known.isVisible()
            page.study.record("known")
            assert vocabulary.get_word(word_id)["streak"] == 0
            page.show_library()
            page.start_study()
            page.study.answer.setText("  REMEMBER  ")
            window.show_library()
            window.show_vocabulary()
            assert page.views.currentWidget() is page.study and page.study.answer.text() == "  REMEMBER  "
            page.study.reveal()
            assert page.study.correct is True
            capture("spelling")
            page.study.record("known")
            page.show_library()
            window.resize(1040, 680)
            capture("compact")
            assert window.width() == 1040 and window.height() == 680
            page.study.begin([vocabulary.get_word(word_id)], "spelling")
            page.views.setCurrentWidget(page.study)
            page.study.words[0]["meaning"] = "较长释义用于检查滚动区域。\n" * 80
            page.study.show_card()
            QTest.qWait(60)
            assert window.width() == 1040 and window.height() == 680
            assert page.study.findChild(QScrollArea, "wordStudyScroll").verticalScrollBar().maximum() > 0
            page.show_library()

            saved = dict(vocabulary.get_word(word_id))
            snapshot = root / "snapshot.zip"
            backup.create_backup(snapshot)
            broken = root / "broken.db"
            shutil.copyfile(database, broken)
            with connection(broken) as db:
                db.execute("DROP TABLE vocabulary_words")
            malformed = root / "malformed.zip"
            with zipfile.ZipFile(malformed, "w") as archive:
                archive.write(broken, "database.sqlite3")
            fails(lambda: backup.restore_backup(malformed), sqlite3.Error)
            assert dict(vocabulary.get_word(word_id)) == saved
            vocabulary.delete_word(word_id)
            backup.restore_backup(snapshot)
            assert dict(vocabulary.get_word(word_id)) == saved
            page.start_study()
            vocabulary.delete_word(word_id)
            page.study.answer.setText("remember")
            page.study.reveal()
            page.study.record("known")
            assert page.study.index == 0 and "保存失败" in page.study.status.text()
            with patch("app.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(legacy), "")), patch(
                "app.ui.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.Yes
            ), patch("app.ui.main_window.QMessageBox.information"):
                window.restore_backup()
            assert not vocabulary.list_words() and page.views.currentWidget() is page.library
            assert not page.study.words and store.get_question(1)["stem"] == "旧题目必须保留"
            window.close()
    print("Vocabulary check passed (migration, CRUD, atomic CSV, cards, spelling, scheduling and backup; temporary data only).")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
