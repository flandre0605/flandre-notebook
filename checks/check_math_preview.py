"""Formula preview and lossless editing check; temporary data, no model calls."""
import base64
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

from app.database import store
from app.services.grading import grade_answer
from app.ui.main_window import MainWindow
from app.ui.math_text import MathEditor, _formula_image, math_html


def check(previews=None):
    app = QApplication.instance() or QApplication([])
    for font in ("msyh.ttc", "msyhbd.ttc"):
        QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    expression = r"\lim_{x\to0}\frac{1}{x}\left(\frac{1}{\sin x}-\frac{1}{\tan x}\right)"
    stem = f"计算极限 ${expression}$"
    answer = r"$\frac{1}{2}$"
    assert grade_answer("计算题", answer, "1/2") is None
    assert grade_answer("计算题", answer, answer) is True
    assert grade_answer("填空题", "5", "4") is False
    explanation = (r"原式可化为 $\lim_{x\to0}\frac{1-\cos x}{x\sin x}$。"
                   r"利用 $1-\cos x\sim\frac{x^2}{2}$ 与 $\sin x\sim x$，得到 $\frac{1}{2}$。")
    width, height, data = _formula_image(expression, False)
    image = QImage.fromData(base64.b64decode(data), "PNG")
    assert image.width() == width * 2 and image.height() == height * 2
    # SVG 2 symbol references silently lose glyphs in Qt; catch missing characters.
    ink = sum(image.pixelColor(x, y).alpha() > 0 for x in range(image.width()) for y in range(image.height()))
    assert ink > 2000
    for source in (answer, r"\(\sqrt{x^2+1}\)", r"\[\int_0^1 x\,dx\]", r"$$\sum_{n=1}^3 n$$",
                   r"$\begin{pmatrix}1&2\\3&4\end{pmatrix}$"):
        assert "data:image/png" in math_html(source) and "暂无法预览" not in math_html(source)
    assert "&lt;script&gt;" in math_html("<script>alert(1)</script>")
    assert "<img" not in math_html(r"美元 \$5 和普通文字")
    assert "暂无法预览" in math_html(r"$\unsupportedcommand{x}$")
    with patch("app.ui.math_text._formula_image", side_effect=ImportError):
        assert answer in math_html(answer) and "暂无法预览" in math_html(answer)
    editor = MathEditor()
    editor.setPlainText(stem)
    assert editor.currentWidget() is editor.preview and editor.toPlainText() == stem
    editor.setCurrentIndex(1)
    editor.source.insertPlainText("补充说明 ")
    edited = editor.toPlainText()
    editor.setCurrentIndex(0)
    assert editor.toPlainText() == edited and "data:image/png" in editor.preview.toHtml()
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "questions.db"
        store.initialize(database)
        source = root / "source.png"
        assert image.save(str(source), "PNG")
        with patch.object(store, "_connection", lambda: connection(database)), patch("app.ui.main_window.GlobalScreenshotHotkey"):
            question_id = store.save_question(dict(stem=stem, answer=answer, explanation=explanation,
                                                   subject="数学", question_type="计算题"))
            window = MainWindow()
            window.show_library()
            window.show()
            QTest.qWait(230)
            assert "data:image/png" in window.preview_stem.toHtml()
            assert "data:image/png" in window.preview_solution.toHtml()
            assert store.get_question(question_id)["stem"] == stem
            popup = window.start_image_recognition(source)
            popup._recognized([dict(stem=stem, answer=answer, explanation=explanation, subject="数学", question_type="计算题"),
                               dict(stem="第二道普通题", answer="B")])
            draft = popup.draft_editor
            assert draft.stem.currentWidget() is draft.stem.preview
            assert "data:image/png" in draft.answer.preview.toHtml()
            draft.question_selector.setCurrentIndex(1)
            draft.question_selector.setCurrentIndex(0)
            assert draft.values()[0]["stem"] == stem and draft.values()[0]["answer"] == answer
            popup.resize(980, 600)
            QTest.qWait(230)
            save = draft.buttons.button(QDialogButtonBox.StandardButton.Save)
            assert draft.rect().contains(save.mapTo(draft, save.rect().bottomRight()))
            assert draft.findChild(QScrollArea).verticalScrollBar().maximum() > 0
            if previews:
                previews.mkdir(parents=True, exist_ok=True)
                assert popup.grab().save(str(previews / "math-draft.png"))
                assert window.grab().save(str(previews / "math-library.png"))
            popup.reject()
            window.start_practice()
            window._practice_setup.accept()
            practice = window._page_dialogs["practice_run"]
            assert practice.stem.text() == stem and not practice.solution.isVisible()
            practice.user_answer.setPlainText("1/2")
            practice.submit_answer()
            assert answer in practice.solution.text()
            assert practice.result_choice.isEnabled() and "自评" in practice.judgement.text()
            window.enter_mini_practice()
            mini = window._mini_practice_window
            mini.resize(440, 560)
            QTest.qWait(230)
            assert mini.scroll.horizontalScrollBar().maximum() == 0
            if previews:
                assert mini.grab().save(str(previews / "math-mini.png"))
            window.restore_mini_practice()
            window.close()
    print("PASS: visible formula glyphs, delimiters, fallback, escaped HTML, lossless edits, library/practice/mini and visible draft actions")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
