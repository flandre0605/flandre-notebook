import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from app.question_data import QUESTION_FIELDS, database_values, validate_question
from app.paths import DATA_DIR


DATABASE_PATH = DATA_DIR / "questions.db"
SCHEMA_VERSION = 10


@contextmanager
def _connection(database_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    database_path = Path(database_path) if database_path is not None else DATABASE_PATH
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


def initialize(database_path: Path | None = None) -> None:
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
            version = 4
        if version < 5:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "ALTER TABLE practice_attempts ADD COLUMN user_answer TEXT NOT NULL DEFAULT ''"
            )
            connection.execute("PRAGMA user_version = 5")
            version = 5
        if version < 6:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE vocabulary_words (
                    id INTEGER PRIMARY KEY,
                    word TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    meaning TEXT NOT NULL,
                    phonetic TEXT NOT NULL DEFAULT '',
                    example TEXT NOT NULL DEFAULT '',
                    book TEXT NOT NULL DEFAULT '',
                    review_count INTEGER NOT NULL DEFAULT 0 CHECK (review_count >= 0),
                    streak INTEGER NOT NULL DEFAULT 0 CHECK (streak >= 0),
                    due_at TEXT,
                    last_reviewed_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute("CREATE INDEX idx_vocabulary_due_at ON vocabulary_words(due_at)")
            connection.execute("PRAGMA user_version = 6")
            version = 6
        if version < 7:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            for field in ("tags", "knowledge_points", "difficulty", "source"):
                connection.execute(f"ALTER TABLE questions ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
            connection.execute("PRAGMA user_version = 7")
            version = 7
        if version < 8:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE workspace_state (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute("PRAGMA user_version = 8")
            version = 8
        if version < 9:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute("ALTER TABLE questions ADD COLUMN options TEXT NOT NULL DEFAULT '{}'")
            connection.execute("""CREATE TABLE review_preferences (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                mastered_days INTEGER NOT NULL CHECK(mastered_days BETWEEN 0 AND 365),
                unsure_days INTEGER NOT NULL CHECK(unsure_days BETWEEN 0 AND 365),
                unknown_days INTEGER NOT NULL CHECK(unknown_days BETWEEN 0 AND 365))""")
            connection.execute("INSERT INTO review_preferences VALUES (1, 7, 1, 0)")
            connection.execute("PRAGMA user_version = 9")
            version = 9
        if version < 10:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            for field in ("grade", "notes"):
                connection.execute(f"ALTER TABLE questions ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
            connection.execute("PRAGMA user_version = 10")


def _question_conditions(
    search: str, subject: str, question_type: str, state: str, prefix: str = "", difficulty: str = ""
) -> tuple[list[str], list[str]]:
    search_fields = ("stem", "subject", "tags", "knowledge_points", "source", "grade", "notes")
    conditions = ["(" + " OR ".join(f"{prefix}{field} LIKE ?" for field in search_fields) + ")"]
    parameters = [f"%{search}%"] * len(search_fields)
    if difficulty:
        conditions.append(f"{prefix}difficulty = ?")
        parameters.append(difficulty)
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
    search: str = "", subject: str = "", question_type: str = "", state: str = "all", difficulty: str = ""
) -> list[sqlite3.Row]:
    conditions, parameters = _question_conditions(search, subject, question_type, state, difficulty=difficulty)
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


def question_summary() -> tuple[int, int, int]:
    with _connection() as connection:
        row = connection.execute(
            """SELECT COUNT(*), COALESCE(SUM(is_wrong), 0),
                      (SELECT COUNT(*) FROM review_state WHERE due_at <= CURRENT_TIMESTAMP)
               FROM questions"""
        ).fetchone()
        return tuple(row)


def get_question(question_id: int) -> sqlite3.Row | None:
    with _connection() as connection:
        return connection.execute(
            "SELECT * FROM questions WHERE id = ?", (question_id,)
        ).fetchone()


def save_question(question: dict, question_id: int | None = None, draft_key: str | None = None) -> int:
    with _connection() as connection:
        old = connection.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone() if question_id is not None else None
        if question_id is not None and old is None:
            raise ValueError("题目已不存在，请返回题库重新选择。")
        values = database_values(validate_question(question, old))
        if question_id is None:
            cursor = connection.execute(
                f"INSERT INTO questions ({', '.join(QUESTION_FIELDS)}) VALUES ({', '.join('?' for _ in QUESTION_FIELDS)})",
                values,
            )
            if draft_key:
                _write_workspace(connection, draft_key, None)
            return int(cursor.lastrowid)

        connection.execute(
            f"UPDATE questions SET {', '.join(field + ' = ?' for field in QUESTION_FIELDS)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*values, question_id),
        )
        if draft_key:
            _write_workspace(connection, draft_key, None)
        return question_id


def save_question_notes(question_id: int, notes: str) -> str:
    with _connection() as connection:
        question = connection.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        if question is None:
            raise ValueError("题目已不存在，请返回题库重新选择。")
        notes = validate_question({"notes": notes}, question)["notes"]
        connection.execute("UPDATE questions SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (notes, question_id))
        # A parked full editor must keep its other draft fields without restoring stale notes later.
        key = f"question:{question_id}"
        draft = connection.execute("SELECT payload FROM workspace_state WHERE key = ?", (key,)).fetchone()
        if draft is not None:
            state = json.loads(draft["payload"])
            state = validate_question({**state, "notes": notes}, draft=True)
            _write_workspace(connection, key, state)
        return notes


def delete_question(question_id: int) -> None:
    with _connection() as connection:
        connection.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        _write_workspace(connection, f"question:{question_id}", None)


def save_recognized_questions(questions, images, workspace_key=None):
    values = [database_values(validate_question(question)) for question in questions]
    if not values or len(values) > 100 or len(images) != len(values):
        raise ValueError("识题数量或原图关联无效。")
    ids = []
    with _connection() as connection:
        for question, image in zip(values, images):
            cursor = connection.execute(
                f"INSERT INTO questions ({', '.join(QUESTION_FIELDS)}) VALUES ({', '.join('?' for _ in QUESTION_FIELDS)})", question)
            question_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO attachments (question_id, relative_path, original_name, mime_type) VALUES (?, ?, ?, ?)",
                (question_id, image["relative_path"], image["original_name"], image["mime_type"]))
            ids.append(question_id)
        if workspace_key:
            _write_workspace(connection, workspace_key, None)
    return ids


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
    difficulty: str = "",
) -> list[sqlite3.Row]:
    conditions, parameters = _question_conditions(
        search, subject, question_type, state, prefix="q.", difficulty=difficulty
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
    user_answer: str = "",
    session_state: dict | None = None,
    is_wrong: bool | None = None,
) -> None:
    from datetime import datetime, timedelta, timezone

    if mastery not in {"mastered", "unsure", "unknown"}:
        raise ValueError("无效的掌握程度。")
    if result not in {"correct", "incorrect", "skipped"}:
        raise ValueError("无效的作答结果。")
    if is_wrong is not None and type(is_wrong) is not bool:
        raise ValueError("错题标记应为布尔值。")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    reviewed_at = now.strftime("%Y-%m-%d %H:%M:%S")
    with _connection() as connection:
        intervals = _review_intervals(connection)
        due_at = (now + timedelta(days=intervals[mastery])).strftime("%Y-%m-%d %H:%M:%S")
        connection.execute(
            """INSERT INTO practice_attempts
               (question_id, result, duration_seconds, mistake_reason, mastery, user_answer)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                question_id,
                result,
                max(0, duration_seconds),
                mistake_reason.strip(),
                mastery,
                user_answer.strip(),
            ),
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
        if is_wrong is not None:
            connection.execute("UPDATE questions SET is_wrong = ? WHERE id = ?", (int(is_wrong), question_id))
        elif result == "incorrect":
            connection.execute("UPDATE questions SET is_wrong = 1 WHERE id = ?", (question_id,))
        if session_state is not None:
            _write_workspace(connection, "practice", session_state if session_state["index"] < len(session_state["ids"]) else None)


def _review_intervals(connection):
    row = connection.execute("SELECT mastered_days, unsure_days, unknown_days FROM review_preferences WHERE id = 1").fetchone()
    if row is None:
        raise ValueError("复习设置缺失，请在设置页重新保存。")
    return dict(zip(("mastered", "unsure", "unknown"), row))


def review_intervals():
    with _connection() as connection:
        return _review_intervals(connection)


def save_review_intervals(intervals):
    keys = ("mastered", "unsure", "unknown")
    if not isinstance(intervals, dict) or any(type(intervals.get(key)) is not int or not 0 <= intervals[key] <= 365 for key in keys):
        raise ValueError("复习间隔应为 0～365 的整数天数。")
    with _connection() as connection:
        connection.execute("INSERT INTO review_preferences VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                           "mastered_days = excluded.mastered_days, unsure_days = excluded.unsure_days, unknown_days = excluded.unknown_days",
                           tuple(intervals[key] for key in keys))


def _write_workspace(connection, key, state):
    if state is None:
        connection.execute("DELETE FROM workspace_state WHERE key = ?", (key,))
    else:
        payload = json.dumps(state, ensure_ascii=False)
        if len(payload.encode("utf-8")) > 5 * 1024 * 1024:
            raise ValueError("草稿不能超过 5 MB，请精简后保存。")
        connection.execute("INSERT INTO workspace_state (key, payload) VALUES (?, ?) "
                           "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload",
                           (key, payload))


def save_workspace(key: str, state: dict | None):
    with _connection() as connection:
        _write_workspace(connection, key, state)


def workspace_keys(prefix):
    with _connection() as connection:
        return [row[0] for row in connection.execute(
            "SELECT key FROM workspace_state WHERE substr(key, 1, ?) = ? ORDER BY rowid DESC", (len(prefix), prefix))]


def load_workspace(key: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT payload FROM workspace_state WHERE key = ?", (key,)).fetchone()
    if row is None or len(row[0]) > 5 * 1024 * 1024:
        return None
    try:
        state = json.loads(row[0])
    except (ValueError, TypeError):
        return None
    return state if isinstance(state, dict) else None


def list_attempts(limit: int = 500) -> list[sqlite3.Row]:
    with _connection() as connection:
        return connection.execute(
            """SELECT a.answered_at, a.result, a.duration_seconds, a.mistake_reason,
                      a.mastery, a.user_answer, q.stem, q.subject
               FROM practice_attempts a
               JOIN questions q ON q.id = a.question_id
               ORDER BY a.id DESC LIMIT ?""",
            (max(1, min(limit, 2000)),),
        ).fetchall()


def learning_statistics() -> dict:
    with _connection() as connection:
        total = dict(connection.execute(
            """SELECT COUNT(*) AS attempts,
                      COALESCE(SUM(result = 'correct'), 0) AS correct,
                      COALESCE(SUM(result = 'incorrect'), 0) AS incorrect,
                      COALESCE(SUM(result = 'skipped'), 0) AS skipped,
                      COALESCE(SUM(duration_seconds), 0) AS seconds,
                      COUNT(DISTINCT date(answered_at, 'localtime')) AS days
               FROM practice_attempts"""
        ).fetchone())
        subjects = [dict(row) for row in connection.execute(
            """SELECT q.subject, COUNT(*) AS attempts,
                      SUM(a.result = 'correct') AS correct,
                      SUM(a.result = 'incorrect') AS incorrect,
                      SUM(a.result = 'skipped') AS skipped,
                      SUM(a.duration_seconds) AS seconds
               FROM practice_attempts a JOIN questions q ON q.id = a.question_id
               GROUP BY q.subject ORDER BY q.subject"""
        )]
        daily = [dict(row) for row in connection.execute(
            """SELECT date(answered_at, 'localtime') AS day, COUNT(*) AS attempts,
                      SUM(result = 'correct') AS correct,
                      SUM(result = 'incorrect') AS incorrect
               FROM practice_attempts
               WHERE date(answered_at, 'localtime') BETWEEN date('now', 'localtime', '-89 days')
                                                      AND date('now', 'localtime')
               GROUP BY day ORDER BY day"""
        )]
        reasons = [dict(row) for row in connection.execute(
            """SELECT mistake_reason, COUNT(*) AS count FROM practice_attempts
               WHERE result = 'incorrect' AND mistake_reason <> ''
               GROUP BY mistake_reason ORDER BY count DESC, mistake_reason LIMIT 5"""
        )]
    return dict(total=total, subjects=subjects, daily=daily, reasons=reasons)


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
