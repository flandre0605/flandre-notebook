"""Application resources and persistent user data have separate lifetimes."""
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_DATA_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                   else PROJECT_ROOT) / "data"


def user_data_dir():
    override = os.environ.get("FLANDRE_DATA_DIR", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError("FLANDRE_DATA_DIR 必须为绝对路径。")
        return path.resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "FlandreNotebook" / "data"


DATA_DIR = user_data_dir()


def prepare_data_directory(validate, target=None, legacy=None):
    """Copy legacy learning data once, validate in staging, then publish together."""
    target = Path(target) if target is not None else DATA_DIR
    if legacy is None and os.environ.get("FLANDRE_DATA_DIR", "").strip():
        target.mkdir(parents=True, exist_ok=True)
        return ""  # An explicitly selected workspace must not import the default user's data.
    legacy = Path(legacy) if legacy is not None else LEGACY_DATA_DIR
    if target.resolve() == legacy.resolve() or (target / "questions.db").exists():
        return ""
    if not (legacy / "questions.db").is_file():
        target.mkdir(parents=True, exist_ok=True)
        return ""
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"新数据目录已有文件但没有题库，未覆盖。请先整理目录或使用 ZIP 恢复：{target}")
    if target.resolve().is_relative_to(legacy.resolve()) or legacy.resolve().is_relative_to(target.resolve()):
        raise ValueError("新旧数据目录不能相互包含。")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".flandre-migration-", dir=target.parent) as temporary:
        staged = Path(temporary) / "data"
        staged.mkdir()
        with closing(sqlite3.connect((legacy / "questions.db").resolve().as_uri() + "?mode=ro", uri=True)) as source, \
                closing(sqlite3.connect(staged / "questions.db")) as destination:
            source.backup(destination)
        images = legacy / "attachments"
        if images.exists():
            if images.is_symlink() or not images.resolve().is_relative_to(legacy.resolve()) or any(
                    path.is_symlink() or not path.resolve().is_relative_to(images.resolve())
                    for path in images.rglob("*")):
                raise ValueError("旧图片目录包含外部链接，未迁移；请整理后重试。")
            shutil.copytree(images, staged / "attachments")
        # Only learning backups belong here; an installed bridge environment cannot be relocated.
        for file in legacy.iterdir():
            if file.is_file() and (file.name == "错题本备份.zip" or
                                   file.name.startswith("pre-restore-") and file.suffix.lower() == ".zip"):
                shutil.copy2(file, staged / file.name)
        validate(staged)
        (staged / "migration.json").write_text(json.dumps(dict(
            source=str(legacy.resolve()), migrated_at=datetime.now().astimezone().isoformat(timespec="seconds")
        ), ensure_ascii=False, indent=2), encoding="utf-8")
        if target.exists():
            target.rmdir()  # Refuse a concurrently populated directory instead of replacing it.
        staged.rename(target)
    return "已迁移旧题库、图片与草稿；旧目录中的文件已保留。"
