"""Meaningful auth-probe checks; no live credentials or network requests."""
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.cloudbase_login import LoginCheckError, _NoRedirect, validate_login


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


if __name__ == "__main__":
    unittest.main()
