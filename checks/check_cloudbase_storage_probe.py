"""Simulated storage checks; hosted policies still require real user testing."""
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import cloudbase_storage_probe as probe


def session_for(environment, username, password, device):
    label = 'B' if username == 'test_b' else 'A'
    return {'user_id': 'USER_' + label, 'access_token': 'TOKEN_' + label, 'expires_in': 7200}


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def request(self, environment, method, token, key, body=None, sign=False):
        self.calls.append((method, token, key, sign))
        user = {'TOKEN_A': 'USER_A', 'TOKEN_B': 'USER_B'}.get(token)
        if key.split('/')[0] != user:
            return (404, b'') if method in ('GET', 'DELETE') else (403, b'')
        if sign:
            return (200, b'{"signedURL":"/secret-link?token=SIGNED_SECRET"}') if key in self.objects else (404, b'')
        if method == 'POST':
            self.objects[key] = body
            return 200, json.dumps({'Id': 'random-id', 'Key': probe.BUCKET_ID + '/' + key}).encode()
        if key not in self.objects:
            return 404, b''
        if method == 'GET':
            return 200, self.objects[key]
        if method == 'PUT':
            self.objects[key] = body
            return 200, b'{}'
        if method == 'DELETE':
            del self.objects[key]
            return 200, b'{}'
        raise AssertionError(method)


class StorageTests(unittest.TestCase):
    def run_probe(self, store, second=True):
        with patch.object(probe, 'login_session', side_effect=session_for), \
                patch.object(probe, '_request', side_effect=store.request):
            return probe.verify_storage('test-env', 'test_a', 'PASSWORD_A', 'device',
                                        'test_b' if second else '', 'PASSWORD_B' if second else '')

    def test_two_accounts_download_exact_bytes_and_cross_operations_are_exercised(self):
        store = FakeStorage()
        store.objects['USER_A/existing.png'] = b'Keep existing file'
        result = self.run_probe(store)
        self.assertEqual(store.objects, {'USER_A/existing.png': b'Keep existing file'})
        self.assertTrue(any('均被阻止' in line for line in result['checks']))
        for token, target in (('TOKEN_A', 'USER_B/'), ('TOKEN_B', 'USER_A/')):
            for method, sign in (('GET', False), ('PUT', False), ('DELETE', False), ('POST', True), ('POST', False)):
                self.assertTrue(any(m == method and t == token and k.startswith(target) and s == sign
                                    for m, t, k, s in store.calls))
        for secret in ('TOKEN_A', 'PASSWORD_A', 'SIGNED_SECRET'):
            self.assertNotIn(secret, str(result))

    def test_single_account_does_not_claim_multiuser_success(self):
        store = FakeStorage()
        result = self.run_probe(store, second=False)
        self.assertFalse(store.objects)
        self.assertTrue(any('待验证' in line for line in result['checks']))

    def test_same_account_rejected_before_storage_access(self):
        with patch.object(probe, 'login_session', side_effect=session_for), patch.object(probe, '_request') as request:
            with self.assertRaisesRegex(probe.StorageProbeError, '账号相同'):
                probe.verify_storage('test-env', 'test_a', 'A', 'device', 'test_a', 'A')
            request.assert_not_called()

    def test_public_download_leak_fails_and_cleans_current_files(self):
        store = FakeStorage()
        original = store.request
        def request(environment, method, token, key, body=None, sign=False):
            if method == 'GET' and token is None:
                return 200, store.objects[key]
            return original(environment, method, token, key, body, sign)
        store.request = request
        with self.assertRaisesRegex(probe.StorageProbeError, '无凭据'):
            self.run_probe(store)
        self.assertFalse(store.objects)

    def test_corrupted_download_fails(self):
        store = FakeStorage()
        original = store.request
        def request(environment, method, token, key, body=None, sign=False):
            status, data = original(environment, method, token, key, body, sign)
            return (status, b'CORRUPTED') if method == 'GET' and status == 200 else (status, data)
        store.request = request
        with self.assertRaisesRegex(probe.StorageProbeError, '不一致'):
            self.run_probe(store)
        self.assertFalse(store.objects)

    def test_other_user_can_sign_is_not_counted_as_isolated(self):
        store = FakeStorage()
        original = store.request
        def request(environment, method, token, key, body=None, sign=False):
            if sign and token == 'TOKEN_A' and key.startswith('USER_B/'):
                return 200, b'{"signedURL":"SIGNED_SECRET"}'
            return original(environment, method, token, key, body, sign)
        store.request = request
        with self.assertRaisesRegex(probe.StorageProbeError, '临时链接') as error:
            self.run_probe(store)
        self.assertNotIn('SIGNED_SECRET', str(error.exception))
        self.assertFalse(store.objects)

    def test_missing_bucket_and_cleanup_failure_never_report_success(self):
        with patch.object(probe, 'login_session', side_effect=session_for), \
                patch.object(probe, '_request', return_value=(404, b'')):
            with self.assertRaisesRegex(probe.StorageProbeError, '测试桶脚本'):
                probe.verify_storage('test-env', 'test_a', 'A', 'device')
        store = FakeStorage()
        original = store.request
        def request(environment, method, token, key, body=None, sign=False):
            return (503, b'RAW_SECRET') if method == 'DELETE' else original(environment, method, token, key, body, sign)
        store.request = request
        with self.assertRaisesRegex(probe.StorageProbeError, '未确认清理') as error:
            self.run_probe(store, second=False)
        self.assertNotIn('RAW_SECRET', str(error.exception))

    def test_request_confined_to_test_path_and_never_redirects(self):
        key = 'USER_A/flandre-probe-' + 'a' * 32 + '.png'
        response = BytesIO(b'{}')
        response.status = 200
        with patch.object(probe.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = response
            probe._request('test-env', 'POST', 'TOKEN_A', key, b'IMAGE')
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://test-env.api.tcloudbasegateway.com/v1/storages/object/'
                             + probe.BUCKET_ID + '/' + key)
            self.assertEqual(request.get_header('Authorization'), 'Bearer TOKEN_A')
            self.assertEqual(request.get_header('Content-type'), 'image/png')
            self.assertIsInstance(build.call_args.args[0], probe._NoRedirect)
            build.return_value.open.assert_called_once()
        for unsafe in ('../existing.png', 'USER_A/existing.png', 'USER_A/flandre-probe-other.png'):
            with self.assertRaises(probe.StorageProbeError):
                probe._request('test-env', 'DELETE', 'TOKEN_A', unsafe)

    def test_unknown_error_is_not_permission_evidence(self):
        for response in ((400, b'{"code":"INVALID_PARAM"}'), (500, b'error'), (200, b'{}')):
            with self.assertRaises(probe.StorageProbeError):
                probe._blocked(response, '检查')


if __name__ == '__main__':
    unittest.main()
