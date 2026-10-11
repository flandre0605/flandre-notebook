"""Desktop startup, close, tray and offline checks against a synthetic backend."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def check():
    with tempfile.TemporaryDirectory(prefix='flandre-auto-sync-') as folder:
        os.environ['FLANDRE_DATA_DIR'] = folder
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
        from PySide6.QtCore import QThreadPool
        from app.database import store, vocabulary
        from app.ui.main_window import MainWindow
        from app.services.cloud_sync import CloudSession, CloudSyncError, ENVIRONMENT_ID, synchronize
        from app.services.cloud_sync_store import SyncStore
        from check_cloud_sync import Backend, Client
        import app.services.cloud_sync as protocol
        app = QApplication([])
        app.setApplicationName('FlandreAutoSyncCheck')
        store.initialize()
        session = CloudSession(dict(user_id='USER_A',access_token='synthetic',expires_in=7200),'test')
        local = SyncStore(Path(folder),'USER_A',ENVIRONMENT_ID);local.bind()
        backend = Backend();client = Client(backend,'USER_A')
        calls = []
        failing = [False]
        def sync(local, client, pull=True):
            calls.append(pull)
            if failing[0]:
                raise CloudSyncError('合成断网：本地修改保留。')
            return synchronize(local, client, pull=pull)
        def wait(predicate):
            until=time.monotonic()+12
            while not predicate():
                app.processEvents();time.sleep(.01)
                assert time.monotonic()<until,'automatic lifecycle did not finish'
            app.processEvents()
        class Tray:
            def isVisible(self):return True
            def showMessage(self,*args):pass
            def hide(self):pass
        with patch.object(QSystemTrayIcon,'isSystemTrayAvailable',return_value=False), patch('app.ui.main_window.GlobalScreenshotHotkey'), patch.object(protocol,'CloudClient',return_value=client), patch.object(protocol,'synchronize',side_effect=sync):
            vocabulary.save_word(dict(word='startup',meaning='启动'))
            window=MainWindow(session,Path(folder));window.show()
            wait(lambda: bool(calls) and window._auto_sync_worker is None)
            assert calls==[True] and local.status()['pending']==0
            assert window.statusBar().currentMessage().startswith('自动同步完成')
            vocabulary.save_word(dict(word='closing',meaning='关闭'))
            assert not window.close()
            assert window._auto_sync_worker is not None and window.isVisible()
            assert not window.can_switch_workspace()
            wait(lambda: not window.isVisible())
            assert local.status()['pending']==0 and len(backend.learning_rows)==2
            window.show();window._tray=Tray();window._tray_notice_shown=True
            vocabulary.save_word(dict(word='tray',meaning='托盘'))
            window.close();wait(lambda: not window.isVisible())
            assert len(backend.learning_rows)==3
            window._restore_from_tray();wait(lambda: len(calls)>=4 and window._auto_sync_worker is None)
            failing[0]=True
            vocabulary.save_word(dict(word='offline',meaning='离线'))
            window._request_exit()
            wait(lambda: not window.isVisible())
            assert window._exit_requested and local.status()['pending']==1
            assert '断网' in window.statusBar().currentMessage()
            window._tray=None
            failing[0]=False
            restarted=MainWindow(session,Path(folder));restarted.show()
            wait(lambda: local.status()['pending']==0 and restarted._auto_sync_worker is None)
            assert len(backend.learning_rows)==4
            restarted._pages['question']=object()
            restarted.close();wait(lambda:not restarted.isVisible())
            assert calls[-1] is False,'active editor must defer remote writes during close'
            QThreadPool.globalInstance().waitForDone()
            session.close()
        print('PASS: startup, close, tray restore, exit waits, offline exit/reopen, workspace guard and active-editor upload only')


if __name__=='__main__':check()
