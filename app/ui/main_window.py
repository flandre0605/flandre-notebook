import random
import sqlite3
import tempfile
from html import escape
from pathlib import Path
import zipfile

from PySide6.QtCore import QRect, QSettings, QSignalBlocker, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.database import store
from app.services import backup, attachments
from app.ui.attachments_dialog import AttachmentsDialog
from app.ui.history_dialog import HistoryDialog
from app.ui.motion import AnimatedButton, ContentFade
from app.ui.mini_practice_window import MiniPracticeWindow
from app.ui.image_recognition_dialog import ImageRecognitionDialog
from app.ui.practice_dialog import PracticeDialog, PracticeSetupDialog
from app.ui.profiles_dialog import ProfilesDialog
from app.ui.screenshot import GlobalScreenshotHotkey, ScreenshotOverlay
from app.ui.theme import ACCENT, MUTED, STYLE, TEXT
from app.ui.vocabulary_page import VocabularyPage


def _line_icon(path, color=MUTED):
    pixmap = QPixmap()
    pixmap.loadFromData((
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.7" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    ).encode())
    return QIcon(pixmap)


class QuestionRowDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        title, _, metadata = str(index.data() or "").partition("\n")
        styled.text = ""
        styled.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        content = styled.rect.adjusted(12, 8, -12, -8)
        painter.save()
        painter.setFont(styled.font)
        painter.setPen(QColor("#913455" if selected else TEXT))
        painter.drawText(
            QRect(content.left(), content.top(), content.width(), 25),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(styled.font).elidedText(title, Qt.TextElideMode.ElideRight, content.width()),
        )
        small = QFont(styled.font)
        small.setPointSizeF(max(8, small.pointSizeF() - 1))
        painter.setFont(small)
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRect(content.left(), content.top() + 26, content.width(), content.height() - 26),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(small).elidedText(metadata, Qt.TextElideMode.ElideRight, content.width()),
        )
        painter.restore()


class QuestionDialog(QDialog):
    def __init__(self, question=None, parent=None, on_save=None):
        super().__init__(parent)
        self.on_save = on_save
        self.setWindowTitle("编辑题目" if question else "新增题目")
        self.resize(600, 560)
        self.setStyleSheet(STYLE)

        self.stem = QPlainTextEdit()
        self.stem.setMinimumHeight(105)
        self.stem.setPlaceholderText("输入题干")
        self.subject = QLineEdit()
        self.subject.setMinimumHeight(38)
        self.question_type = QLineEdit()
        self.question_type.setMinimumHeight(38)
        self.answer = QPlainTextEdit()
        self.answer.setMinimumHeight(65)
        self.answer.setPlaceholderText("标准答案；多个可接受答案用 | 分隔")
        self.explanation = QPlainTextEdit()
        self.explanation.setMinimumHeight(85)
        self.is_wrong = QCheckBox("标记为错题")
        self.validation_status = QLabel()
        self.validation_status.setStyleSheet("color:#b84d58;font-size:12px;")

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.addRow("题干 *", self.stem)
        form.addRow("学科", self.subject)
        form.addRow("题型", self.question_type)
        form.addRow("答案", self.answer)
        form.addRow("解析", self.explanation)
        form.addRow("", self.is_wrong)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存题目")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("返回题库")
        buttons.accepted.connect(self._save_if_valid)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(18)
        layout.addLayout(form)
        layout.addWidget(self.validation_status)
        layout.addWidget(buttons)

        if question:
            self.stem.setPlainText(question["stem"])
            self.subject.setText(question["subject"])
            self.question_type.setText(question["question_type"])
            self.answer.setPlainText(question["answer"])
            self.explanation.setPlainText(question["explanation"])
            self.is_wrong.setChecked(bool(question["is_wrong"]))

    def _save_if_valid(self):
        if not self.stem.toPlainText().strip():
            self.validation_status.setText("请先输入题干。")
            return
        self.validation_status.clear()
        if self.on_save:
            try:
                if not self.on_save(self.values()):
                    self.validation_status.setText("题目未保存，请检查输入后重试。")
                    return
            except Exception as error:
                self.validation_status.setText(f"保存失败：{error}")
                return
        self.accept()

    def values(self) -> dict[str, str | int]:
        return {
            "stem": self.stem.toPlainText(),
            "subject": self.subject.text(),
            "question_type": self.question_type.text(),
            "answer": self.answer.toPlainText(),
            "explanation": self.explanation.toPlainText(),
            "is_wrong": int(self.is_wrong.isChecked()),
        }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI 错题本")
        self.resize(1280, 820)
        self.setMinimumSize(1040, 680)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self._motion = ContentFade(self)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(188)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 20, 12, 16)
        sidebar_layout.setSpacing(7)

        brand_row = QHBoxLayout()
        brand_mark = QLabel()
        brand_mark.setObjectName("appBrandIcon")
        brand_mark.setPixmap(QPixmap(str(Path(__file__).resolve().parents[2] / "assets" / "flandre_icon.png")).scaled(
            42, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(42, 42)
        brand_text = QVBoxLayout()
        brand_title = QLabel("AI 错题本")
        brand_title.setObjectName("brandTitle")
        brand_caption = QLabel("收集 · 整理 · 复习")
        brand_caption.setObjectName("muted")
        brand_text.addWidget(brand_title)
        brand_text.addWidget(brand_caption)
        brand_row.addWidget(brand_mark)
        brand_row.addLayout(brand_text)
        brand_row.addStretch()
        sidebar_layout.addLayout(brand_row)
        sidebar_layout.addSpacing(20)

        section_label = QLabel("学习空间")
        section_label.setObjectName("sectionCaption")
        sidebar_layout.addWidget(section_label)
        self._navigation_buttons = []

        def add_nav(text, callback, icon_path, page_key=None, active=False, utility=False):
            button = AnimatedButton(text)
            button.setIcon(_line_icon(icon_path))
            button.setIconSize(QSize(18, 18))
            button.setObjectName(
                "navButtonActive" if active else "navUtility" if utility else "navButton"
            )
            button.setMinimumHeight(43)
            button.clicked.connect(callback)
            sidebar_layout.addWidget(button)
            if page_key:
                self._navigation_buttons.append((button, page_key))
            return button

        recognition_icon = "M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"
        add_nav("我的题库", self.show_library, "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z", page_key="library", active=True)
        add_nav("开始练习", self.start_practice, "M7 4l13 8-13 8z", page_key="practice")
        add_nav("练习记录", self.show_history, "M21 12a9 9 0 1 1-18 0 9 9 0 1 1 18 0 M12 7v5l3 2", page_key="history")
        add_nav("英语背单词", self.show_vocabulary, "M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3z M12 6v16 M6 9h3 M15 9h3", page_key="vocabulary")
        sidebar_layout.addSpacing(18)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("separator")
        divider.setFixedHeight(1)
        sidebar_layout.addWidget(divider)
        sidebar_layout.addSpacing(8)
        section_label = QLabel("管理")
        section_label.setObjectName("sectionCaption")
        sidebar_layout.addWidget(section_label)
        add_nav("设置", self.manage_profiles, "M3 6h18 M3 12h18 M3 18h18 M8 3v6 M16 9v6 M8 15v6", page_key="settings", utility=True)
        add_nav("备份数据", self.create_backup, "M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5", utility=True)
        add_nav("恢复备份", self.restore_backup, "M3 10a9 9 0 1 1 1 8 M3 4v6h6", utility=True)
        sidebar_layout.addStretch()

        local_badge = QFrame()
        local_layout = QVBoxLayout(local_badge)
        local_layout.setContentsMargins(10, 10, 10, 0)
        local_title = QLabel("●  本地空间")
        local_title.setStyleSheet("color:#31815d;font-size:11px;font-weight:700;")
        local_caption = QLabel("题库数据保存在此设备")
        local_caption.setObjectName("muted")
        local_layout.addWidget(local_title)
        local_layout.addWidget(local_caption)
        sidebar_layout.addWidget(local_badge)

        title = QLabel("我的题库")
        title.setObjectName("pageTitle")
        title.setStyleSheet("font-size:22px;")
        subtitle = QLabel("收录题目，整理思路，安排下一次复习")
        subtitle.setObjectName("pageSubtitle")
        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        self.add_button = AnimatedButton("＋  新增题目")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setMinimumHeight(34)
        self.recognize_button = AnimatedButton("截图识题")
        self.recognize_button.setIcon(_line_icon(recognition_icon, ACCENT))
        self.recognize_button.setObjectName("softButton")
        self.recognize_button.setMinimumHeight(34)
        self.add_button.clicked.connect(self.add_question)
        self.recognize_button.clicked.connect(self.capture_screenshot)
        page_header = QHBoxLayout()
        page_header.addLayout(title_block)
        page_header.addStretch()
        page_header.addWidget(self.recognize_button)
        page_header.addWidget(self.add_button)

        self.stat_values = {}
        stats = QHBoxLayout()
        stats.setSpacing(8)
        for key, caption in (
            ("total", "全部题目"),
            ("wrong", "错题"),
            ("due", "待复习"),
        ):
            if key != "total":
                separator = QLabel("  /  ")
                separator.setObjectName("muted")
                stats.addWidget(separator)
            value = QLabel("0")
            value.setObjectName("statValue")
            label = QLabel(caption)
            label.setObjectName("cardCaption")
            stats.addWidget(label)
            stats.addWidget(value)
            self.stat_values[key] = value
        stats.addStretch()

        self.search = QLineEdit()
        self.search.setMinimumHeight(34)
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("搜索题干关键词…")

        self.subject_filter = QComboBox()
        self.subject_filter.setMinimumWidth(100)
        self.type_filter = QComboBox()
        self.type_filter.setMinimumWidth(100)
        self.state_filter = QComboBox()
        self.state_filter.setMinimumWidth(110)
        for label, value in (
            ("全部状态", "all"),
            ("错题", "wrong"),
            ("未练习", "unreviewed"),
            ("已掌握", "mastered"),
            ("还不熟", "unsure"),
            ("不会", "unknown"),
        ):
            self.state_filter.addItem(label, value)

        self.attach_button = AnimatedButton("图片附件")
        self.edit_button = AnimatedButton("编辑题目")
        self.edit_button.setObjectName("softButton")
        self.delete_button = AnimatedButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.attach_button.clicked.connect(self.manage_attachments)
        self.edit_button.clicked.connect(self.edit_question)
        self.delete_button.clicked.connect(self.delete_question)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        filters.addWidget(self.subject_filter, 1)
        filters.addWidget(self.type_filter, 1)
        filters.addWidget(self.state_filter, 1)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["题目", "状态"])
        self.table.setItemDelegateForColumn(0, QuestionRowDelegate(self.table))
        self.table.horizontalHeaderItem(0).setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(68)
        header = self.table.horizontalHeader()
        header.setFixedHeight(36)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 76)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_question())
        self.table.selectionModel().selectionChanged.connect(self._update_actions)
        self.search.textChanged.connect(self.refresh)
        self.subject_filter.currentIndexChanged.connect(self.refresh)
        self.type_filter.currentIndexChanged.connect(self.refresh)
        self.state_filter.currentIndexChanged.connect(self.refresh)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("font-size: 13px; line-height: 1.5;")
        self.empty_title = QLabel("从第一道题开始")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setObjectName("emptyTitle")
        self.empty_action = AnimatedButton("＋  新增题目")
        self.empty_action.setObjectName("primaryButton")
        self.empty_action.clicked.connect(self._empty_action)
        empty_card = QFrame()
        empty_card.setStyleSheet("background:white;")
        empty_layout = QVBoxLayout(empty_card)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_label)
        empty_layout.addWidget(self.empty_action, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)

        self.content = QStackedWidget()
        self.content.addWidget(empty_card)
        self.content.addWidget(self.table)

        list_header = QHBoxLayout()
        list_title = QLabel("题目列表")
        list_title.setObjectName("sectionTitle")
        self.result_count = QLabel("共 0 道题")
        self.result_count.setObjectName("resultCount")
        list_header.addWidget(list_title)
        list_header.addStretch()
        list_header.addWidget(self.result_count)

        library_panel = QFrame()
        library_panel.setObjectName("libraryPanel")
        library_panel.setMinimumWidth(360)
        list_section = QVBoxLayout(library_panel)
        list_section.setContentsMargins(18, 18, 18, 12)
        list_section.setSpacing(12)
        list_section.addWidget(self.search)
        list_section.addLayout(filters)
        list_section.addLayout(list_header)
        list_section.addWidget(self.content, 1)
        list_hint = QLabel("双击编辑题目 · 拖入图片可开始识题")
        list_hint.setObjectName("muted")
        list_section.addWidget(list_hint)

        detail_panel = QFrame()
        detail_panel.setObjectName("detailPanel")
        detail_panel.setMinimumWidth(300)
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(20, 20, 20, 12)
        detail_layout.setSpacing(12)
        self.preview_title = QLabel("题目详情")
        self.preview_title.setObjectName("detailTitle")
        self.preview_meta = QLabel("选择一道题目，查看完整内容")
        self.preview_meta.setObjectName("muted")
        self.preview_meta.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_meta.setWordWrap(True)
        self.preview_tabs = QTabWidget()
        self.preview_stem = QTextBrowser()
        self.preview_solution = QTextBrowser()
        for browser in (self.preview_stem, self.preview_solution):
            browser.setObjectName("previewText")
            browser.setOpenLinks(False)
        self.preview_tabs.addTab(self.preview_stem, "题目内容")
        self.preview_tabs.addTab(self.preview_solution, "答案与解析")
        self.preview_tabs.currentChanged.connect(
            lambda _index: self._motion.play(self.preview_tabs.currentWidget())
        )
        self._preview_id = None
        detail_actions = QHBoxLayout()
        detail_actions.addWidget(self.edit_button)
        detail_actions.addWidget(self.attach_button)
        detail_actions.addStretch()
        detail_actions.addWidget(self.delete_button)
        detail_layout.addWidget(self.preview_title)
        detail_layout.addWidget(self.preview_meta)
        detail_layout.addWidget(self.preview_tabs, 1)
        detail_layout.addLayout(detail_actions)

        self.library_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.library_splitter.setHandleWidth(5)
        self.library_splitter.setChildrenCollapsible(False)
        self.library_splitter.addWidget(library_panel)
        self.library_splitter.addWidget(detail_panel)
        self.library_splitter.setStretchFactor(0, 3)
        self.library_splitter.setStretchFactor(1, 2)
        self.library_splitter.setSizes([620, 430])

        workspace_header = QFrame()
        workspace_header.setObjectName("workspaceHeader")
        header_layout = QVBoxLayout(workspace_header)
        header_layout.setContentsMargins(22, 18, 22, 14)
        header_layout.setSpacing(12)
        header_layout.addLayout(page_header)
        header_layout.addLayout(stats)

        central = QWidget()
        central.setObjectName("centralPage")
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(sidebar)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(workspace_header)
        layout.addWidget(self.library_splitter, 1)
        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(page)
        self._pages = {"library": page}
        self._page_containers = {"library": page}
        self._page_dialogs = {}
        self._page_nav_keys = {"library": "library"}
        shell.addWidget(self.page_stack, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("本地模式 · 题库数据保存在此设备")
        self._screenshot_overlays = []
        self._profiles_dialog = None
        self._practice_setup = None
        self._mini_practice_window = None
        self._recognition_dialogs = []
        self.screenshot_shortcut = str(
            QSettings().value("shortcuts/screenshot", "Ctrl+Alt+S")
        )
        self._screenshot_hotkey = GlobalScreenshotHotkey(
            self, self.capture_screenshot, self.screenshot_shortcut
        )
        self._update_screenshot_status()
        self._refresh_filter_options()
        self.refresh()

    def capture_screenshot(self):
        if self._screenshot_overlays:
            return
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        screenshot = screen.grabWindow(0) if screen else None
        if screenshot is None or screenshot.isNull():
            QMessageBox.warning(self, "截图失败", "无法读取当前屏幕，请改用图片选择或粘贴。")
            return
        overlay = ScreenshotOverlay(screen, screenshot)
        overlay.captured.connect(self._screenshot_captured)
        overlay.cancelled.connect(self._cancel_screenshot)
        self._screenshot_overlays.append(overlay)
        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        overlay.setFocus()

    def _cancel_screenshot(self):
        for overlay in self._screenshot_overlays:
            overlay.close()
        self._screenshot_overlays.clear()

    def _screenshot_captured(self, image):
        self._cancel_screenshot()
        directory = tempfile.TemporaryDirectory(prefix="mistake-notebook-capture-")
        image_path = Path(directory.name) / "question.png"
        if not image.save(str(image_path), "PNG"):
            directory.cleanup()
            QMessageBox.warning(self, "截图失败", "无法保存截图，请重试或改用图片选择。")
            return
        del image
        dialog = self.start_image_recognition(image_path, auto_recognize=True)
        dialog._clipboard_temp_dirs.append(directory)

    def set_screenshot_shortcut(self, shortcut):
        self._screenshot_hotkey.close()
        self.screenshot_shortcut = shortcut
        self._screenshot_hotkey = GlobalScreenshotHotkey(self, self.capture_screenshot, shortcut)
        self._update_screenshot_status()
        return self._screenshot_hotkey.registered

    def _update_screenshot_status(self):
        suffix = "" if self._screenshot_hotkey.registered else "（仅应用打开时可用）"
        self.statusBar().showMessage(
            f"本地模式 · 题库数据保存在此设备    |    截图识题：{self.screenshot_shortcut}{suffix}"
        )

    def _show_page(self, key):
        page = self._pages.get(key)
        if page is None:
            return
        if key != "vocabulary" and "vocabulary" in self._pages:
            self.vocabulary_page.speech.stop()
        self.restore_mini_practice()
        changed = self.page_stack.currentWidget() != page
        self.page_stack.setCurrentWidget(page)
        dialog = self._page_dialogs.get(key)
        if dialog is not None:
            dialog.show()
        active_key = self._page_nav_keys.get(key, key)
        for button, page_key in self._navigation_buttons:
            active = page_key == active_key
            button.setObjectName("navButtonActive" if active else "navUtility" if page_key == "settings" else "navButton")
            button.style().unpolish(button)
            button.style().polish(button)
        if changed:
            self._motion.play(page)

    def _embed_dialog_page(
        self, key, dialog, title, back_key="library", nav_key=None, persistent=False
    ):
        if key in self._pages and key != "library":
            self._discard_page(key)
        dialog.setWindowFlags(Qt.WindowType.Widget)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        header = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        back_button = AnimatedButton("← 返回")
        back_button.clicked.connect(
            lambda: self._show_page(back_key) if persistent else dialog.reject()
        )
        header.addWidget(heading)
        header.addStretch()
        if key == "practice_run":
            self.mini_practice_button = AnimatedButton("小窗练习")
            self.mini_practice_button.setObjectName("softButton")
            self.mini_practice_button.clicked.connect(self.enter_mini_practice)
            header.addWidget(self.mini_practice_button)
        header.addWidget(back_button)
        layout.addLayout(header)
        layout.addWidget(dialog, 1)
        self.page_stack.addWidget(container)
        self._pages[key] = container
        self._page_containers[key] = container
        self._page_dialogs[key] = dialog
        self._page_nav_keys[key] = nav_key or self._page_nav_keys.get(back_key, back_key)
        return container

    def _leave_dialog_page(self, key, back_key="library", persistent=False):
        self._show_page(back_key)
        if not persistent:
            self._discard_page(key)

    def _discard_page(self, key):
        container = self._page_containers.pop(key, None)
        self._pages.pop(key, None)
        self._page_dialogs.pop(key, None)
        self._page_nav_keys.pop(key, None)
        if container is not None:
            self.page_stack.removeWidget(container)
            container.deleteLater()

    def show_library(self):
        self._refresh_filter_options()
        self.refresh()
        self._show_page("library")

    def closeEvent(self, event):
        if "vocabulary" in self._pages:
            self.vocabulary_page.cancel_translation()
            self.vocabulary_page.speech.stop()
        self.restore_mini_practice(show_main=False)
        self._motion.finish()
        self._cancel_screenshot()
        self._screenshot_hotkey.close()
        for dialog in list(self._recognition_dialogs):
            dialog.reject()
        super().closeEvent(event)

    def refresh(self):
        try:
            rows = store.list_questions(
                self.search.text().strip(),
                self.subject_filter.currentData(),
                self.type_filter.currentData(),
                self.state_filter.currentData(),
            )
            summary = store.question_summary()
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法读取本地题库：\n{error}")
            return
        for key, value in zip(("total", "wrong", "due"), summary):
            self.stat_values[key].setText(f"{value:,}")
        filtered = bool(
            self.search.text().strip()
            or self.subject_filter.currentData()
            or self.type_filter.currentData()
            or self.state_filter.currentData() != "all"
        )
        self.result_count.setText(f"找到 {len(rows)} 道题" if filtered else f"共 {len(rows)} 道题")
        selected_id = self._selected_id()
        with QSignalBlocker(self.table.selectionModel()):
            self.table.setRowCount(0)
            self.table.setRowCount(len(rows))
            selected_row = 0
            for row_index, question in enumerate(rows):
                metadata = " · ".join((question["subject"] or "未分类", question["question_type"] or "未设题型"))
                values = [
                    " ".join(question["stem"].split()) + "\n" + metadata,
                    "● 错题" if question["is_wrong"] else "普通",
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(question["stem"] if column == 0 else value)
                    if column == 1 and question["is_wrong"]:
                        item.setForeground(QColor("#b34d5b"))
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, question["id"])
                    self.table.setItem(row_index, column, item)
                if question["id"] == selected_id:
                    selected_row = row_index
            if rows:
                self.table.selectRow(selected_row)
        if rows:
            self.content.setCurrentIndex(1)
        else:
            self.empty_title.setText("没有匹配的题目" if filtered else "从第一道题开始")
            self.empty_label.setText(
                "调整关键词或筛选条件，或者一键清除筛选。"
                if filtered
                else "题目会保存在本机，之后可随时搜索、练习和复习。"
            )
            self.empty_action.setText("清除筛选" if filtered else "＋  新增题目")
            self.empty_action.setObjectName("softButton" if filtered else "primaryButton")
            self.empty_action.style().unpolish(self.empty_action)
            self.empty_action.style().polish(self.empty_action)
            self.content.setCurrentIndex(0)
        self._update_actions()

    def _empty_action(self):
        filtered = bool(
            self.search.text().strip()
            or self.subject_filter.currentData()
            or self.type_filter.currentData()
            or self.state_filter.currentData() != "all"
        )
        if not filtered:
            self.add_question()
            return
        self.search.clear()
        self.subject_filter.setCurrentIndex(0)
        self.type_filter.setCurrentIndex(0)
        self.state_filter.setCurrentIndex(0)

    def _update_actions(self, *_):
        question_id = self._selected_id()
        has_selection = question_id is not None
        self.attach_button.setEnabled(has_selection)
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self._update_preview(question_id)

    def _update_preview(self, question_id):
        changed = question_id != self._preview_id
        question = None
        error_message = "在左侧选择题目，即可在这里阅读题干。"
        if question_id is not None:
            try:
                question = store.get_question(question_id)
            except sqlite3.Error as error:
                error_message = f"无法读取题目，请稍后重试。\n{error}"
        if question_id != self._preview_id or question is None:
            self.preview_tabs.setCurrentIndex(0)
        self._preview_id = question_id
        self.preview_tabs.setTabEnabled(1, question is not None)
        if question is None:
            self.preview_title.setText("题目详情")
            self.preview_meta.setText("选择一道题目，查看完整内容")
            self.preview_stem.setPlainText(error_message)
            self.preview_solution.clear()
            return
        self.preview_title.setText(f"题目 #{question_id}")
        self.preview_meta.setText(" · ".join((
            question["subject"] or "未分类",
            question["question_type"] or "未设题型",
            "已标记为错题" if question["is_wrong"] else "普通题目",
        )))
        self.preview_stem.setPlainText(question["stem"])
        answer = escape(question["answer"] or "暂未填写参考答案").replace("\n", "<br>")
        explanation = escape(question["explanation"] or "暂未填写解析").replace("\n", "<br>")
        self.preview_solution.setHtml(
            f"<h3>参考答案</h3><p>{answer}</p><br><h3>解析</h3><p>{explanation}</p>"
        )
        if changed:
            self._motion.play(self.preview_tabs.currentWidget())

    def _refresh_filter_options(self):
        selected_subject = self.subject_filter.currentData()
        selected_type = self.type_filter.currentData()
        subjects, types = store.question_filter_options()
        for combo, label, values, selected in (
            (self.subject_filter, "全部学科", subjects, selected_subject),
            (self.type_filter, "全部题型", types, selected_type),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(label, "")
            for value in values:
                combo.addItem(value, value)
            index = combo.findData(selected)
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def add_question(self):
        if "question" in self._pages:
            self._show_page("question")
            return
        dialog = QuestionDialog(parent=self, on_save=self._save_new_question)
        self._embed_dialog_page("question", dialog, "新增题目")
        dialog.accepted.connect(lambda: self._leave_dialog_page("question"))
        dialog.rejected.connect(lambda: self._leave_dialog_page("question"))
        self._show_page("question")

    def _save_new_question(self, values):
        store.save_question(values)
        self._refresh_filter_options()
        self.refresh()
        return True

    def edit_question(self):
        if "question" in self._pages:
            self._show_page("question")
            return
        question_id = self._selected_id()
        if question_id is None:
            return
        question = store.get_question(question_id)
        if question is None:
            self.refresh()
            return
        dialog = QuestionDialog(
            question,
            self,
            on_save=lambda values: self._save_existing_question(question_id, values),
        )
        self._embed_dialog_page("question", dialog, "编辑题目")
        dialog.accepted.connect(lambda: self._leave_dialog_page("question"))
        dialog.rejected.connect(lambda: self._leave_dialog_page("question"))
        self._show_page("question")

    def _save_existing_question(self, question_id, values):
        store.save_question(values, question_id)
        self._refresh_filter_options()
        self.refresh()
        return True

    def delete_question(self):
        question_id = self._selected_id()
        if question_id is None:
            return
        answer = QMessageBox.question(self, "删除题目", "确定删除选中的题目吗？")
        if answer == QMessageBox.StandardButton.Yes:
            try:
                orphaned = attachments.delete_question_images(question_id)
            except sqlite3.Error as error:
                QMessageBox.critical(self, "删除失败", f"题目没有删除：\n{error}")
                return
            self._refresh_filter_options()
            self.refresh()
            if orphaned:
                QMessageBox.warning(
                    self,
                    "题目已删除",
                    "部分图片文件无法清理，可稍后手动删除：\n" + "\n".join(orphaned),
                )

    def manage_attachments(self):
        question_id = self._selected_id()
        if question_id is None:
            return
        self._show_attachments(question_id, "library")

    def _show_attachments(self, question_id, back_key):
        dialog = AttachmentsDialog(question_id, self)
        self._embed_dialog_page(
            "attachments", dialog, "题目图片", back_key=back_key,
            nav_key=self._page_nav_keys.get(back_key, back_key),
        )
        dialog.accepted.connect(lambda: self._leave_dialog_page("attachments", back_key))
        dialog.rejected.connect(lambda: self._leave_dialog_page("attachments", back_key))
        self._show_page("attachments")

    def start_image_recognition(self, image_path=None, auto_recognize=False):
        self.restore_mini_practice()
        if self.isMinimized():
            self.showNormal()
        if "vocabulary" in self._pages:
            self.vocabulary_page.speech.stop()
        if image_path is None:
            for current in reversed(self._recognition_dialogs):
                if current.isVisible():
                    current.raise_()
                    current.activateWindow()
                    return current
        dialog = ImageRecognitionDialog(image_path, self, auto_recognize=auto_recognize)
        self._recognition_dialogs.append(dialog)
        dialog.accepted.connect(self._refresh_filter_options)
        dialog.accepted.connect(self.refresh)
        dialog.finished.connect(lambda _result: self._cleanup_finished_recognition(dialog))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _cleanup_finished_recognition(self, dialog):
        if dialog in self._recognition_dialogs:
            self._recognition_dialogs.remove(dialog)
        for directory in dialog._clipboard_temp_dirs:
            directory.cleanup()
        dialog._clipboard_temp_dirs.clear()
        dialog.deleteLater()

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.start_image_recognition(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()

    def start_practice(self):
        if "practice_run" in self._pages:
            self._show_page("practice_run")
            return
        setup = self._practice_setup
        first_open = setup is None
        if setup is None:
            setup = PracticeSetupDialog(self)
            self._practice_setup = setup
            self._embed_dialog_page(
                "practice_setup", setup, "开始练习", nav_key="practice", persistent=True
            )
            setup.accepted.connect(self._begin_practice)
            setup.rejected.connect(lambda: self._show_page("library"))
        setup.refresh_subjects()
        if first_open:
            setup.subject.setCurrentIndex(max(0, setup.subject.findData(self.subject_filter.currentData())))
        filters = []
        if self.search.text().strip():
            filters.append(f"关键词：{self.search.text().strip()}")
        if self.type_filter.currentData():
            filters.append(f"题型：{self.type_filter.currentText()}")
        if self.state_filter.currentData() != "all":
            filters.append(f"状态：{self.state_filter.currentText()}")
        setup.filter_hint.setText(
            "勾选后额外限制为：" + "；".join(filters)
            if filters else "题库当前没有额外的搜索、题型或状态限制。"
        )
        setup.show()
        self._show_page("practice_setup")

    def _begin_practice(self):
        setup = self._practice_setup
        mode, subject, random_order, use_library_filters = setup.values()
        try:
            questions = store.practice_questions(
                mode,
                search=self.search.text().strip() if use_library_filters else "",
                subject=subject,
                question_type=self.type_filter.currentData() if use_library_filters else "",
                state=self.state_filter.currentData() if use_library_filters else "all",
            )
        except sqlite3.Error as error:
            setup.status.setText(f"无法生成练习题：{error}")
            setup.show()
            return
        if not questions:
            setup.status.setText("所选学科和练习范围内没有题目，请调整条件后重试。")
            setup.show()
            return
        setup.status.clear()
        if random_order:
            random.shuffle(questions)
        dialog = PracticeDialog(questions, self)
        self._embed_dialog_page(
            "practice_run", dialog, "练习中", nav_key="practice"
        )
        dialog.content_changed.connect(lambda: self._motion.play(dialog))
        dialog.images_requested.connect(
            lambda question_id: self._show_attachments(question_id, "practice_run")
        )
        dialog.accepted.connect(lambda: self._leave_dialog_page("practice_run"))
        dialog.rejected.connect(lambda: self._leave_dialog_page("practice_run"))
        self._show_page("practice_run")
        self.refresh()
        if setup.mini_mode.isChecked():
            self.enter_mini_practice()

    def enter_mini_practice(self):
        if self._mini_practice_window is not None:
            self._mini_practice_window.show()
            self._mini_practice_window.raise_()
            return
        practice = self._page_dialogs.get("practice_run")
        if practice is None:
            return
        self._motion.finish()
        self._page_containers["practice_run"].layout().removeWidget(practice)
        mini = MiniPracticeWindow(practice, self)
        self._mini_practice_window = mini
        mini.restore_requested.connect(self.restore_mini_practice)
        available = self.screen().availableGeometry()
        mini.resize(480, min(640, available.height() - 64))
        mini.move(max(available.left(), available.right() - mini.width() - 24), available.top() + 24)
        self.hide()
        mini.show()
        practice.show()
        mini.raise_()
        mini.activateWindow()

    def restore_mini_practice(self, show_main=True):
        mini = self._mini_practice_window
        if mini is None:
            return
        self._motion.finish()
        self._mini_practice_window = None
        practice = mini.take_practice()
        container = self._page_containers["practice_run"]
        practice.setParent(container)
        practice.setWindowFlags(Qt.WindowType.Widget)
        container.layout().addWidget(practice, 1)
        mini.hide()
        mini.deleteLater()
        if show_main:
            self.show()
            self._show_page("practice_run")
            self.raise_()
            self.activateWindow()

    def show_history(self):
        if "history" not in self._pages:
            history = HistoryDialog(self)
            self.history_page = history
            self._embed_dialog_page(
                "history", history, "练习记录", persistent=True
            )
        self.history_page.refresh()
        self._show_page("history")

    def show_vocabulary(self):
        if "vocabulary" not in self._pages:
            self.vocabulary_page = VocabularyPage(self)
            self._embed_dialog_page("vocabulary", self.vocabulary_page, "英语背单词",
                                    nav_key="vocabulary", persistent=True)
            self.vocabulary_page.rejected.connect(lambda: self._show_page("library"))
            self.vocabulary_page.content_changed.connect(
                lambda: self._motion.play(self.vocabulary_page.views.currentWidget())
            )
        self.vocabulary_page.refresh()
        self._show_page("vocabulary")

    def manage_profiles(self):
        if self._profiles_dialog is None:
            self._profiles_dialog = ProfilesDialog(self)
            self._embed_dialog_page(
                "settings", self._profiles_dialog, "设置与模型服务", nav_key="settings", persistent=True
            )
        self._show_page("settings")

    def create_backup(self):
        default_path = store.DATA_DIR / "错题本备份.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, "备份题库和图片", str(default_path), "错题本备份 (*.zip)"
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        destination = Path(path)
        if destination.exists() and QMessageBox.question(
            self, "覆盖备份", f"文件已存在，确定覆盖吗？\n{destination}"
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            backup.create_backup(destination)
        except (OSError, sqlite3.Error, ValueError) as error:
            QMessageBox.critical(self, "备份失败", str(error))
            return
        QMessageBox.information(self, "备份完成", f"题库和图片已备份到：\n{destination}")

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择题库备份", str(store.DATA_DIR), "错题本备份 (*.zip)"
        )
        if not path:
            return
        answer = QMessageBox.warning(
            self,
            "确认恢复",
            "恢复会替换当前题库和图片。应用会先在 data 目录保存一份当前数据备份。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            recovery = backup.restore_backup(path)
        except (OSError, sqlite3.Error, ValueError, zipfile.BadZipFile) as error:
            QMessageBox.critical(self, "恢复失败", str(error))
            return
        self.refresh()
        if "vocabulary" in self._pages:
            self.vocabulary_page.reset()
        QMessageBox.information(self, "恢复完成", f"当前数据已恢复。恢复前备份保存在：\n{recovery}")
