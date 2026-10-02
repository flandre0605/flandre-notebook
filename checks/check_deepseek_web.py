"""Local bridge settings check; temporary DB, mocked credentials, no login requests."""
import os
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch, MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from app.database import store
from app.services import credentials, deepseek_web, model_provider
from app.ui.profiles_dialog import ProfilesDialog


def check():
    app = QApplication.instance() or QApplication([])
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "questions.db"
        store.initialize(database)
        keys = {}
        with patch.object(store, "_connection", lambda: connection(database)), patch.object(
            credentials, "has_api_key", side_effect=lambda ref: ref in keys
        ), patch.object(credentials, "save_api_key", side_effect=lambda ref, value: keys.update({ref: value})), patch.object(
            credentials, "get_api_key", side_effect=lambda ref: keys[ref]
        ):
            key = deepseek_web.local_key()
            assert key == deepseek_web.local_key() and len(key) > 30
            store.save_profile(dict(name="原有服务", base_url="https://example.com/v1", model_id="old",
                                    endpoint_path="/chat/completions", timeout_seconds=60,
                                    enabled=True, vision_enabled=True), "existing")
            dialog = ProfilesDialog()
            dialog._web_started(key)
            dialog._web_started(key)
            rows = store.list_profiles()
            assert len(rows) == 2 and store.get_profile("existing")["model_id"] == "old"
            profile = next(row for row in rows if row["name"] == "DeepSeek 网页版（本机）")
            assert profile["base_url"] == "http://127.0.0.1:4000/v1"
            assert profile["vision_enabled"] and profile["model_id"] == "v4.1flash"
            assert keys[profile["api_key_ref"]] == key and "尚未验证网页账号" in dialog.connection_status.text()
            messages = [{"role": "system", "content": "识别图片"}, {"role": "user", "content": [
                {"type": "text", "text": "按题目拆分"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,one"}},
            ]}]
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(
                {"choices": [{"message": {"content": "OK"}}]}
            ).encode()
            with patch.object(model_provider, "get_api_key", side_effect=lambda ref: keys[ref]), patch.object(
                model_provider.urllib.request, "urlopen", return_value=response
            ) as request:
                for _ in range(3):
                    model_provider._request(profile, messages)
                bodies = [json.loads(call.args[0].data) for call in request.call_args_list]
                identifiers = [body["messages"][0]["content"] for body in bodies]
                assert len(set(identifiers)) == 3
                assert all(body["messages"][1:] == messages for body in bodies)
                assert messages[0]["content"] == "识别图片"
                # Explicit conversation history still keeps its intended continuity.
                history = [*messages, {"role": "assistant", "content": "上次回答"}, {"role": "user", "content": "继续"}]
                model_provider._request(profile, history)
                assert json.loads(request.call_args.args[0].data)["messages"] == history
                remote = dict(profile)
                remote["base_url"] = "https://example.com/v1"
                model_provider._request(remote, messages)
                assert json.loads(request.call_args.args[0].data)["messages"] == messages
            dialog._copy_web_password()
            assert QApplication.clipboard().text() == key
            QApplication.clipboard().clear()
            dialog.close()
    print("PASS: stable local credential, repeat setup without duplicates, existing profile preserved, account readiness message")


if __name__ == "__main__":
    check()
