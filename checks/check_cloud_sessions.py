"""Login restart/refresh/logout regression; synthetic credentials, no network or OS vault writes."""
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from app.services.cloud_sync import CloudSession, CloudClient, CloudSyncError, ENVIRONMENT_ID
from app.services.cloud_session_store import CloudSessionStore
from app.services.cloudbase_login import refresh_session, LoginCheckError, SessionExpired


def session():
    return CloudSession(dict(user_id='USER_A', access_token='ACCESS_OLD', refresh_token='REFRESH_OLD', expires_in=7200), 'test', 'device')


def renewed():
    return dict(user_id='USER_A', access_token='ACCESS_NEW', refresh_token='REFRESH_NEW', expires_in=7200)


class SessionChecks(unittest.TestCase):
    def test_official_refresh_protocol_rotates_and_checks_identity(self):
        result = dict(sub='USER_A', token_type='Bearer', access_token='ACCESS_NEW', refresh_token='REFRESH_NEW', expires_in=7200)
        with patch('app.services.cloudbase_login.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = lambda *a, **k: BytesIO(json.dumps(result).encode())
            self.assertEqual(refresh_session(ENVIRONMENT_ID, 'REFRESH_OLD', 'device', 'USER_A'), renewed())
            request = opener.return_value.open.call_args.args[0]
            self.assertTrue(request.full_url.endswith('/auth/v1/token'))
            self.assertEqual(request.get_header('X-device-id'), 'device')
            self.assertEqual(json.loads(request.data), dict(grant_type='refresh_token', refresh_token='REFRESH_OLD'))
            result['sub'] = 'USER_B'
            with self.assertRaises(SessionExpired):
                refresh_session(ENVIRONMENT_ID, 'REFRESH_OLD', 'device', 'USER_A')

    def test_restart_secure_rotation_close_and_explicit_logout(self):
        with tempfile.TemporaryDirectory() as root:
            settings = QSettings(str(Path(root) / 'selector.ini'), QSettings.Format.IniFormat)
            vault = {}
            with patch('app.services.cloud_session_store.QSettings', return_value=settings) as settings_class, \
                 patch('app.services.cloud_session_store.credentials.save_api_key', side_effect=vault.__setitem__), \
                 patch('app.services.cloud_session_store.credentials.get_api_key', side_effect=vault.__getitem__), \
                 patch('app.services.cloud_session_store.credentials.delete_api_key', side_effect=lambda k: vault.pop(k, None)):
                settings_class.Status = QSettings.Status
                current = session(); current.remember(root); current.close()
                restored = CloudSessionStore(root).load_last()
                self.assertEqual((restored.user_id, restored.device_id, restored.token), ('USER_A', 'device', ''))
                self.assertIsNone(CloudSessionStore(Path(root) / 'different').load_last())
                with patch('app.services.cloudbase_login.refresh_session', side_effect=lambda *a: renewed()) as refresh:
                    self.assertEqual(restored.require_token(), 'ACCESS_NEW')
                    self.assertEqual(restored.require_token(), 'ACCESS_NEW')
                    refresh.assert_called_once_with(ENVIRONMENT_ID, 'REFRESH_OLD', 'device', 'USER_A')
                self.assertEqual(CloudSessionStore(root).load_last().refresh_token, 'REFRESH_NEW')
                self.assertNotIn('ACCESS_NEW', str(vault))
                self.assertNotIn('REFRESH', Path(settings.fileName()).read_text())
                restored.logout()
                self.assertIsNone(CloudSessionStore(root).load_last()); self.assertFalse(vault)

    def test_transient_failure_preserves_but_revocation_clears(self):
        current = session(); current.expires_at = 0
        with patch('app.services.cloudbase_login.refresh_session', side_effect=LoginCheckError('offline')):
            with self.assertRaises(CloudSyncError): current.require_token()
        self.assertEqual(current.refresh_token, 'REFRESH_OLD'); self.assertFalse(current.closed)
        with patch('app.services.cloudbase_login.refresh_session', side_effect=SessionExpired('revoked')):
            with self.assertRaises(CloudSyncError): current.require_token()
        self.assertTrue(current.closed); self.assertFalse(current.refresh_token)

    def test_only_unauthorized_retries_once_and_parallel_refresh_is_serialized(self):
        current = session(); client = CloudClient(current)
        with patch.object(client, '_request', side_effect=[(401,b''), (200,b'ok')]) as send, \
             patch('app.services.cloudbase_login.refresh_session', side_effect=lambda *a: renewed()) as refresh:
            self.assertEqual(client.request('/test','POST',b'body'), (200,b'ok'))
            self.assertEqual([c.args[-1] for c in send.call_args_list], ['ACCESS_OLD','ACCESS_NEW'])
            self.assertTrue(all(c.args[2] == b'body' for c in send.call_args_list)); refresh.assert_called_once()
        with patch.object(client, '_request', return_value=(403,b'')) as send, \
             patch('app.services.cloudbase_login.refresh_session') as refresh:
            self.assertEqual(client.request('/test','GET')[0],403); send.assert_called_once(); refresh.assert_not_called()
        current.expires_at=0; results=[]
        with patch('app.services.cloudbase_login.refresh_session', side_effect=lambda *a: renewed()) as refresh:
            threads=[threading.Thread(target=lambda: results.append(current.require_token())) for _ in range(4)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(results, ['ACCESS_NEW']*4); refresh.assert_called_once()


if __name__ == '__main__': unittest.main()
