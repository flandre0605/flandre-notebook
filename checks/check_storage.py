"""Temporary-data acceptance for storage migration and startup orchestration."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import shutil
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QImage
from app import paths
from app.database import store
from app.services import attachments, backup, recognition_drafts, storage


def rejects(call):
    try:
        call()
    except (OSError, ValueError, sqlite3.Error):
        return
    raise AssertionError("Invalid migration was accepted")


def check():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        old = root / "旧版本 data"
        target = root / "新版本 data"
        database = old / "questions.db"
        connection = store._connection
        store.initialize(database)
        with patch.object(store, "_connection", lambda path=database: connection(path)), \
             patch.object(store, "DATA_DIR", old), \
             patch.object(attachments, "ATTACHMENTS_DIR", old / "attachments"):
            question = store.save_question(dict(stem="Migration", subject="English", answer="A",
                                               question_type="单选题", options={"A": "yes", "B": "no"}))
            image = QImage(30, 20, QImage.Format.Format_RGB32)
            image.fill(0xffffff)
            original = root / "original.png"
            assert image.save(str(original))
            attachments.import_image(question, original)
            key, state, _ = recognition_drafts.create(original, "test-profile")
            state["drafts"] = [dict(stem="Unconfirmed", options={})]
            recognition_drafts.save(key, state)
            store.save_workspace("vocabulary:import", dict(rows=[dict(word="pending")]))
        before = database.read_bytes()
        (old / "tools").mkdir()
        (old / "tools" / "private-token.txt").write_text("do not migrate", encoding="utf-8")
        (old / "pre-restore-example.zip").write_bytes(b"backup")
        assert paths.prepare_data_directory(backup.validate_data_directory, target, old)
        assert database.read_bytes() == before
        assert not (target / "tools").exists()
        assert (target / "pre-restore-example.zip").read_bytes() == b"backup"
        assert json.loads((target / "migration.json").read_text(encoding="utf-8"))["source"] == str(old.resolve())
        with connection(target / "questions.db") as db:
            assert db.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
            payload = json.loads(db.execute("SELECT payload FROM workspace_state WHERE key=?", (key,)).fetchone()[0])
            recognition_drafts.validate_state(key, payload, target / "attachments")
            assert db.execute("SELECT COUNT(*) FROM workspace_state").fetchone()[0] == 2
        # Repeated startup uses the already migrated database; no merge or overwrite.
        migrated_before = (target / "questions.db").read_bytes()
        assert not paths.prepare_data_directory(backup.validate_data_directory, target, old)
        assert (target / "questions.db").read_bytes() == migrated_before
        blank = root / "blank"
        assert not paths.prepare_data_directory(backup.validate_data_directory, blank, root / "absent")
        assert blank.is_dir()
        same = paths.prepare_data_directory(backup.validate_data_directory, old, old)
        assert not same and database.read_bytes() == before
        occupied = root / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_text("keep", encoding="utf-8")
        rejects(lambda: paths.prepare_data_directory(backup.validate_data_directory, occupied, old))
        assert (occupied / "keep.txt").read_text(encoding="utf-8") == "keep"
        rejects(lambda: paths.prepare_data_directory(backup.validate_data_directory, old / "nested", old))
        # Missing originals and copy failures leave the source and target untouched.
        draft_image = recognition_drafts.image_file(key, state, old / "attachments")
        draft_bytes = draft_image.read_bytes()
        draft_image.unlink()
        failed_target = root / "failed"
        rejects(lambda: paths.prepare_data_directory(backup.validate_data_directory, failed_target, old))
        assert not failed_target.exists() and database.read_bytes() == before
        draft_image.write_bytes(draft_bytes)
        with patch("app.paths.shutil.copytree", side_effect=PermissionError("denied")):
            rejects(lambda: paths.prepare_data_directory(backup.validate_data_directory, failed_target, old))
        assert not failed_target.exists() and not list(root.glob(".flandre-migration-*"))
        # Windows directory junctions must not import an outside tree as attachments.
        if sys.platform == "win32":
            external = root / "external"
            external.mkdir()
            linked = root / "linked"
            linked.mkdir()
            shutil.copy2(database, linked / "questions.db")
            import subprocess
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "New-Item -ItemType Junction -Path $env:FLANDRE_LINK -Target $env:FLANDRE_TARGET | Out-Null"],
                           env={**os.environ, "FLANDRE_LINK": str(linked / "attachments"),
                                "FLANDRE_TARGET": str(external)}, check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                rejects(lambda: paths.prepare_data_directory(backup.validate_data_directory, failed_target, linked))
                assert not failed_target.exists()
            finally:
                (linked / "attachments").rmdir()  # Remove only our junction, never its target tree.
        # Old schemas upgrade only in the staged copy.
        older = root / "v1"
        older.mkdir()
        with closing(sqlite3.connect(older / "questions.db")) as db, db:
            db.execute("CREATE TABLE questions (id INTEGER PRIMARY KEY, stem TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '', question_type TEXT NOT NULL DEFAULT '', answer TEXT NOT NULL DEFAULT '', explanation TEXT NOT NULL DEFAULT '', is_wrong INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO questions(stem) VALUES('old')")
            db.execute("PRAGMA user_version=1")
        assert paths.prepare_data_directory(backup.validate_data_directory, root / "upgraded", older)
        with connection(older / "questions.db") as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        with connection(root / "upgraded" / "questions.db") as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
            assert db.execute("SELECT stem,options FROM questions").fetchone()[:] == ("old", "{}")
        # Explicit startup override stays isolated from the real default directory.
        fresh = root / "fresh"
        with patch.object(store, "DATA_DIR", fresh), patch.object(store, "DATABASE_PATH", fresh / "questions.db"), \
             patch("app.services.storage.prepare_data_directory", side_effect=lambda validate, target: paths.prepare_data_directory(validate, target, root / "absent")):
            assert not storage.initialize_storage()
            assert (fresh / "questions.db").is_file()
        with patch.dict(os.environ, {"FLANDRE_DATA_DIR": str(fresh)}):
            assert paths.user_data_dir() == fresh.resolve()
            isolated = root / "isolated"
            with patch.object(paths, "LEGACY_DATA_DIR", old):
                assert not paths.prepare_data_directory(backup.validate_data_directory, isolated)
            assert isolated.is_dir() and not (isolated / "questions.db").exists()
        with patch.dict(os.environ, {"FLANDRE_DATA_DIR": "relative"}):
            rejects(paths.user_data_dir)
    print("Storage migration checks passed (temporary data only).")


if __name__ == "__main__":
    check()
