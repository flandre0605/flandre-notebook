"""Meaningful auth-probe checks; no live credentials or network requests."""
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.cloudbase_login import (LoginCheckError, _NoRedirect, validate_login,
    send_registration_code, registration_fields)


class LoginCheckTests(unittest.TestCase):
    def test_login_uses_fixed_https_host_and_returns_no_credentials(self):
        payload = dict(token_type="Bearer", access_token="SECRET_ACCESS",
                       refresh_token="SECRET_REFRESH", expires_in=7200, sub="12345")
        with patch("app.services.cloudbase_login.urllib.request.build_opener") as build:
            build.return_value.open.return_value = BytesIO(json.dumps(payload).encode())
            result = validate_login("test-env", " test_a ", "SECRET_PASSWORD", "stable-device")
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://test-env.api.tcloudbasegateway.com/auth/v1/signin")
            self.assertEqual(json.loads(request.data), {"username": "test_a", "password": "SECRET_PASSWORD"})
            self.assertEqual(request.get_header("X-device-id"), "stable-device")
            self.assertEqual(result, {"user_id": "12345", "expires_in": 7200})
            self.assertNotIn("SECRET", str(result))
            build.return_value.open.assert_called_once()

    def test_server_error_never_echoes_secrets_or_retries(self):
        for code in ("invalid_username_or_password", "unknown_error"):
            body = json.dumps(dict(error=code, error_description="SECRET_PASSWORD SECRET_ACCESS")).encode()
            error = urllib.error.HTTPError("https://test", 400, "failure", {}, BytesIO(body))
            with self.subTest(code=code), patch("app.services.cloudbase_login.urllib.request.build_opener") as build:
                build.return_value.open.side_effect = error
                with self.assertRaises(LoginCheckError) as raised:
                    validate_login("test-env", "test_a", "SECRET_PASSWORD", "device")
                self.assertNotIn("SECRET", str(raised.exception))
                build.return_value.open.assert_called_once()

    def test_incomplete_success_is_rejected(self):
        with patch("app.services.cloudbase_login.urllib.request.build_opener") as build:
            build.return_value.open.return_value = BytesIO(b'{"sub":"12345","expires_in":7200}')
            with self.assertRaises(LoginCheckError):
                validate_login("test-env", "test_a", "password", "device")

    def test_redirect_cannot_forward_password(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://elsewhere"))

    def test_environment_cannot_be_changed_to_arbitrary_url(self):
        with patch("app.services.cloudbase_login.urllib.request.build_opener") as build:
            with self.assertRaises(LoginCheckError):
                validate_login("https://elsewhere", "test_a", "password", "device")
            build.assert_not_called()

    def test_verified_email_registration_returns_existing_session_shape(self):
        responses = [dict(verification_id='email-bound', expires_in=600),
                     dict(verification_token='verification-secret', expires_in=600),
                     dict(token_type='Bearer', access_token='memory-only', refresh_token='discarded',
                          expires_in=7200, sub='new-user')]
        with patch('app.services.cloudbase_login.urllib.request.build_opener') as build:
            build.return_value.open.side_effect = [BytesIO(json.dumps(r).encode()) for r in responses]
            challenge = send_registration_code('test-env', ' test@example.com ', 'device')
            result = challenge.signup('test-env', 'test@example.com', 'new_user', 'Password123!', '123456', 'device')
            requests = [call.args[0] for call in build.return_value.open.call_args_list]
            self.assertEqual([r.full_url.rsplit('/auth/v1/', 1)[1] for r in requests],
                             ['verification', 'verification/verify', 'signup'])
            self.assertEqual(json.loads(requests[0].data), {'email':'test@example.com', 'target':'ANY'})
            self.assertEqual(json.loads(requests[1].data), {'verification_id':'email-bound', 'verification_code':'123456'})
            self.assertEqual(json.loads(requests[2].data), {'email':'test@example.com', 'username':'new_user',
                'password':'Password123!', 'verification_token':'verification-secret'})
            self.assertTrue(all(r.get_header('X-device-id') == 'device' for r in requests))
            self.assertEqual(result, {'user_id':'new-user', 'access_token':'memory-only', 'expires_in':7200, 'refresh_token':'discarded'})
            with self.assertRaises(LoginCheckError):
                challenge.signup('test-env', challenge.email, 'new_user', 'Password123!', '123456', 'device')
            self.assertEqual(build.return_value.open.call_count, 3, 'consumed challenge must not resend')

    def test_registration_rejects_changed_email_expiry_and_invalid_input_before_network(self):
        with patch('app.services.cloudbase_login.urllib.request.build_opener') as build:
            build.return_value.open.return_value = BytesIO(b'{"verification_id":"email-bound","expires_in":600}')
            challenge = send_registration_code('test-env', 'test@example.com', 'device')
            for email, name, password, code in [('other@example.com','new_user','Password123!','123456'),
                (challenge.email,'x','Password123!','123456'), (challenge.email,'new_user','short','123456'),
                (challenge.email,'new_user','Password123!','abc123')]:
                with self.assertRaises(LoginCheckError):
                    challenge.signup('test-env', email, name, password, code, 'device')
            challenge.deadline = 0
            with self.assertRaises(LoginCheckError):
                challenge.signup('test-env', challenge.email, 'new_user', 'Password123!', '123456', 'device')
            self.assertEqual(build.return_value.open.call_count, 1)
            with self.assertRaises(LoginCheckError):
                registration_fields('bad-email')

    def test_registration_errors_are_safe_and_not_retried(self):
        for response in [dict(is_user=True, verification_id='unused', expires_in=600),
            dict(error='rate_limit_exceeded', error_description='SECRET'),
            dict(error='captcha_required', error_description='SECRET'),
            dict(error='unimplemented', error_description='SECRET'), dict(verification_id='', expires_in=600)]:
            with patch('app.services.cloudbase_login.urllib.request.build_opener') as build:
                build.return_value.open.return_value = BytesIO(json.dumps(response).encode())
                with self.assertRaises(LoginCheckError) as raised:
                    send_registration_code('test-env', 'test@example.com', 'device')
                self.assertNotIn('SECRET', str(raised.exception))
                build.return_value.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
