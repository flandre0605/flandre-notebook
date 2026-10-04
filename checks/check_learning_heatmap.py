"""Run with .venv/Scripts/python.exe checks/check_learning_heatmap.py [preview-directory]."""
import os
from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from app.database import store
from app.ui.history_dialog import HistoryDialog
from app.ui.theme import STYLE


def check():
    app = QApplication.instance() or QApplication([])
    if sys.platform == "win32":
        for font in ("msyh.ttc", "msyhbd.ttc"):
            QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
    connection = store._connection
    today = date.today()
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda: connection(database)):
            history = HistoryDialog()
            assert len(history.heatmap.cells) == 90
            assert "暂无练习记录" in history.heatmap.summary.text()
            assert "正确率：—" in history.heatmap.cells[today.isoformat()].toolTip()

            question_id = store.save_question(dict(stem="1 + 1 = ?", subject="数学", answer="2"))
            # SQLite converts local midday to UTC, exercising the same date conversion as the app.
            with store._connection() as db:
                for offset, results in (
                    (90, ["correct"]), (89, ["correct"]), (8, ["skipped"]),
                    (0, ["correct", "incorrect", "skipped"]), (-1, ["correct"]),
                ):
                    day = today - timedelta(days=offset)
                    for result in results:
                        db.execute(
                            """INSERT INTO practice_attempts
                               (question_id, result, mastery, answered_at)
                               VALUES (?, ?, 'unsure', datetime(?, 'utc'))""",
                            (question_id, result, f"{day.isoformat()} 12:00:00"),
                        )
            statistics = store.learning_statistics()
            assert sum(row["attempts"] for row in statistics["daily"]) == 5
            assert len(statistics["daily"]) == 3
            history.refresh()
            assert "5 次记录 · 学习 3 天" in history.heatmap.summary.text()
            assert (today - timedelta(days=89)).isoformat() in history.heatmap.cells
            assert (today - timedelta(days=90)).isoformat() not in history.heatmap.cells
            tooltip = history.heatmap.cells[today.isoformat()].toolTip()
            assert "记录数：3" in tooltip and "跳过：1" in tooltip and "正确率：50%" in tooltip
            assert "正确率：—" in history.heatmap.cells[(today - timedelta(days=8)).isoformat()].toolTip()
            for width, height in ((700, 560), (900, 560), (1040, 680)):
                history.resize(width, height)
                history.show()
                app.processEvents()
                assert history.width() == width
                assert history.heatmap.rect().contains(history.heatmap.calendar.geometry())
                assert all(cell.isVisible() for cell in history.heatmap.cells.values())

            if len(sys.argv) > 1:
                destination = Path(sys.argv[1])
                destination.mkdir(parents=True, exist_ok=True)
                history.grab().save(str(destination / "statistics-real-fixture.png"))
                # A clearly named demonstration preview covers every intensity and month boundary.
                rows = []
                for offset in range(90):
                    count = (0, 1, 3, 7, 12, 24)[(offset * 7 + offset // 4) % 6]
                    correct = count * 3 // 4
                    rows.append(dict(day=(today - timedelta(days=offset)).isoformat(),
                                     attempts=count, correct=correct, incorrect=count - correct))
                history.heatmap.set_daily(rows)
                app.processEvents()
                history.heatmap.grab().save(str(destination / "heatmap-demo.png"))
            history.close()
    print("Learning heatmap: empty state, local 90-day boundaries, skipped accuracy and layouts OK.")


if __name__ == "__main__":
    check()
