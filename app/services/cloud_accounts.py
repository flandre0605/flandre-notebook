"""Account directory identity; switching is handled by the existing main window."""
import hashlib
from pathlib import Path

from app.services.cloud_sync import ENVIRONMENT_ID


def account_directory(guest_root, user_id):
    guest_root = Path(guest_root).resolve()
    accounts = guest_root.parent / (guest_root.name + '-accounts')
    name = hashlib.sha256((ENVIRONMENT_ID + ':' + user_id).encode()).hexdigest()
    target = accounts / name
    if not target.resolve().is_relative_to(guest_root.parent.resolve()) or not target.resolve().is_relative_to(accounts):
        raise ValueError('账号目录包含外部链接，未打开。')
    return target
