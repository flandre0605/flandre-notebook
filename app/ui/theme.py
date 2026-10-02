from pathlib import Path


ACCENT = "#b54b72"
TEXT = "#503845"
MUTED = "#806772"
ICON_DIR = (Path(__file__).resolve().parents[2] / "assets" / "ui").as_posix()

STYLE = """
QMainWindow, QDialog { background: #fff8fb; }
QWidget#miniPracticeWindow { background: #fff8fb; }
QWidget#wordStudyCanvas { background: #fff8fb; }
QWidget#recognitionDraftBody { background: #fff8fb; }
QWidget#homeCanvas, QScrollArea#homeScroll { background: #fff8fb; border: none; }
QFrame#homeHero { background: #fce8f1; border: 1px solid #f0cddd; border-radius: 18px; }
QFrame#homeStatCard, QFrame#homeFeatureCard { background: white; border: 1px solid #efdce5; border-radius: 14px; }
QLabel#homeStatValue { color: #9f4565; font-size: 25px; font-weight: 700; }
QScrollArea#wordStudyScroll { background: transparent; border: none; }
QLabel { color: #503845; }
QLabel#pageTitle { color: #422e3b; font-size: 27px; font-weight: 700; }
QLabel#pageSubtitle, QLabel#muted { color: #806772; font-size: 12px; }
QLabel#resultCount, QLabel#cardCaption { color: #806772; font-size: 12px; }
QLabel#statValue { color: #9f4565; font-size: 14px; font-weight: 700; }
QLabel#brandTitle { color: #422e3b; font-size: 15px; font-weight: 700; }
QLabel#sectionCaption { color: #806772; font-size: 11px; padding: 0 10px 5px; }
QLabel#sectionTitle { color: #503845; font-size: 15px; font-weight: 700; }
QLabel#emptyTitle { color: #503845; font-size: 18px; font-weight: 700; }
QLabel#detailTitle { color: #503845; font-size: 16px; font-weight: 700; }
QLabel#badge { background: #fbe8f0; color: #9f4565; border-radius: 10px; padding: 5px 10px; font-weight: 600; }
QLabel#attachmentPreview { background: #fff4f8; border: 1px solid #ecd5df; border-radius: 12px; color: #806772; }
QLabel#practiceStem { background: white; border: 1px solid #ecd5df; border-radius: 14px; padding: 20px; color: #503845; font-size: 17px; }
QLabel#practiceSolution { background: #fff4f8; border: 1px solid #ecd5df; border-radius: 12px; padding: 14px; color: #503845; }
QLabel#wordFace { color: #9f4565; font-size: 30px; font-weight: 700; padding: 18px 0; }
QLabel#wordMeaning { color: #503845; font-size: 17px; padding: 12px; background: #fff4f8; border-radius: 12px; }
QFrame#sidebar { background: #fff0f5; border-right: 1px solid #ecd5df; }
QFrame#workspaceHeader { background: #fffcfd; border-bottom: 1px solid #ecd5df; }
QFrame#libraryPanel, QFrame#detailPanel { background: #ffffff; }
QFrame#separator { background: #ecd5df; border: none; }
QFrame#formCard { background: white; border: 1px solid #ecd5df; border-radius: 14px; }
QFrame#imageDropZone { background: #fffcfd; border: 2px dashed #ddb8c8; border-radius: 16px; }
QFrame#imageDropZone[dragging="true"] { background: #fbe8f0; border-color: #b54b72; }
QScrollArea#miniPracticeScroll { background: transparent; border: 1px solid #ecd5df; border-radius: 12px; }
QTextBrowser#previewText { background: white; border: none; padding: 8px 4px; color: #503845; font-size: 14px; }
QTextBrowser#mathPreview { background: #fffcfd; border: 1px solid #ecd5df; border-radius: 10px; padding: 8px 10px; color: #503845; font-size: 14px; }
QSplitter::handle { background: #f7e6ed; }
QSplitter::handle:hover { background: #e3b3c5; }
QTabWidget::pane { border: none; border-top: 1px solid #ecd5df; }
QTabBar::tab { background: transparent; color: #806772; padding: 10px 13px; margin: 0 6px 6px 0; border-radius: 9px; }
QTabBar::tab:selected { background: #fbe8f0; color: #9f4565; font-weight: 600; }
QTabBar::tab:hover { background: #fff4f8; color: #9f4565; }
QTabBar::tab:disabled { color: #a9949f; background: transparent; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #fffcfd; border: 1px solid #ecd5df; border-radius: 10px;
    padding: 8px 10px; color: #503845; selection-background-color: #f6d7e5; selection-color: #503845;
}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #d6a5ba; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #b54b72; background: white; }
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #a9949f; background: #fbf5f8; }
QComboBox, QSpinBox { min-height: 22px; padding-right: 28px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url("@assets/chevron-down.svg"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #ecd5df; padding: 4px; selection-background-color: #fbe8f0; selection-color: #9f4565; outline: none; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 24px; border: none; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border: none; }
QSpinBox::up-arrow { image: url("@assets/chevron-up.svg"); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url("@assets/chevron-down.svg"); width: 10px; height: 10px; }
QPushButton {
    background: #fffcfd; color: #705361; border: 1px solid #ecd5df;
    border-radius: 10px; padding: 8px 13px; font-weight: 600;
}
QPushButton:hover { background: #fff0f5; border-color: #d6a5ba; }
QPushButton:focus { border-color: #b54b72; }
QPushButton:pressed { background: #f6d7e5; border-color: #c77a96; }
QPushButton#primaryButton { background: #b54b72; color: white; border-color: #b54b72; }
QPushButton#primaryButton:hover { background: #a73f65; border-color: #a73f65; }
QPushButton#primaryButton:pressed { background: #913455; border-color: #913455; }
QPushButton#softButton { background: #fcecf2; color: #9f4565; border-color: #f2d7e3; }
QPushButton#softButton:hover { background: #f8dfe9; border-color: #d6a5ba; }
QPushButton#softButton:pressed { background: #f2d0df; }
QPushButton#dangerButton { color: #b34d5b; }
QPushButton:disabled, QPushButton#primaryButton:disabled, QPushButton#softButton:disabled, QPushButton#dangerButton:disabled {
    background: #fbf5f8; color: #a9949f; border-color: #f0e3e9;
}
QPushButton#navButton, QPushButton#navButtonActive, QPushButton#navUtility { text-align: left; border: none; padding: 11px 13px; font-weight: 500; }
QPushButton#navButton, QPushButton#navUtility { background: transparent; color: #806772; }
QPushButton#navButton:hover, QPushButton#navUtility:hover { background: #fce5ee; color: #705361; }
QPushButton#navButtonActive { background: #f6d7e5; color: #9f4565; font-weight: 700; }
QPushButton#navButton:pressed, QPushButton#navUtility:pressed, QPushButton#navButtonActive:pressed { background: #efc8d9; }
QTableWidget { background: white; alternate-background-color: #fff7fa; border: none; color: #503845; selection-background-color: #fbe1ec; selection-color: #913455; outline: none; }
QHeaderView::section { background: #fff4f8; color: #806772; border: none; border-bottom: 1px solid #ecd5df; padding: 10px 12px; font-weight: 600; }
QTableWidget::item { padding-left: 10px; border: none; }
QTableWidget::item:hover { background: #fff0f5; }
QTableWidget::item:selected { background: #fbe1ec; color: #913455; }
QListWidget { background: white; border: 1px solid #ecd5df; border-radius: 12px; padding: 6px; color: #503845; outline: none; }
QListWidget::item { padding: 10px; margin-bottom: 4px; border-radius: 8px; }
QListWidget::item:hover { background: #fff4f8; }
QListWidget::item:selected { background: #fbe1ec; color: #913455; }
QCheckBox { color: #705361; spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #cfa4b6; border-radius: 5px; background: white; }
QCheckBox::indicator:hover { border-color: #b54b72; background: #fff4f8; }
QCheckBox::indicator:checked { background: #b54b72; border-color: #b54b72; image: url("@assets/check.svg"); }
QCheckBox::indicator:disabled { background: #f0e3e9; border-color: #dfcbd5; }
QScrollBar:vertical { background: #fff8fb; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #e0bdcd; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #c77a96; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: #fff8fb; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #e0bdcd; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
QStatusBar { background: #fff0f5; color: #806772; font-size: 11px; padding: 3px 10px; }
QDialogButtonBox QPushButton { min-width: 82px; }
QToolTip { color: #fff8fb; background: #654253; border: none; border-radius: 6px; padding: 6px 8px; }
""".replace("@assets", ICON_DIR)
