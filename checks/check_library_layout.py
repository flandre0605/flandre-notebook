"""Run with .venv/Scripts/python.exe checks/check_library_layout.py [preview.png]."""

import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QLabel

from app.database import store
from app.ui.main_window import MainWindow


def check(preview_path=None):
    app = QApplication.instance() or QApplication([])
    if sys.platform == "win32":
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyhbd.ttc")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    icon = QIcon(str(Path(__file__).resolve().parents[1] / "assets" / "flandre_icon.ico"))
    for size in (16, 32, 48, 256):
        assert not icon.pixmap(size, size).isNull()
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda: connection(database)), patch(
            "app.ui.main_window.GlobalScreenshotHotkey"
        ):
            for stem, subject, kind, wrong, answer in (
                ("阅读《记承天寺夜游》，概括作者在文中表达的情感。", "语文", "简答题", 1, "赏月的欣喜、贬谪的落寞与自我排解的旷达。"),
                ("Choose the correct form: If I ___ you, I would try again.", "英语", "单选题", 0, "were"),
                ("一个质量为 2 kg 的物体，受到 6 N 的水平合力。求物体的加速度。", "物理", "计算题", 1, "3 m/s²"),
                ("已知函数 f(x) = x² − 4x + 3，求它的零点和最小值。", "数学", "解答题", 1, "零点：1、3；最小值：−1。"),
                ("已知函数 f(x) = x² − 2x − 3。\n\n（1）求函数的零点；\n（2）写出函数的单调区间；\n（3）求函数在区间 [0, 3] 上的最小值。", "数学", "解答题", 1, "（1）−1 和 3；（2）(−∞, 1] 递减，[1, +∞) 递增；（3）−4。"),
            ):
                store.save_question(dict(stem=stem, subject=subject, question_type=kind,
                                         is_wrong=wrong, answer=answer,
                                         explanation="配方：f(x) = (x − 1)² − 4。\n注意区间端点。<提示>"))
            window = MainWindow()
            window.show_library()
            assert not window.findChild(QLabel, "appBrandIcon").pixmap().isNull()
            window.show()
            app.processEvents()
            assert window.table.rowCount() == 5
            assert window.preview_stem.toPlainText() == store.get_question(window._selected_id())["stem"]
            if preview_path:
                assert window.grab().save(str(preview_path))
            window.table.selectRow(1)
            assert window._motion._target is window.preview_stem
            selected_id = window._selected_id()
            window.preview_tabs.setCurrentIndex(1)
            assert window._motion._target is window.preview_solution
            assert "<提示>" in window.preview_solution.toPlainText()
            window.refresh()
            assert window._selected_id() == selected_id
            assert window.preview_tabs.currentIndex() == 1
            window.table.selectRow(2)
            assert window.preview_tabs.currentIndex() == 0
            for width, height in ((1040, 680), (1600, 900)):
                window.resize(width, height)
                app.processEvents()
                assert all(size >= 300 for size in window.library_splitter.sizes())
                for button in (window.edit_button, window.attach_button, window.delete_button):
                    assert button.parentWidget().rect().contains(button.geometry())
                if preview_path and width == 1040:
                    assert window.grab().save(str(preview_path.with_name(preview_path.stem + "-compact.png")))
            window.search.setText("不存在的题目关键词")
            assert window.table.rowCount() == 0
            assert window.content.currentIndex() == 0
            assert window._selected_id() is None
            assert not window.edit_button.isEnabled()
            assert window.preview_solution.toPlainText() == ""
            window.search.clear()
            window.state_filter.setCurrentIndex(window.state_filter.findData("wrong"))
            assert window.table.rowCount() == 4
            for row in store.list_questions():
                store.delete_question(row["id"])
            window.refresh()
            assert window.table.rowCount() == 0
            assert window.stat_values["total"].text() == "0"
            assert not window.preview_tabs.isTabEnabled(1)
            window.close()
    print("Library layout check passed (temporary database only).")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
