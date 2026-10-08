"""Isolated account bootstrap and window lifecycle checks; never opens personal data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def child():
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication, QDialog
    from app.ui.cloud_account_dialog import CloudSignInDialog, CloudAccountDialog, ConflictDialog
    from app.services.cloud_sync import CloudSession, ENVIRONMENT_ID
    from app.services.cloud_accounts import account_directory
    # Login must not freeze the guest paths by importing database services.
    assert 'app.database.store' not in sys.modules
    import main
    guest = Path(os.environ['FLANDRE_DATA_DIR'])
    expected = account_directory(guest, 'ui-check-user')

    prompted = []
    def login(dialog):
        prompted.append(True)
        dialog.session = CloudSession({'user_id':'ui-check-user', 'access_token':'memory-only', 'expires_in':7200}, 'ui-test')
        return QDialog.DialogCode.Accepted

    def check_event_loop(app):
        from app import paths
        from app.database import store
        from app.services import attachments, backup
        from app.ui.main_window import MainWindow
        assert paths.DATA_DIR == store.DATA_DIR == expected
        assert attachments.ATTACHMENTS_DIR == backup.ATTACHMENTS_DIR == expected / 'attachments'
        assert not (guest / 'questions.db').exists()
        window = next(item for item in app.topLevelWidgets() if isinstance(item, MainWindow))
        assert window.cloud_root == guest
        dialog = CloudAccountDialog(window)
        assert dialog.local().user_id == 'ui-check-user'
        assert dialog.local().status()['pending'] == 0
        window._cloud_dialog = dialog
        dialog.show()
        app.processEvents()
        dialog.worker = object()
        assert not dialog.close(), 'Busy account window closed'
        assert not window.close(), 'Main window closed while syncing'
        dialog.worker = None
        conflict = ConflictDialog(dialog.local(), None, dialog)
        conflict.show()
        app.processEvents()
        conflict.worker = object()
        assert not conflict.close(), 'Busy conflict window closed'
        assert not window.close(), 'Main window closed while resolving a conflict'
        conflict.worker = None
        conflict.close()
        dialog.close()
        window._cloud_dialog = None
        signin = CloudSignInDialog()
        signin.show()
        app.processEvents()
        signin.worker = object()
        assert not signin.close(), 'Busy sign-in window closed'
        signin.worker = None
        signin.close()
        from app.services.cloudbase_login import EmailChallenge
        from PySide6.QtCore import QThreadPool
        signin = CloudSignInDialog()
        signin.show()
        signin.switch_button.click()
        app.processEvents()
        assert signin.registering and signin.email.isVisible() and signin.confirm.isVisible()
        signin.email.setText('test@example.com')
        signin.username.setText('new_user')
        signin.password.setText('Password123!')
        signin.confirm.setText('different')
        signin.sign_in()
        assert '不一致' in signin.status.text() and signin.worker is None
        challenge = EmailChallenge('test@example.com', {'verification_id':'memory-only', 'expires_in':600})
        with patch('app.ui.cloud_account_dialog.send_registration_code', return_value=challenge):
            signin.send_code()
            signin.switch_button.click()
            assert signin.registering, 'Busy registration switched mode'
            assert not signin.close(), 'Busy email send closed'
            QThreadPool.globalInstance().waitForDone(5000)
            app.processEvents()
        assert signin.challenge is challenge and not signin.send_button.isEnabled()
        assert '秒' in signin.send_button.text()
        with patch('app.ui.cloud_account_dialog.send_registration_code') as send:
            signin.send_code()
            send.assert_not_called()
        signin.password.setText('Password123!')
        signin.confirm.setText('Password123!')
        signin.code.setText('123456')
        with patch.object(challenge, 'signup', return_value={'user_id':'new-user', 'access_token':'memory-only', 'expires_in':7200}) as signup:
            signin.sign_in()
            assert not signin.password.text() and not signin.confirm.text() and not signin.code.text()
            QThreadPool.globalInstance().waitForDone(5000)
            app.processEvents()
            signup.assert_called_once()
        assert signin.result() == QDialog.DialogCode.Accepted and signin.session.user_id == 'new-user'
        signin.session.close()
        renewal = CloudSignInDialog(expected_user='ui-check-user')
        renewal.set_registration(True)
        assert not renewal.registering and renewal.switch_button.isHidden(), 'Renewal must preserve account identity'
        renewal.close()
        signup_view = CloudSignInDialog()
        signup_view.set_registration(True)
        signup_view.show()
        app.processEvents()
        if os.environ.get('FLANDRE_REGISTRATION_SCREENSHOT'):
            signup_view.grab().save(str(Path(os.environ['FLANDRE_REGISTRATION_SCREENSHOT'])))
        signup_view.close()
        # Login changes the existing native window; colliding local IDs remain isolated.
        from PySide6.QtCore import QLockFile, QTimer
        from app.database import vocabulary
        from app.services.cloud_sync_store import SyncStore
        handle = int(window.winId())
        geometry = window.geometry()
        a_id = store.save_question({'stem':'account A', 'notes':'A notes'})
        store.save_workspace('switch-check', {'owner':'A'})
        window.refresh()
        window.preview_notes.setPlainText('A autosaved before switch')
        window.manage_profiles()
        assert window.can_switch_workspace(), 'Idle settings mistaken for a running model request'
        window._profiles_dialog.name.setText('unsaved model')
        assert not window.can_switch_workspace(), 'Unsaved model settings were discarded'
        window._profiles_dialog._clear()
        window.show_vocabulary()
        window.vocabulary_page._editing_active = True
        with patch.object(window.vocabulary_page, '_editor_values', return_value={'word':'x'*4001}):
            assert not window.can_switch_workspace(), 'Invalid word draft was discarded on switch'
        window.vocabulary_page._editing_active = False
        assert window.switch_workspace(None)
        assert int(window.winId()) == handle and window.geometry() == geometry and window.isVisible()
        assert paths.DATA_DIR == store.DATA_DIR == guest
        assert store.DATABASE_PATH == guest / 'questions.db'
        assert backup.ATTACHMENTS_DIR == attachments.ATTACHMENTS_DIR == guest / 'attachments'
        assert not store.list_questions() and store.load_workspace('switch-check') is None
        guest_id = store.save_question({'stem':'guest only'})
        assert a_id == guest_id, 'Fixture requires colliding IDs across workspaces'
        window.refresh()
        window.preview_notes.setPlainText('guest autosave')
        other = account_directory(guest, 'USER_B')
        def login_b(dialog):
            dialog.session = CloudSession({'user_id':'USER_B','access_token':'fake','expires_in':7200}, 'B')
            return QDialog.DialogCode.Accepted
        dialog = CloudAccountDialog(window)
        window._cloud_dialog = dialog
        with patch.object(CloudSignInDialog, 'exec', login_b), patch('subprocess.Popen') as launch:
            dialog.sign_in()
            launch.assert_not_called()
        assert window.cloud_session.user_id == 'USER_B' and int(window.winId()) == handle
        assert paths.DATA_DIR == store.DATA_DIR == other and not store.list_questions()
        store.save_question({'stem':'B only'})
        assert store.load_workspace('switch-check') is None
        # A live job or failed target leaves the original window/data/session untouched.
        window._cloud_dialog = None
        busy = CloudAccountDialog(window);busy.worker=object();window._cloud_dialog=busy
        refused = CloudSession({'user_id':'REFUSED','access_token':'fake','expires_in':7200}, 'refused')
        assert not window.switch_workspace(refused) and refused.closed and store.DATA_DIR == other
        busy.worker=None;window._cloud_dialog=None
        locked_root = account_directory(guest, 'LOCKED');locked_root.mkdir(parents=True)
        external = QLockFile(str(locked_root / '.workspace.lock'));assert external.tryLock(0)
        refused = CloudSession({'user_id':'LOCKED','access_token':'fake','expires_in':7200}, 'locked')
        assert not window.switch_workspace(refused) and store.DATA_DIR == other and window.cloud_session.user_id == 'USER_B'
        external.unlock()
        bad_root = account_directory(guest, 'BROKEN');bad_root.mkdir(parents=True)
        import sqlite3
        with sqlite3.connect(bad_root / 'questions.db') as db: db.execute('PRAGMA user_version = 999')
        refused = CloudSession({'user_id':'BROKEN','access_token':'fake','expires_in':7200}, 'broken')
        assert not window.switch_workspace(refused) and store.DATA_DIR == other
        # Repeated switches stop old autosave timers and restore the correct draft.
        a = CloudSession({'user_id':'ui-check-user','access_token':'fake','expires_in':7200}, 'A')
        assert window.switch_workspace(a)
        assert store.get_question(a_id)['notes'] == 'A autosaved before switch'
        assert store.load_workspace('switch-check') == {'owner':'A'}
        assert len(window.findChildren(QTimer)) < 12, 'Workspace timers accumulate across switches'
        dialog = CloudAccountDialog(window);window._cloud_dialog=dialog
        with patch.object(a, 'logout', wraps=a.logout) as logout:
            dialog.logout();logout.assert_called_once()
        assert int(window.winId()) == handle and window.isVisible() and window.cloud_session is None
        assert store.DATA_DIR == guest and store.get_question(guest_id)['notes'] == 'guest autosave'
        assert store.get_question(guest_id)['stem'] == 'guest only'
        assert window.close()
        return 0

    from app.services.cloud_session_store import CloudSessionStore
    restored = '--restored-child' in sys.argv
    sys.argv = [str(Path(main.__file__))] if restored else [str(Path(main.__file__)), '--cloud', '--workspace-root', str(guest)]
    previous = CloudSession({'user_id':'ui-check-user', 'access_token':'', 'expires_in':0}, 'ui-test', 'device')
    with patch.object(CloudSessionStore, 'load_last', return_value=previous) as load, patch.object(CloudSignInDialog, 'exec', login), patch.object(QApplication, 'exec', check_event_loop):
        assert main.main() == 0
        if restored:
            load.assert_called_once();assert not prompted
        else: load.assert_not_called()


def foreground_child():
    from unittest.mock import patch
    from PySide6.QtCore import QTimer
    from app.ui.cloud_account_dialog import CloudSignInDialog
    import main
    original = CloudSignInDialog.__init__
    checked = []
    def initialize(dialog, *args, **kwargs):
        original(dialog, *args, **kwargs)
        def finish():
            checked.append(dialog.isVisible())
            dialog.reject()
        # Regression: changing flags after eight seconds used to end exec().
        QTimer.singleShot(9000, finish)
    sys.argv = [str(Path(main.__file__)), '--cloud', '--foreground']
    with patch.object(CloudSignInDialog, '__init__', initialize):
        assert main.main() == 0
    assert checked == [True], 'Requested modal login disappeared before user action'


if __name__ == '__main__':
    if '--bootstrap-child' in sys.argv or '--restored-child' in sys.argv:
        child()
    elif '--foreground-child' in sys.argv:
        foreground_child()
    else:
        with tempfile.TemporaryDirectory(prefix='flandre-account-ui-') as root:
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', FLANDRE_DATA_DIR=str(Path(root) / 'guest'))
            for mode in ('--bootstrap-child', '--restored-child', '--foreground-child'):
                environment['FLANDRE_DATA_DIR'] = str(Path(root) / mode[2:] / 'guest')
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), mode],
                                        env=environment, capture_output=True, text=True, timeout=45)
                if result.returncode:
                    raise AssertionError(result.stdout + result.stderr)
        print('PASS: verified registration UI, cooldown, busy guards, renewal identity and isolated account bootstrap')
