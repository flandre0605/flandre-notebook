"""Run with .venv/Scripts/python.exe checks/check_practice_subjects.py."""

import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QMessageBox

from app.database import store
from app.ui.main_window import MainWindow


def check():
    app = QApplication.instance() or QApplication([])
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda: connection(database)), patch(
            "app.ui.main_window.GlobalScreenshotHotkey"
        ):
            ordinary = store.save_question(dict(stem="数学普通题", subject="数学", question_type="单选题"))
            wrong = store.save_question(dict(stem="数学错题", subject="数学", question_type="单选题", is_wrong=1))
            due = store.save_question(dict(stem="数学复习题", subject="数学", question_type="简答题"))
            language = store.save_question(dict(stem="语文错题", subject="语文", question_type="单选题", is_wrong=1))
            store.record_attempt(due, "correct", 1, "unknown")
            window = MainWindow()
            window.show()
            window.subject_filter.setCurrentIndex(window.subject_filter.findData("语文"))
            window.state_filter.setCurrentIndex(window.state_filter.findData("wrong"))
            window.type_filter.setCurrentIndex(window.type_filter.findData("单选题"))
            window.search.setText("语文")
            window.start_practice()
            setup = window._practice_setup
            assert setup.subject.currentData() == "语文"
            assert not setup.use_library_filters.isChecked()
            for mode, subject, expected in (
                ("all", "数学", {ordinary, wrong, due}),
                ("wrong", "数学", {wrong}),
                ("due", "数学", {due}),
                ("all", "语文", {language}),
                ("all", "", {ordinary, wrong, due, language}),
            ):
                window.start_practice()
                setup.mode.setCurrentIndex(setup.mode.findData(mode))
                setup.subject.setCurrentIndex(setup.subject.findData(subject))
                setup.accept()
                run = window._page_dialogs["practice_run"]
                assert {question["id"] for question in run.questions} == expected
                assert window.page_stack.currentWidget() == window._pages["practice_run"]
                if mode == "all" and subject == "数学":
                    run.submit_answer()
                    assert run.solution.isVisible()
                    assert window._motion._target is run
                with patch("app.ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                    window.end_practice()
            window.start_practice()
            setup.mode.setCurrentIndex(setup.mode.findData("all"))
            setup.subject.setCurrentIndex(setup.subject.findData("数学"))
            setup.use_library_filters.setChecked(True)
            setup.accept()
            assert "practice_run" not in window._pages
            assert setup.status.text()
            assert setup.isVisible()
            window.search.clear()
            setup.accept()
            run = window._page_dialogs["practice_run"]
            assert {question["id"] for question in run.questions} == {wrong}
            with patch("app.ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                window.end_practice()
            english = store.save_question(dict(stem="英语题", subject="英语"))
            window.start_practice()
            assert setup.subject.findData("英语") >= 0
            assert setup.subject.currentData() == "数学"
            setup.use_library_filters.setChecked(False)
            setup.random_order.setChecked(True)
            setup.accept()
            run = window._page_dialogs["practice_run"]
            assert {question["id"] for question in run.questions} == {ordinary, wrong, due}
            with patch("app.ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                window.end_practice()
            for question_id in (ordinary, wrong, due, language, english):
                store.delete_question(question_id)
            window.start_practice()
            assert setup.subject.count() == 1
            assert setup.subject.currentData() == ""
            setup.accept()
            assert "practice_run" not in window._pages
            assert setup.status.text()
            app.processEvents()
            window.close()
    print("Practice subject check passed (temporary database only).")


if __name__ == "__main__":
    check()
