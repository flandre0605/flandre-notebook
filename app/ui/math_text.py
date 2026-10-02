"""Offline formula previews; source text remains the editable and stored value."""
import base64
from functools import lru_cache
from html import escape
from math import ceil
import re

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QTabWidget, QTextBrowser

from app.ui.theme import TEXT


MATH = re.compile(
    r"(?<!\\)(?:\$\$(?P<block>.+?)(?<!\\)\$\$|"
    r"\\\[(?P<bracket>.+?)\\\]|\\\((?P<paren>.+?)\\\)|"
    r"\$(?P<inline>[^$\n]+?)(?<!\\)\$)", re.DOTALL
)


@lru_cache(maxsize=32)
def _formula_image(expression, block):
    if len(expression) > 2000 or re.search(r"[\u3400-\u9fff]", expression):
        raise ValueError("公式过长或含字体不支持的文字")
    import ziamath  # Load the small renderer only when a formula is encountered.

    # Qt's SVG reader needs SVG 1.x paths instead of SVG 2 symbol references.
    ziamath.config.svg2 = False
    equation = ziamath.Latex(expression, size=20, inline=not block, color=TEXT)
    if re.search(r"\\[A-Za-z]+", equation.mathmlstr()):
        raise ValueError("含不支持的公式命令")
    renderer = QSvgRenderer(equation.svg().encode("utf-8"))
    bounds = renderer.viewBoxF()
    width, height = ceil(bounds.width()), ceil(bounds.height())
    if not renderer.isValid() or width <= 0 or height <= 0 or width * height > 1_000_000:
        raise ValueError("公式无法预览或尺寸过大")
    image = QImage(width * 2, height * 2, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("公式图片生成失败")
    return width, height, base64.b64encode(bytes(buffer.data())).decode("ascii")


def math_html(text, max_width=640):
    """Escape all user text; only locally generated formula images become HTML."""
    parts, end, failed = [], 0, False
    for index, match in enumerate(MATH.finditer(text)):
        parts.append(escape(text[end:match.start()]).replace("\n", "<br>"))
        expression = next(value for value in match.groupdict().values() if value is not None)
        block = match.group("block") is not None or match.group("bracket") is not None
        try:
            if index >= 64:
                raise ValueError("单段公式过多")
            width, height, data = _formula_image(expression.strip(), block)
            scale = min(1.0, max(120, max_width) / width)
            image = (f'<img src="data:image/png;base64,{data}" width="{width * scale:.1f}" '
                     f'height="{height * scale:.1f}" alt="{escape(match.group(), quote=True)}" '
                     'style="vertical-align:middle;">')
            parts.append(f"<br>{image}<br>" if block else image)
        except Exception:
            # Unsupported math stays visible and editable instead of disappearing.
            parts.append(escape(match.group()).replace("\n", "<br>"))
            failed = True
        end = match.end()
    parts.append(escape(text[end:]).replace("\n", "<br>"))
    if failed:
        parts.append('<br><small style="color:#b84d58;">部分公式暂无法预览，已保留原文，可切换编辑并对照原图。</small>')
    return "".join(parts)


class MathBrowser(QTextBrowser):
    def __init__(self):
        super().__init__()
        self._source = ""
        self._sections = None
        self.setObjectName("mathPreview")
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)

    def setPlainText(self, text):
        self._source = text
        self._sections = None
        self._render()

    def setSections(self, sections):
        self._sections = sections
        self._source = "\n\n".join(f"{title}\n{body}" for title, body in sections)
        self._render()

    def _render(self):
        self.setAccessibleDescription(self._source)
        width = self.viewport().width() - 20
        html = ("<br>".join(f"<h3>{escape(title)}</h3>{math_html(body, width)}"
                           for title, body in self._sections)
                if self._sections is not None else math_html(self._source, width))
        self.setHtml(html)

    def clear(self):
        self.setPlainText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            position = self.verticalScrollBar().value()
            self._render()
            self.verticalScrollBar().setValue(position)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.addAction("复制原文（含公式）", lambda: QApplication.clipboard().setText(self._source))
        menu.exec(event.globalPos())
        menu.deleteLater()


class MathLabel(QLabel):
    def __init__(self):
        super().__init__()
        self._source = ""
        self.setTextFormat(Qt.TextFormat.RichText)

    def setText(self, text):
        self._source = text
        self.setAccessibleDescription(text)
        super().setText(math_html(text, self.width() - 48))

    def text(self):
        return self._source

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.setText(self._source)


class MathEditor(QTabWidget):
    def __init__(self):
        super().__init__()
        self.source = QPlainTextEdit()
        self.preview = MathBrowser()
        self.addTab(self.preview, "预览")
        self.addTab(self.source, "编辑")
        self.setCurrentIndex(1)
        self.currentChanged.connect(self._preview)

    def _preview(self, index):
        if index == 0:
            self.preview.setPlainText(self.toPlainText())

    def setPlainText(self, text):
        self.source.setPlainText(text)
        self.setCurrentIndex(0 if MATH.search(text) else 1)
        self._preview(self.currentIndex())

    def toPlainText(self):
        return self.source.toPlainText()

    def setPlaceholderText(self, text):
        self.source.setPlaceholderText(text)
