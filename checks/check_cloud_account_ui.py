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

    def login(dialog):
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
        assert window.close()
        return 0

    sys.argv = [str(Path(main.__file__)), '--cloud', '--workspace-root', str(guest)]
    with patch.object(CloudSignInDialog, 'exec', login), patch.object(QApplication, 'exec', check_event_loop):
        assert main.main() == 0


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
    if '--bootstrap-child' in sys.argv:
        child()
    elif '--foreground-child' in sys.argv:
        foreground_child()
    else:
        with tempfile.TemporaryDirectory(prefix='flandre-account-ui-') as root:
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', FLANDRE_DATA_DIR=str(Path(root) / 'guest'))
            for mode in ('--bootstrap-child', '--foreground-child'):
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), mode],
                                        env=environment, capture_output=True, text=True, timeout=45)
                if result.returncode:
                    raise AssertionError(result.stdout + result.stderr)
        print('PASS: account bootstrap paths, separate guest, and busy sign-in/sync/conflict close guards')
