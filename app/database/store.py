import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "questions.db"
SCHEMA_VERSION = 4


@contextmanager
def _connection(database_path: Path = DATABASE_PATH) -> Iterator[sqlite3.Connection]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(database_path: Path = DATABASE_PATH) -> None:
    with _connection(database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("题库由较新版本创建，请升级应用后再打开。")
        if version < 1:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE questions (
                    id INTEGER PRIMARY KEY,
                    stem TEXT NOT NULL,
                    subject TEXT NOT NULL DEFAULT '',
                    question_type TEXT NOT NULL DEFAULT '',
                    answer TEXT NOT NULL DEFAULT '',
                    explanation TEXT NOT NULL DEFAULT '',
                    is_wrong INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute("PRAGMA user_version = 1")
            version = 1
        if version < 2:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE attachments (
                    id INTEGER PRIMARY KEY,
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute("CREATE INDEX idx_attachments_question_id ON attachments(question_id)")
            connection.execute(
                """CREATE TABLE practice_attempts (
                    id INTEGER PRIMARY KEY,
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    answered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    result TEXT NOT NULL CHECK (result IN ('correct', 'incorrect', 'skipped')),
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    mistake_reason TEXT NOT NULL DEFAULT '',
                    mastery TEXT NOT NULL CHECK (mastery IN ('mastered', 'unsure', 'unknown'))
                )"""
            )
            connection.execute("CREATE INDEX idx_attempts_question_id ON practice_attempts(question_id)")
            connection.execute(
                """CREATE TABLE review_state (
                    question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
                    mastery TEXT NOT NULL CHECK (mastery IN ('mastered', 'unsure', 'unknown')),
                    due_at TEXT NOT NULL,
                    last_reviewed_at TEXT NOT NULL,
                    review_count INTEGER NOT NULL DEFAULT 1
                )"""
            )
            connection.execute("CREATE INDEX idx_review_due_at ON review_state(due_at)")
            connection.execute("PRAGMA user_version = 2")
            version = 2
        if version < 3:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE model_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider_type TEXT NOT NULL DEFAULT 'openai_compatible',
                    base_url TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    timeout_seconds INTEGER NOT NULL DEFAULT 60,
                    vision_enabled INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    api_key_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute("PRAGMA user_version = 3")
            version = 3
        if version < 4:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "ALTER TABLE model_profiles ADD COLUMN endpoint_path TEXT NOT NULL DEFAULT '/chat/completions'"
            )
            connection.execute("PRAGMA user_version = 4")


def _question_conditions(
    search: str, subject: str, question_type: str, state: str, prefix: str = ""
) -> tuple[list[str], list[str]]:
    conditions = [f"{prefix}stem LIKE ?"]
    parameters = [f"%{search}%"]
    if subject:
        conditions.append(f"{prefix}subject = ?")
        parameters.append(subject)
    if question_type:
        conditions.append(f"{prefix}question_type = ?")
        parameters.append(question_type)
    if state == "wrong":
        conditions.append(f"{prefix}is_wrong = 1")
    elif state == "unreviewed":
        conditions.append(f"{prefix}id NOT IN (SELECT question_id FROM review_state)")
    elif state in {"mastered", "unsure", "unknown"}:
        conditions.append(
            f"{prefix}id IN (SELECT question_id FROM review_state WHERE mastery = ?)"
        )
        parameters.append(state)
    return conditions, parameters


def list_questions(
    search: str = "", subject: str = "", question_type: str = "", state: str = "all"
) -> list[sqlite3.Row]:
    conditions, parameters = _question_conditions(search, subject, question_type, state)
    with _connection() as connection:
        return connection.execute(
            f"""SELECT id, stem, subject, question_type, is_wrong, updated_at
                FROM questions WHERE {' AND '.join(conditions)}
                ORDER BY updated_at DESC, id DESC""",
            parameters,
        ).fetchall()


def question_filter_options() -> tuple[list[str], list[str]]:
    with _connection() as connection:
        subjects = connection.execute(
            "SELECT DISTINCT subject FROM questions WHERE subject <> '' ORDER BY subject"
        ).fetchall()
        types = connection.execute(
            "SELECT DISTINCT question_type FROM questions WHERE question_type <> '' ORDER BY question_type"
        ).fetchall()
        return [row[0] for row in subjects], [row[0] for row in types]


def get_question(question_id: int) -> sqlite3.Row | None:
    with _connection() as connection:
        return connection.execute(
            "SELECT * FROM questions WHERE id = ?", (question_id,)
        ).fetchone()


def save_question(question: dict[str, str | int], question_id: int | None = None) -> int:
    stem = question["stem"].strip()
    if not stem:
        raise ValueError("题干不能为空。")

    values = (
        stem,
        question.get("subject", "").strip(),
        question.get("question_type", "").strip(),
        question.get("answer", "").strip(),
        question.get("explanation", "").strip(),
        int(question.get("is_wrong", 0)),
    )
    with _connection() as connection:
        if question_id is None:
            cursor = connection.execute(
                """INSERT INTO questions
                   (stem, subject, question_type, answer, explanation, is_wrong)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                values,
            )
            return int(cursor.lastrowid)

        connection.execute(
            """UPDATE questions
               SET stem = ?, subject = ?, question_type = ?, answer = ?,
                   explanation = ?, is_wrong = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (*values, question_id),
        )
        return question_id


def delete_question(question_id: int) -> None:
    with _connection() as connection:
        connection.execute("DELETE FROM questions WHERE id = ?", (question_id,))


def list_attachments(question_id: int) -> list[sqlite3.Row]:
    with _connection() as connection:
        return connection.execute(
            "SELECT * FROM attachments WHERE question_id = ? ORDER BY id", (question_id,)
        ).fetchall()


def add_attachment(
    question_id: int, relative_path: str, original_name: str, mime_type: str
) -> int:
    with _connection() as connection:
        cursor = connection.execute(
            """INSERT INTO attachments (question_id, relative_path, original_name, mime_type)
               VALUES (?, ?, ?, ?)""",
            (question_id, relative_path, original_name, mime_type),
        )
        return int(cursor.lastrowid)


def delete_attachment(attachment_id: int) -> str | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT relative_path FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()
        if row is None:
            return None
        connection.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        return row["relative_path"]


def practice_questions(
    mode: str,
    search: str = "",
    subject: str = "",
    question_type: str = "",
    state: str = "all",
) -> list[sqlite3.Row]:
    conditions, parameters = _question_conditions(
        search, subject, question_type, state, prefix="q."
    )
    query = "SELECT q.* FROM questions q"
    if mode == "due":
        query += " JOIN review_state r ON r.question_id = q.id"
        conditions.append("r.due_at <= CURRENT_TIMESTAMP")
        order_by = "r.due_at, q.id"
    else:
        if mode == "wrong":
            conditions.append("q.is_wrong = 1")
        order_by = "q.updated_at DESC, q.id DESC"
    with _connection() as connection:
        return connection.execute(
            f"{query} WHERE {' AND '.join(conditions)} ORDER BY {order_by}", parameters
        ).fetchall()


def record_attempt(
    question_id: int,
    result: str,
    duration_seconds: int,
    mastery: str,
    mistake_reason: str = "",
) -> None:
    from datetime import datetime, timedelta, timezone

    intervals = {"mastered": 7, "unsure": 1, "unknown": 0}
    if mastery not in intervals:
        raise ValueError("无效的掌握程度。")
    if result not in {"correct", "incorrect", "skipped"}:
        raise ValueError("无效的作答结果。")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    reviewed_at = now.strftime("%Y-%m-%d %H:%M:%S")
    due_at = (now + timedelta(days=intervals[mastery])).strftime("%Y-%m-%d %H:%M:%S")
    with _connection() as connection:
        connection.execute(
            """INSERT INTO practice_attempts
               (question_id, result, duration_seconds, mistake_reason, mastery)
               VALUES (?, ?, ?, ?, ?)""",
            (question_id, result, max(0, duration_seconds), mistake_reason.strip(), mastery),
        )
        connection.execute(
            """INSERT INTO review_state
               (question_id, mastery, due_at, last_reviewed_at, review_count)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(question_id) DO UPDATE SET
                   mastery = excluded.mastery,
                   due_at = excluded.due_at,
                   last_reviewed_at = excluded.last_reviewed_at,
                   review_count = review_state.review_count + 1""",
            (question_id, mastery, due_at, reviewed_at),
        )
        if result == "incorrect":
            connection.execute("UPDATE questions SET is_wrong = 1 WHERE id = ?", (question_id,))


def list_attempts(limit: int = 500) -> list[sqlite3.Row]:
    with _connection() as connection:
        return connection.execute(
            """SELECT a.answered_at, a.result, a.duration_seconds, a.mistake_reason,
                      a.mastery, q.stem, q.subject
               FROM practice_attempts a
               JOIN questions q ON q.id = a.question_id
               ORDER BY a.id DESC LIMIT ?""",
            (max(1, min(limit, 2000)),),
        ).fetchall()


def list_profiles(enabled_only: bool = False) -> list[sqlite3.Row]:
    query = "SELECT * FROM model_profiles"
    if enabled_only:
        query += " WHERE enabled = 1"
    query += " ORDER BY name, created_at"
    with _connection() as connection:
        return connection.execute(query).fetchall()


def get_profile(profile_id: str) -> sqlite3.Row | None:
    with _connection() as connection:
        return connection.execute(
            "SELECT * FROM model_profiles WHERE id = ?", (profile_id,)
        ).fetchone()


def save_profile(profile: dict, profile_id: str) -> None:
    with _connection() as connection:
        connection.execute(
            """INSERT INTO model_profiles
               (id, name, provider_type, base_url, model_id, timeout_seconds,
                vision_enabled, enabled, api_key_ref, endpoint_path)
               VALUES (?, ?, 'openai_compatible', ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name = excluded.name, base_url = excluded.base_url,
                   model_id = excluded.model_id, timeout_seconds = excluded.timeout_seconds,
                   vision_enabled = excluded.vision_enabled, enabled = excluded.enabled,
                   endpoint_path = excluded.endpoint_path""",
            (
                profile_id,
                profile["name"].strip(),
                profile["base_url"].strip().rstrip("/"),
                profile["model_id"].strip(),
                int(profile["timeout_seconds"]),
                int(profile["vision_enabled"]),
                int(profile["enabled"]),
                profile_id,
                profile["endpoint_path"].strip(),
            ),
        )


def delete_profile(profile_id: str) -> None:
    with _connection() as connection:
        connection.execute("DELETE FROM model_profiles WHERE id = ?", (profile_id,))
