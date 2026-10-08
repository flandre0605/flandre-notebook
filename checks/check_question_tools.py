"""Run with .venv/Scripts/python.exe checks/check_question_tools.py [preview-directory]."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter
from PySide6.QtCore import QSize
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication
from app.database import store
from app.services import question_files as files
from app.ui.main_window import MainWindow
from app.ui.history_dialog import HistoryDialog


def check():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda: connection(database)), patch("app.ui.main_window.GlobalScreenshotHotkey"):
            assert len(files.read_questions(Path(__file__).resolve().parents[1] / "checks" / "fixtures" / "question_template.csv")) == 2
            rows = files.validate_questions([dict(stem=r"计算 $\frac{1}{2}+\frac{1}{3}$", subject="数学", answer="5/6", is_wrong=1),
                                             dict(stem="=危险的电子表格公式", subject="英语", answer="'quoted")])
            assert files.import_questions(rows) == (2, 0)
            assert files.import_questions(rows) == (0, 2)
            for suffix in ("json", "csv"):
                path = root / f"questions.{suffix}"
                files.write_questions(path, rows)
                assert files.read_questions(path) == rows
            try:
                files.import_questions([dict(stem="should not be written"), dict(stem="")])
                assert False
            except ValueError:
                assert len(store.list_questions()) == 2
            csv = root / "chinese.csv"
            csv.write_text('题干,学科,答案,错题\n"含逗号,和换行\n第二行",语文,答案,是', encoding="utf-8-sig")
            assert files.read_questions(csv)[0]["is_wrong"] == 1
            assert "\n第二行" in files.read_questions(csv)[0]["stem"]
            assert len(files.export_rows(subject="数学")) == 1
            files.write_questions(root / "print.pdf", rows)
            assert (root / "print.pdf").read_bytes().startswith(b"%PDF")
            pdf = root / "print.pdf"
            old = pdf.read_bytes()
            try:
                files.write_questions(pdf, [])
                assert False
            except ValueError:
                assert pdf.read_bytes() == old
            question_id = next(row["id"] for row in store.list_questions() if row["subject"] == "数学")
            for result in ("correct", "incorrect", "skipped", "incorrect"):
                store.record_attempt(question_id, result, 60, "unsure", "计算失误")
            statistics = store.learning_statistics()
            assert statistics["total"] == dict(attempts=4, correct=1, incorrect=2, skipped=1, seconds=240, days=1)
            assert sum(row["attempts"] for row in statistics["daily"]) == 4
            assert statistics["reasons"] == [dict(mistake_reason="计算失误", count=2)]
            window = MainWindow()
            window.show_library()
            window.show()
            app.processEvents()
            assert window.read_button.isEnabled()
            window.read_question()
            assert window.page_stack.currentWidget() == window._pages["reader"]
            window._page_dialogs["reader"].reject()
            window.show_question_files()
            dialog = window._page_dialogs["question_files"]
            with patch("app.ui.question_files_dialog.QFileDialog.getOpenFileName", return_value=(str(root / "questions.json"), "")):
                dialog.choose_file()
            assert dialog.table.rowCount() == 2
            dialog.table.item(0, 0).setText("修改后的题目")
            dialog.confirm_import()
            assert "新增 1 道" in dialog.status.text()
            history = HistoryDialog(window)
            assert history.subject_table.rowCount() == 1
            assert history.subject_table.item(0, 2).text() == "33%"
            assert "数学" in history.suggestion.text()
            if len(sys.argv) > 1:
                destination = Path(sys.argv[1])
                destination.mkdir(parents=True, exist_ok=True)
                preview_pdf = destination / "questions.pdf"
                preview_pdf.write_bytes((root / "print.pdf").read_bytes())
                document = QPdfDocument()
                assert document.load(str(preview_pdf)) == QPdfDocument.Error.None_
                assert not document.render(0, QSize(800, 1132)).isNull()
                page = QImage(800, 1132, QImage.Format.Format_ARGB32)
                page.fill("white")
                painter = QPainter(page)
                painter.drawImage(0, 0, document.render(0, QSize(800, 1132)))
                painter.end()
                page.save(str(destination / "print-preview.png"))
                document.close()
                window.show_library()
                window._motion.finish()
                app.processEvents()
                window.grab().save(str(destination / "library.png"))
                history.resize(1040, 680)
                history.show()
                app.processEvents()
                history.grab().save(str(destination / "statistics.png"))
            history.close()
            window.close()
    print("question file round trips, atomic import, PDF, UI routes and statistics: OK")


if __name__ == "__main__":
    check()
