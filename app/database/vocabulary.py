import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3
import unicodedata

from app.database import store


def normalize_word(value):
    return " ".join(unicodedata.normalize("NFKC", value).replace("’", "'").strip().split())


def validate_word(value):
    word = normalize_word(value)
    if not word or len(word) > 100 or not re.fullmatch(r"[A-Za-z]+(?:[ '\-][A-Za-z]+)*", word):
        raise ValueError("请输入英文单词或短语（最多 100 个字符，可含空格、连字符和撇号）。")
    return word


def _values(data, require_meaning=True):
    if not isinstance(data, dict) or any(not isinstance(data.get(key, ""), str)
                                         for key in ("word", "meaning", "phonetic", "example", "book")):
        raise ValueError("词条内容应为文本。")
    word = validate_word(data.get("word", ""))
    meaning = data.get("meaning", "").strip()
    if (require_meaning and not meaning) or len(meaning) > 4000:
        raise ValueError("请填写释义，最多 4000 个字符。")
    extras = []
    for key, label, maximum in (("phonetic", "音标", 100), ("example", "例句", 4000), ("book", "单词本名称", 100)):
        value = data.get(key, "").strip()
        if len(value) > maximum:
            raise ValueError(f"{label}内容过长，最多 {maximum} 个字符。")
        extras.append(value)
    return (word, meaning, *extras)


def save_word(data, word_id=None, draft_key=None):
    values = _values(data)
    try:
        with store._connection() as connection:
            if word_id is None:
                cursor = connection.execute(
                    "INSERT INTO vocabulary_words (word, meaning, phonetic, example, book) VALUES (?, ?, ?, ?, ?)", values
                )
                if draft_key:
                    store._write_workspace(connection, draft_key, None)
                return int(cursor.lastrowid)
            cursor = connection.execute(
                "UPDATE vocabulary_words SET word = ?, meaning = ?, phonetic = ?, example = ?, book = ? WHERE id = ?",
                (*values, word_id),
            )
            if not cursor.rowcount:
                raise ValueError("单词已不存在，请刷新列表。")
            if draft_key:
                store._write_workspace(connection, draft_key, None)
            return word_id
    except sqlite3.IntegrityError as error:
        raise ValueError("该单词已存在，请编辑现有词条。") from error


def get_word(word_id):
    with store._connection() as connection:
        return connection.execute("SELECT * FROM vocabulary_words WHERE id = ?", (word_id,)).fetchone()


def delete_word(word_id):
    with store._connection() as connection:
        connection.execute("DELETE FROM vocabulary_words WHERE id = ?", (word_id,))
        store._write_workspace(connection, f"vocabulary:word:{word_id}", None)


def list_words(search="", book="", scope="all", limit=None):
    conditions = ["(word LIKE ? OR meaning LIKE ?)"]
    parameters = [f"%{search}%", f"%{search}%"]
    if book:
        conditions.append("book = ?")
        parameters.append(book)
    if scope == "new":
        conditions.append("review_count = 0")
    elif scope == "due":
        conditions.append("due_at <= CURRENT_TIMESTAMP")
    elif scope != "all":
        raise ValueError("无效的单词范围。")
    query = "SELECT * FROM vocabulary_words WHERE " + " AND ".join(conditions)
    query += " ORDER BY COALESCE(due_at, '0000'), id"
    if limit is not None:
        query += " LIMIT ?"
        parameters.append(max(1, min(int(limit), 200)))
    with store._connection() as connection:
        return connection.execute(query, parameters).fetchall()


def summary_and_books():
    with store._connection() as connection:
        summary = connection.execute(
            """SELECT COUNT(*), COALESCE(SUM(review_count = 0), 0),
                      COALESCE(SUM(due_at <= CURRENT_TIMESTAMP), 0) FROM vocabulary_words"""
        ).fetchone()
        books = connection.execute("SELECT DISTINCT book FROM vocabulary_words WHERE book <> '' ORDER BY book").fetchall()
        return tuple(summary), [row[0] for row in books]


