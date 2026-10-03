"""Temporary-database checks for metadata, numeric grading and restart recovery."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from app.database import store
from app.services.grading import grade_answer
from app.services import backup
from app.ui.main_window import MainWindow
from app.ui.practice_dialog import load_practice_progress


def check():
    app = QApplication.instance() or QApplication([])
    assert grade_answer("计算题", r"$\frac{1}{2}$", "0.5") is True
    assert grade_answer("填空题", "50%", "2/4") is True
    assert grade_answer("填空题", ".5", "0.500") is True
    assert grade_answer("计算题", "0.1", "1e-1") is True
    assert grade_answer("计算题", "1/-2", "-0.5") is True
    assert grade_answer("计算题", "1/2", "0.51") is False
    assert grade_answer("计算题", "1/2", "1/0") is None
    assert grade_answer("计算题", "1/2", "1e999999999999") is None
    assert grade_answer("计算题", "$x^2$", "x*x") is None
    assert grade_answer("解答题", "1/2", "0.5") is None
    assert grade_answer("计算题", "1/2", "__import__('os').system('bad')") is None
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "questions.db"
        store.initialize(database)
        root = Path(directory)
        with patch.object(store, "_connection", lambda path=database: connection(path)), patch("app.ui.main_window.GlobalScreenshotHotkey"), \
             patch.object(store, "DATABASE_PATH", database), patch.object(store, "DATA_DIR", root), \
             patch.object(backup, "ATTACHMENTS_DIR", root / "attachments"):
            first = store.save_question(dict(stem="第一题", subject="数学", answer="1/2", question_type="计算题",
                                             tags="易错,极限", knowledge_points="等价无穷小", difficulty="困难", source="课本第 20 页"))
            second = store.save_question(dict(stem="第二题", subject="数学", answer="2", question_type="填空题"))
            assert len(store.list_questions(search="等价无穷小", difficulty="困难")) == 1
            assert not store.list_questions(difficulty="简单")
            store.save_question(dict(stem="第一题修订"), first)
            assert store.get_question(first)["source"] == "课本第 20 页"
            window = MainWindow()
            window.show()
            window.add_question()
            editor = window._page_dialogs["question"]
            editor.stem.setPlainText("未保存题目")
            editor.metadata_inputs["tags"].setText("保存检查")
            QTest.qWait(650)
            assert store.load_workspace("question:new")["stem"] == "未保存题目"
            window.close()
            app.processEvents()
            window = MainWindow()
            window.add_question()
            editor = window._page_dialogs["question"]
            assert editor.stem.toPlainText() == "未保存题目"
            assert editor.metadata_inputs["tags"].text() == "保存检查"
            editor._save_if_valid()
            assert store.load_workspace("question:new") is None
            assert len(store.list_questions()) == 3
            window._open_practice([store.get_question(first), store.get_question(second)])
            practice = window._page_dialogs["practice_run"]
            practice.user_answer.setPlainText("0.5")
            practice.submit_answer()
            practice.mastery.setCurrentIndex(1)
            practice.mistake_reason.setPlainText("保存状态")
            window.close()
            window = MainWindow()
            window.start_practice()
            practice = window._page_dialogs["practice_run"]
            assert practice.index == 0 and practice.user_answer.toPlainText() == "0.5"
            assert practice._submitted and practice.result_choice.currentData() == "correct"
            assert practice.mastery.currentData() == "mastered" and practice.mistake_reason.toPlainText() == "保存状态"
            practice.record_and_continue()
            assert practice.index == 1 and len(store.list_attempts()) == 1
            practice.record_and_continue()  # A fast second click must not submit the next question.
            assert len(store.list_attempts()) == 1
            questions, state = load_practice_progress()
            assert state["index"] == 1 and state["correct_count"] == 1 and not state["submitted"]
            practice.user_answer.setPlainText("2")
            practice.submit_answer()
            with patch.object(store, "_write_workspace", side_effect=__import__('sqlite3').OperationalError("disk full")):
                practice.record_and_continue()
            assert practice.index == 1 and len(store.list_attempts()) == 1
            practice.record_and_continue()
            assert len(store.list_attempts()) == 2 and store.load_workspace("practice") is None
            window.close()
            window = MainWindow()
            window.start_practice()
            assert window.page_stack.currentWidget() == window._pages["practice_setup"]
            window._open_practice([store.get_question(first)])
            with patch("app.ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                window.end_practice()
            assert store.load_workspace("practice") is None and "practice_run" not in window._pages
            assert len(store.list_attempts()) == 2
            store.save_workspace("practice", dict(ids=[999], index=0))
            assert load_practice_progress() is None
            store.save_workspace("practice", None)
            saved = root / "saved.zip"
            backup.create_backup(saved)
            window._open_practice([store.get_question(first)])
            run = window._page_dialogs["practice_run"]
            run.user_answer.setPlainText("旧队列，恢复后不得继续写入")
            window.add_question()
            edit = window._page_dialogs["question"]
            edit.stem.setPlainText("旧草稿，恢复后不得继续写入")
            with patch("app.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(saved), "")), \
                 patch("app.ui.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.Yes), \
                 patch("app.ui.main_window.QMessageBox.information"):
                window.restore_backup()
            QTest.qWait(650)
            assert "practice_run" not in window._pages and "question" not in window._pages
            assert store.load_workspace("practice") is None and store.load_workspace("question:new") is None
            window.close()
    print("metadata, exact numeric grading, drafts, restart, atomic progress and completion: OK")


if __name__ == "__main__":
    check()
