from pathlib import Path


ACCENT = "#ac456d"
TEXT = "#273142"
MUTED = "#667085"
ICON_DIR = (Path(__file__).resolve().parents[2] / "assets" / "ui").as_posix()

STYLE = """
QMainWindow, QDialog { background: #f6f7f9; }
QWidget#miniPracticeWindow { background: #f6f7f9; }
QWidget#wordStudyCanvas { background: #f6f7f9; }
QWidget#recognitionDraftBody { background: #f6f7f9; }
QWidget#homeCanvas, QScrollArea#homeScroll { background: #f6f7f9; border: none; }
QFrame#homeHero { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #344054, stop:1 #202938); border: none; border-radius: 18px; }
QLabel#heroTitle { color: white; font-size: 28px; font-weight: 700; }
QLabel#heroEyebrow { color: #cbd5e1; font-size: 12px; }
QLabel#heroCaption { color: #e2e8f0; font-size: 13px; }
QPushButton#heroButton { background: #ffffff; color: #273142; border: none; padding: 10px 16px; }
QPushButton#heroButton:hover { background: #f8eaf0; }
QFrame#homeStatCard, QFrame#homeFeatureCard { background: white; border: 1px solid #e4e7ec; border-radius: 14px; }
QLabel#homeStatValue { color: #273142; font-size: 25px; font-weight: 700; }
QScrollArea#wordStudyScroll, QScrollArea#practiceScroll { background: transparent; border: none; }
QLabel { color: #273142; }
QLabel#pageTitle { color: #202938; font-size: 27px; font-weight: 700; }
QLabel#pageSubtitle, QLabel#muted { color: #667085; font-size: 12px; }
QLabel#resultCount, QLabel#cardCaption { color: #667085; font-size: 12px; }
QLabel#statValue { color: #ac456d; font-size: 14px; font-weight: 700; }
QLabel#brandTitle { color: #202938; font-size: 15px; font-weight: 700; }
QLabel#sectionCaption { color: #667085; font-size: 11px; padding: 0 10px 5px; }
QLabel#sectionTitle { color: #273142; font-size: 15px; font-weight: 700; }
QLabel#emptyTitle { color: #273142; font-size: 18px; font-weight: 700; }
QLabel#detailTitle { color: #273142; font-size: 16px; font-weight: 700; }
QLabel#badge { background: #fbe8f0; color: #ac456d; border-radius: 10px; padding: 5px 10px; font-weight: 600; }
QLabel#attachmentPreview { background: #f8f9fb; border: 1px solid #e4e7ec; border-radius: 12px; color: #667085; }
QLabel#practiceStem { background: white; border: 1px solid #e4e7ec; border-radius: 14px; padding: 20px; color: #273142; font-size: 17px; }
QLabel#practiceSolution { background: #f8f9fb; border: 1px solid #e4e7ec; border-radius: 12px; padding: 14px; color: #273142; }
QLabel#wordFace { color: #ac456d; font-size: 30px; font-weight: 700; padding: 18px 0; }
QLabel#wordMeaning { color: #273142; font-size: 17px; padding: 12px; background: #f8f9fb; border-radius: 12px; }
QFrame#sidebar { background: #ffffff; border-right: 1px solid #e4e7ec; }
QFrame#workspaceHeader { background: #ffffff; border-bottom: 1px solid #e4e7ec; }
QFrame#libraryPanel, QFrame#detailPanel { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 14px; }
QFrame#separator { background: #e4e7ec; border: none; }
QFrame#emptyLibrary { background: white; }
QFrame#formCard { background: white; border: 1px solid #e4e7ec; border-radius: 14px; }
QFrame#learningHeatmap { background: white; border: 1px solid #e4e7ec; border-radius: 14px; }
QFrame#imageDropZone { background: #ffffff; border: 2px dashed #cbd1da; border-radius: 16px; }
QFrame#imageDropZone[dragging="true"] { background: #fbe8f0; border-color: #ac456d; }
QScrollArea#miniPracticeScroll { background: transparent; border: 1px solid #e4e7ec; border-radius: 12px; }
QTextBrowser#previewText { background: white; border: none; padding: 8px 4px; color: #273142; font-size: 14px; }
QTextBrowser#mathPreview { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 10px; padding: 8px 10px; color: #273142; font-size: 14px; }
QSplitter::handle { background: #f1f3f6; }
QSplitter::handle:hover { background: #e3b3c5; }
QTabWidget::pane { border: none; border-top: 1px solid #e4e7ec; }
QTabBar::tab { background: transparent; color: #667085; padding: 10px 13px; margin: 0 6px 6px 0; border-radius: 9px; }
QTabBar::tab:selected { background: #fbe8f0; color: #ac456d; font-weight: 600; }
QTabBar::tab:hover { background: #f8f9fb; color: #ac456d; }
QTabBar::tab:disabled { color: #98a2b3; background: transparent; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
    background: #ffffff; border: 1px solid #e4e7ec; border-radius: 10px;
    padding: 8px 10px; color: #273142; selection-background-color: #f6d7e5; selection-color: #273142;
}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #d6a5ba; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #ac456d; background: white; }
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #98a2b3; background: #f1f3f6; }
QComboBox, QSpinBox { min-height: 22px; padding-right: 28px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url("@assets/chevron-down.svg"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #e4e7ec; padding: 4px; selection-background-color: #fbe8f0; selection-color: #ac456d; outline: none; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 24px; border: none; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border: none; }
QSpinBox::up-arrow { image: url("@assets/chevron-up.svg"); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url("@assets/chevron-down.svg"); width: 10px; height: 10px; }
QPushButton {
    background: #ffffff; color: #475467; border: 1px solid #e4e7ec;
    border-radius: 10px; padding: 8px 13px; font-weight: 600;
}
QPushButton:hover { background: #f1f3f6; border-color: #d6a5ba; }
QPushButton:focus { border-color: #ac456d; }
QPushButton:pressed { background: #f6d7e5; border-color: #c77a96; }
QPushButton#primaryButton { background: #ac456d; color: white; border-color: #ac456d; }
QPushButton#primaryButton:hover { background: #a73f65; border-color: #a73f65; }
QPushButton#primaryButton:pressed { background: #913455; border-color: #913455; }
QPushButton#softButton { background: #fcecf2; color: #ac456d; border-color: #f2d7e3; }
QPushButton#softButton:hover { background: #f8dfe9; border-color: #d6a5ba; }
QPushButton#softButton:pressed { background: #f2d0df; }
QPushButton#dangerButton { color: #b34d5b; }
QPushButton:disabled, QPushButton#primaryButton:disabled, QPushButton#softButton:disabled, QPushButton#dangerButton:disabled {
    background: #f1f3f6; color: #98a2b3; border-color: #e4e7ec;
}
QPushButton#navButton, QPushButton#navButtonActive, QPushButton#navUtility { text-align: left; border: none; padding: 11px 13px; font-weight: 500; }
QPushButton#navButton, QPushButton#navUtility { background: transparent; color: #667085; }
QPushButton#navButton:hover, QPushButton#navUtility:hover { background: #fce5ee; color: #475467; }
QPushButton#navButtonActive { background: #f6d7e5; color: #ac456d; font-weight: 700; }
QPushButton#navButton:pressed, QPushButton#navUtility:pressed, QPushButton#navButtonActive:pressed { background: #efc8d9; }
QTableWidget { background: white; alternate-background-color: #fafbfc; border: none; color: #273142; selection-background-color: #fbe1ec; selection-color: #913455; outline: none; }
QHeaderView::section { background: #f8f9fb; color: #667085; border: none; border-bottom: 1px solid #e4e7ec; padding: 10px 12px; font-weight: 600; }
QTableWidget::item { padding-left: 10px; border: none; }
QTableWidget::item:hover { background: #f1f3f6; }
QTableWidget::item:selected { background: #fbe1ec; color: #913455; }
QListWidget { background: white; border: 1px solid #e4e7ec; border-radius: 12px; padding: 6px; color: #273142; outline: none; }
QListWidget::item { padding: 10px; margin-bottom: 4px; border-radius: 8px; }
QListWidget::item:hover { background: #f8f9fb; }
QListWidget::item:selected { background: #fbe1ec; color: #913455; }
QCheckBox { color: #475467; spacing: 9px; }
QRadioButton { color: #475467; spacing: 9px; }
QRadioButton::indicator { width: 18px; height: 18px; border: none; background: transparent; image: url("@assets/radio_unchecked.svg"); }
QRadioButton::indicator:checked { image: url("@assets/radio_checked.svg"); }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #cbd1da; border-radius: 5px; background: white; }
QCheckBox::indicator:hover { border-color: #ac456d; background: #f8f9fb; }
QCheckBox::indicator:checked { background: #ac456d; border-color: #ac456d; image: url("@assets/check.svg"); }
QCheckBox::indicator:disabled { background: #e4e7ec; border-color: #d0d5dd; }
QCheckBox::indicator:disabled:checked { background: #ac456d; border-color: #ac456d; }
QScrollArea#choiceScroll { background: #fafbfc; border: 1px solid #e4e7ec; border-radius: 12px; }
QWidget#choiceBody { background: #fafbfc; }
QScrollBar:vertical { background: #f6f7f9; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #cbd1da; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #c77a96; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: #f6f7f9; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #cbd1da; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
QStatusBar { background: #f1f3f6; color: #667085; font-size: 11px; padding: 3px 10px; }
QDialogButtonBox QPushButton { min-width: 82px; }
QMenu { background: white; color: #273142; border: 1px solid #e4e7ec; padding: 6px; }
QMenu::item { padding: 9px 24px; border-radius: 6px; }
QMenu::item:selected { background: #f8eaf0; color: #ac456d; }
QProgressBar { background: #e4e7ec; border: none; border-radius: 4px; text-align: center; color: #273142; }
QProgressBar::chunk { background: #ac456d; border-radius: 4px; }
QToolTip { color: #f6f7f9; background: #344054; border: none; border-radius: 6px; padding: 6px 8px; }
""".replace("@assets", ICON_DIR)
