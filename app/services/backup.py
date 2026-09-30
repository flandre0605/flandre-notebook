import json
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.database import store
from app.services.attachments import ATTACHMENTS_DIR


MAX_BACKUP_BYTES = 5 * 1024 * 1024 * 1024


def create_backup(destination: str | Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mistakebook-backup-") as temporary:
        database_copy = Path(temporary) / "questions.db"
        with closing(sqlite3.connect(store.DATABASE_PATH)) as source, closing(
            sqlite3.connect(database_copy)
        ) as target:
            source.backup(target)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(database_copy, "database.sqlite3")
            if ATTACHMENTS_DIR.exists():
                for file in ATTACHMENTS_DIR.rglob("*"):
                    if file.is_file():
                        archive.write(
                            file,
                            f"attachments/{file.relative_to(ATTACHMENTS_DIR).as_posix()}",
                        )
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": 1,
                        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    },
                    ensure_ascii=False,
                ),
            )
    return destination


def _safe_archive_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if "\\" in name or path.is_absolute() or ".." in path.parts:
        raise ValueError("备份包含不安全的文件路径。")
    if name not in {"database.sqlite3", "manifest.json", "attachments/"} and not name.startswith(
        "attachments/"
    ):
        raise ValueError("备份包含未知文件。")
    return path


def restore_backup(source: str | Path) -> Path:
    source = Path(source)
    store.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mistakebook-restore-", dir=store.DATA_DIR) as temporary:
        staging = Path(temporary)
        staged_db = staging / "questions.db"
        staged_attachments = staging / "attachments"
        staged_attachments.mkdir()

        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            names = set()
            total_size = 0
            for info in infos:
                _safe_archive_name(info.filename)
                if info.filename in names:
                    raise ValueError("备份中有重复文件名。")
                names.add(info.filename)
                total_size += info.file_size
                if total_size > MAX_BACKUP_BYTES:
                    raise ValueError("备份解压后的总大小超过 5 GB。")
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError("备份中不能包含符号链接。")
            if "database.sqlite3" not in names:
                raise ValueError("备份缺少题库数据库。")

            for info in infos:
                if info.is_dir() or info.filename == "manifest.json":
                    continue
                if info.filename == "database.sqlite3":
                    target = staged_db
                else:
                    relative = PurePosixPath(info.filename).relative_to("attachments")
                    if not relative.parts:
                        continue
                    target = staged_attachments.joinpath(*relative.parts)
                    if not target.resolve().is_relative_to(staged_attachments.resolve()):
                        raise ValueError("备份包含不安全的附件路径。")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as input_file, target.open("wb") as output_file:
                    shutil.copyfileobj(input_file, output_file)

        with closing(sqlite3.connect(staged_db)) as database:
            result = database.execute("PRAGMA integrity_check").fetchone()[0]
            version = database.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if result != "ok" or "questions" not in tables:
                raise ValueError("备份数据库损坏或格式无效。")
            if version < 1 or version > store.SCHEMA_VERSION:
                raise ValueError("备份数据库版本不兼容，请使用相同版本的应用恢复。")
        if version < store.SCHEMA_VERSION:
            store.initialize(staged_db)
        with closing(sqlite3.connect(staged_db)) as database:
            for (relative_path,) in database.execute("SELECT relative_path FROM attachments"):
                relative = PurePosixPath(relative_path)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not relative.parts
                    or relative.parts[0] != "attachments"
                ):
                    raise ValueError("备份数据库包含无效附件路径。")
                if not staged_attachments.joinpath(*relative.parts[1:]).is_file():
                    raise ValueError("备份缺少题目引用的图片附件。")

        recovery = store.DATA_DIR / f"pre-restore-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}.zip"
        create_backup(recovery)
        old_attachments = store.DATA_DIR / f"attachments-old-{uuid4().hex}"
        had_attachments = ATTACHMENTS_DIR.exists()
        if had_attachments:
            ATTACHMENTS_DIR.rename(old_attachments)
        try:
            staged_attachments.rename(ATTACHMENTS_DIR)
            os.replace(staged_db, store.DATABASE_PATH)
        except Exception:
            if ATTACHMENTS_DIR.exists():
                shutil.rmtree(ATTACHMENTS_DIR, ignore_errors=True)
            if had_attachments and old_attachments.exists():
                old_attachments.rename(ATTACHMENTS_DIR)
            raise
        if old_attachments.exists():
            shutil.rmtree(old_attachments, ignore_errors=True)
        return recovery
