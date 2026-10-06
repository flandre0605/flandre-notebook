"""Probe-client checks with simulated responses, not proof of hosted RLS."""
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.cloudbase_probe import ProbeError, _blocked, _request, verify_database


class FakeDatabase:
    def __init__(self):
        self.rows = {}
        self.calls = []

    def request(self, environment, method, token, row_id=None, data=None):
        self.calls.append((method, token, row_id))
        if token is None:
            return 401, None
        user_id = {"TOKEN_A": "USER_A", "TOKEN_B": "USER_B"}[token]
        if method == "POST":
            if data.get("user_id", user_id) != user_id:
                return 403, None
            row = dict(data, user_id=user_id)
            self.rows[row["id"]] = row
            return 201, [dict(row)]
        if row_id is None:
            return 200, [dict(row) for row in self.rows.values() if row["user_id"] == user_id]
        row = self.rows.get(row_id)
        if not row or row["user_id"] != user_id:
            return 200, []
        if method == "PATCH":
            row.update(data)
        result = dict(row)
        if method == "DELETE":
            del self.rows[row_id]
        return 200, [result]


def session_for(environment, username, password, device):
    label = "B" if username == "test_b" else "A"
    return {"user_id": "USER_" + label, "access_token": "TOKEN_" + label, "expires_in": 7200}


class ProbeTests(unittest.TestCase):
    def test_single_account_leaves_multiuser_pending_and_cleans_only_its_random_records(self):
        db = FakeDatabase()
        db.rows["existing"] = dict(id="existing", user_id="USER_A", note="Keep me")
        with patch("app.services.cloudbase_probe.login_session", side_effect=session_for), \
                patch("app.services.cloudbase_probe._request", side_effect=db.request):
            result = verify_database("test-env", "test_a", "SECRET", "device")
        self.assertEqual(list(db.rows), ["existing"])
        self.assertTrue(any("待验证" in line for line in result["checks"]))
        self.assertNotIn("TOKEN", str(result))
        self.assertNotIn("SECRET", str(result))

    def test_two_accounts_exercise_bidirectional_read_write_delete(self):
        db = FakeDatabase()
        with patch("app.services.cloudbase_probe.login_session", side_effect=session_for), \
                patch("app.services.cloudbase_probe._request", side_effect=db.request):
            result = verify_database("test-env", "test_a", "SECRET_A", "device", "test_b", "SECRET_B")
        self.assertFalse(db.rows)
        self.assertTrue(any("两个账号：" in line for line in result["checks"]))
        self.assertFalse(any("待验证" in line for line in result["checks"]))
        for token in ("TOKEN_A", "TOKEN_B"):
            for operation in ("GET", "PATCH", "DELETE"):
                self.assertTrue(any(method == operation and caller == token for method, caller, _ in db.calls))

    def test_query_returning_another_users_data_never_reports_success(self):
        db = FakeDatabase()
        def leaking(environment, method, token, row_id=None, data=None):
            if method == "GET" and row_id is None:
                return 200, [dict(id="other", user_id="USER_B", note="Other account")]
            return db.request(environment, method, token, row_id, data)
        with patch("app.services.cloudbase_probe.login_session", side_effect=session_for), \
                patch("app.services.cloudbase_probe._request", side_effect=leaking):
            with self.assertRaisesRegex(ProbeError, "其他账号"):
                verify_database("test-env", "test_a", "SECRET", "device")
        self.assertFalse(db.rows)

    def test_same_account_cannot_count_as_multiuser_evidence(self):
        with patch("app.services.cloudbase_probe.login_session", side_effect=session_for), \
                patch("app.services.cloudbase_probe._request") as request:
            with self.assertRaisesRegex(ProbeError, "账号相同"):
                verify_database("test-env", "test_a", "SECRET", "device", "test_a", "SECRET")
            request.assert_not_called()

    def test_missing_table_and_returned_rows_are_not_permission_denials(self):
        for response in ((404, None), (200, [{"id": "someone-elses-row"}]), (201, [])):
            with self.subTest(response=response), self.assertRaises(ProbeError):
                _blocked(response, "隔离验证", allow_empty=True)

    def test_http_request_targets_only_probe_table_and_uses_user_token(self):
        response = BytesIO(json.dumps([]).encode())
        response.status = 200
        with patch("app.services.cloudbase_probe.urllib.request.build_opener") as build:
            build.return_value.open.return_value = response
            self.assertEqual(_request("test-env", "GET", "TOKEN_A", "record"), (200, []))
            request = build.return_value.open.call_args.args[0]
            self.assertIn("/v1/rdb/rest/v1/flandre_connection_probe?", request.full_url)
            self.assertEqual(request.get_header("Authorization"), "Bearer TOKEN_A")
            build.return_value.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
