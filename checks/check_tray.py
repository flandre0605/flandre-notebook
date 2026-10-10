"""Temporary workspace only; add --native to check the Windows tray surface."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if '--native' not in sys.argv:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

with tempfile.TemporaryDirectory(prefix='flandre-tray-') as root:
    os.environ['FLANDRE_DATA_DIR'] = root
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from app.database import store
    from app.services.storage import initialize_storage
    from app.ui.main_window import MainWindow

    app = QApplication([])
    app.setApplicationName('FlandreTrayCheck')
    initialize_storage()
    native = QSystemTrayIcon.isSystemTrayAvailable()
    if '--native' in sys.argv:
        assert native, 'Windows system tray is unavailable'
    with patch.object(QSystemTrayIcon, 'isSystemTrayAvailable', return_value=True), \
         patch.object(QSystemTrayIcon, 'showMessage') as notice, \
         patch('app.ui.main_window.GlobalScreenshotHotkey') as hotkey, \
         patch.object(QApplication, 'quit') as quit_app:
        window = MainWindow()
        window.show()
        app.processEvents()
        tray = window._tray
        assert tray.isVisible() and not tray.icon().isNull()
        assert not app.quitOnLastWindowClosed()
        actions = tray.contextMenu().actions()
        assert [a.text() for a in actions if not a.isSeparator()] == ['打开主界面', '显示桌宠', '退出程序']
        handle = int(window.winId())
        assert not window.close() and not window.isVisible()
        assert tray.isVisible() and notice.call_count == 1
        assert not hotkey.return_value.close.called
        quit_app.assert_not_called()
        window._tray_activated(QSystemTrayIcon.ActivationReason.Context)
        assert not window.isVisible()
        window._tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert window.isVisible() and int(window.winId()) == handle
        window.showMinimized()
        actions[0].trigger()
        assert window.isVisible() and not window.isMinimized()
        window.showMaximized()
        assert not window.close()
        actions[0].trigger()
        assert window.isMaximized() and notice.call_count == 1
        window.showNormal()
        actions[1].trigger()
        assert window.isVisible() and window._practice_setup is not None
        assert window._practice_setup.mini_mode.isChecked()
        assert '空题库' in window._practice_setup.status.text()
        assert not store.list_questions(), 'Tray must not insert demonstration content'
        store.save_question({'stem':'isolated check', 'answer':'answer'})
        window.start_practice()
        window._practice_setup.accept()
        practice = window._page_dialogs['practice_run']
        assert window._mini_practice_window.isVisible() and not window.isVisible(), 'First pet launch must open the pet automatically'
        practice.user_answer.setPlainText('unsaved answer')
        actions[1].trigger()
        mini = window._mini_practice_window
        assert mini.isVisible() and not window.isVisible()
        assert not window.close() and not mini.isVisible()
        assert store.load_workspace('practice')['answer'] == 'unsaved answer'
        actions[1].trigger()
        assert window._mini_practice_window is mini and mini.isVisible()
        actions[0].trigger()
        assert window.isVisible() and window._mini_practice_window is None
        assert practice.user_answer.toPlainText() == 'unsaved answer'
        with patch.object(practice, 'save_progress', return_value=False):
            assert not window.close() and window.isVisible()
            actions[-1].trigger()
            assert not window._exit_requested and tray.isVisible()
            quit_app.assert_not_called()
        with patch.object(store, 'save_workspace', side_effect=ValueError('synthetic save failure')):
            assert not window.close() and window.isVisible()
        window._recognition_dialogs.append(SimpleNamespace(_recognizing=True))
        assert not window.close() and not window.isVisible(), 'Running requests may continue in background'
        actions[-1].trigger()
        assert window.isVisible() and not window._exit_requested and tray.isVisible()
        quit_app.assert_not_called()
        window._recognition_dialogs.clear()
        actions[-1].trigger()
        quit_app.assert_called_once()
        assert not tray.isVisible() and not window.isVisible()
        assert hotkey.return_value.close.called
    app.setQuitOnLastWindowClosed(True)
    with patch.object(QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False), \
         patch('app.ui.main_window.GlobalScreenshotHotkey'):
        fallback = MainWindow()
        fallback.show()
        assert fallback._tray is None and fallback.close(), 'Without a tray, closing must exit normally'
print('PASS: tray hide/restore, same window, task and save guards, pet state, empty library, exit and no-tray fallback')
