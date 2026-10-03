from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.question_data import parse_options
from app.ui.math_text import MathEditor
from app.ui.motion import AnimatedButton


class OptionsEditor(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._options = {}
        self.selector = QComboBox()
        self.selector.setMinimumWidth(100)
        self.add_button = AnimatedButton("＋ 添加选项")
        self.remove_button = AnimatedButton("删除此选项")
        self.remove_button.setObjectName("dangerButton")
        self.editor = MathEditor()
        self.editor.setMinimumHeight(120)
        self.editor.setPlaceholderText("填写选项内容，数学公式可切换预览")
        hint = QLabel("标号保留不变；删除选项后请核对标准答案。选择题答案填写标号，如 A 或 AC。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        row = QHBoxLayout()
        row.addWidget(self.selector)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.editor)
        layout.addWidget(hint)
        self.selector.currentIndexChanged.connect(self._load)
        self.editor.source.textChanged.connect(self._edit)
        self.add_button.clicked.connect(self.add_option)
        self.remove_button.clicked.connect(self.remove_option)
        self.set_options({})

    def set_options(self, options, selected=None):
        self._options = parse_options(options, draft=True)
        with QSignalBlocker(self.selector):
            self.selector.clear()
            for label in self._options:
                self.selector.addItem(f"选项 {label}", label)
            self.selector.setCurrentIndex(max(0, self.selector.findData(selected)))
        self._load()

    def _load(self, *_):
        label = self.selector.currentData()
        with QSignalBlocker(self.editor.source):
            self.editor.setPlainText(self._options.get(label, ""))
        self.editor.setEnabled(label is not None)
        self.remove_button.setEnabled(label is not None)
        self.add_button.setEnabled(len(self._options) < 12)

    def _edit(self):
        label = self.selector.currentData()
        if label is not None:
            self._options[label] = self.editor.toPlainText()
            self.changed.emit()

    def add_option(self):
        if len(self._options) >= 12:
            return
        label = next(label for label in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if label not in self._options)
        self.set_options({**self._options, label: ""}, label)
        self.changed.emit()

    def remove_option(self):
        label = self.selector.currentData()
        if label is not None:
            self.set_options({key: value for key, value in self._options.items() if key != label})
            self.changed.emit()

    def options(self):
        return dict(self._options)