def record_review(word_id, rating, session_state=None):
    if rating not in {"forgot", "hard", "known"}:
        raise ValueError("无效的单词掌握程度。")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with store._connection() as connection:
        row = connection.execute("SELECT streak FROM vocabulary_words WHERE id = ?", (word_id,)).fetchone()
        if row is None:
            raise ValueError("单词已不存在，未记录本次复习。")
        streak = row["streak"] + 1 if rating == "known" else 0
        # ponytail: 固定间隔 1/3/7/14/30 天；确有长期学习数据后再引入自适应算法。
        days = (1, 3, 7, 14, 30)[min(streak - 1, 4)] if streak else (1 if rating == "hard" else 0)
        connection.execute(
            """UPDATE vocabulary_words SET review_count = review_count + 1, streak = ?,
                      last_reviewed_at = ?, due_at = ? WHERE id = ?""",
            (streak, now.strftime("%Y-%m-%d %H:%M:%S"),
             (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"), word_id),
        )
        if session_state is not None:
            store._write_workspace(connection, "vocabulary:study",
                                   session_state if session_state["index"] < len(session_state["ids"]) else None)


def read_word_file(path):
    path = Path(path)
    if path.suffix.lower() not in {".csv", ".txt"}:
        raise ValueError("请选择 TXT 或 CSV 词表。")
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("词表文件不能超过 5 MB。")
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        content = path.read_text(encoding="gb18030")
    if path.suffix.lower() == ".txt":
        rows = []
        for index, line in enumerate(content.splitlines(), 1):
            if not line.strip():
                continue
            word, _, meaning = line.partition("\t")
            try:
                values = _values(dict(word=word, meaning=meaning), require_meaning=False)
            except ValueError as error:
                raise ValueError(f"第 {index} 行：{error}") from error
            rows.append(dict(zip(("word", "meaning", "phonetic", "example", "book"), values)))
            if len(rows) > 5000:
                raise ValueError("每次最多导入 5000 个单词。")
        if not rows:
            raise ValueError("TXT 没有单词数据。")
        return rows
    aliases = {"单词": "word", "释义": "meaning", "音标": "phonetic", "例句": "example", "单词本": "book"}
    reader = csv.DictReader(content.splitlines(keepends=True), strict=True)
    if reader.fieldnames is None:
        raise ValueError("CSV 文件为空。")
    reader.fieldnames = [aliases.get(name.strip(), name.strip().lower()) for name in reader.fieldnames]
    if "word" not in reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("CSV 表头必须包含 word（或 单词），且不能重复；释义可稍后补全。")
    values = []
    for index, row in enumerate(reader, 1):
        if index > 5000:
            raise ValueError("每次最多导入 5000 个单词。")
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"第 {reader.line_num} 行的列数与表头不一致。")
        try:
            values.append(_values(row, require_meaning=False))
        except ValueError as error:
            raise ValueError(f"第 {reader.line_num} 行：{error}") from error
    if not values:
        raise ValueError("CSV 没有单词数据。")
    return [dict(zip(("word", "meaning", "phonetic", "example", "book"), value)) for value in values]


def validate_rows(rows, require_meaning=True):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise ValueError("每次导入 1～5000 个单词。")
    return [dict(zip(("word", "meaning", "phonetic", "example", "book"), _values(row, require_meaning))) for row in rows]


def import_rows(rows, draft_key=None):
    values = [_values(row) for row in validate_rows(rows)]
    added = 0
    with store._connection() as connection:
        for value in values:
            cursor = connection.execute(
                """INSERT INTO vocabulary_words (word, meaning, phonetic, example, book)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(word) DO NOTHING""", value,
            )
            added += cursor.rowcount
        if draft_key:
            store._write_workspace(connection, draft_key, None)
    return added, len(values) - added


def import_csv(path):
    return import_rows(read_word_file(path))
