"""Launch each account in its own process: no global data-path changes mid-task."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from app.services.cloud_sync import ENVIRONMENT_ID


def account_directory(guest_root, user_id):
    guest_root = Path(guest_root).resolve()
    accounts = guest_root.parent / (guest_root.name + '-accounts')
    name = hashlib.sha256((ENVIRONMENT_ID + ':' + user_id).encode()).hexdigest()
    target = accounts / name
    if not target.resolve().is_relative_to(guest_root.parent.resolve()) or not target.resolve().is_relative_to(accounts):
        raise ValueError('账号目录包含外部链接，未打开。')
    return target


def open_account(guest_root):
    arguments = ['--cloud', '--foreground', '--workspace-root', str(Path(guest_root).resolve())]
    if getattr(sys, 'frozen', False):
        command = [sys.executable, *arguments]
    else:
        executable = Path(sys.executable)
        if sys.platform == 'win32' and executable.with_name('pythonw.exe').is_file():
            executable = executable.with_name('pythonw.exe')
        command = [str(executable), str(Path(__file__).resolve().parents[2] / 'main.py'), *arguments]
    subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[2]),
                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
