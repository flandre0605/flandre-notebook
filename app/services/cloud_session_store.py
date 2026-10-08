"""Refresh credentials in the OS vault; only an account selector in QSettings."""
import hashlib
import json
from pathlib import Path
import re

from PySide6.QtCore import QSettings
from app.services import credentials
from app.services.cloud_sync import CloudSession, ENVIRONMENT_ID


class CloudSessionStore:
    def __init__(self, root):
        self.scope = hashlib.sha256((str(Path(root).resolve()).casefold() + ENVIRONMENT_ID).encode()).hexdigest()
        self.settings = QSettings('FlandreNotebook', 'CloudSessions')

    def reference(self, uid):
        if not isinstance(uid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', uid):
            raise RuntimeError('保存的账号信息无效，请重新登录。')
        return f'cloud-refresh:{self.scope}:{uid}'

    def save(self, session):
        value = dict(environment=ENVIRONMENT_ID, user_id=session.user_id, username=session.username,
                     device=session.device_id, refresh_token=session.refresh_token)
        try:
            credentials.save_api_key(self.reference(session.user_id), json.dumps(value))
            self.settings.setValue(self.scope, session.user_id)
            self.settings.sync()
            if self.settings.status() != QSettings.Status.NoError:
                raise RuntimeError()
        except Exception:
            raise RuntimeError('登录状态未能安全保存，请检查系统凭据存储。密码不会保存。') from None

    def load_last(self):
        uid = self.settings.value(self.scope, '')
        if not uid:
            return None
        try:
            value = json.loads(credentials.get_api_key(self.reference(uid)))
            if (value.get('environment') != ENVIRONMENT_ID or value.get('user_id') != uid
                    or not isinstance(value.get('username'), str)
                    or not isinstance(value.get('device'), str) or not 1 <= len(value['device']) <= 128
                    or not isinstance(value.get('refresh_token'), str) or not 1 <= len(value['refresh_token']) <= 4096):
                raise ValueError()
            session = CloudSession(dict(user_id=uid, access_token='', expires_in=0,
                                        refresh_token=value['refresh_token']), value['username'], value['device'])
            session._store = self
            return session
        except Exception:
            raise RuntimeError('无法恢复安全保存的登录，请重新登录。原账号题库仍保留。') from None

    def clear(self, uid):
        # Remove the selector first: even if the OS vault is unavailable, do not restore this login.
        if self.settings.value(self.scope, '') == uid:
            self.settings.remove(self.scope)
            self.settings.sync()
        try:
            credentials.delete_api_key(self.reference(uid))
        except Exception:
            raise RuntimeError('已停止恢复此账号，但系统凭据清理失败，请检查 Windows 凭据管理器。') from None
