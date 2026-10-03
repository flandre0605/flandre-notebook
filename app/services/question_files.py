"""Portable question text, separate from full database/image backups."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile

from app.database import store
from app.question_data import QUESTION_FIELDS, QUESTION_LABELS, TEXT_FIELDS, database_values, question_text, validate_question

FIELDS = QUESTION_FIELDS
HEADERS = {label: field for field, label in QUESTION_LABELS.items()}
MAX_ROWS = 5000
MAX_BYTES = 5 * 1024 * 1024


def validate_questions(rows):
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
        raise ValueError("文件应包含 1～5000 道题目。")
    validated = []
    for index, row in enumerate(rows, 1):
        try:
            validated.append(validate_question(row))
        except ValueError as error:
            raise ValueError(f"第 {index} 道题目：{error}") from error
    return validated


def read_questions(path):
    path = Path(path)
    if path.suffix.lower() not in {".json", ".csv"}:
        raise ValueError("请选择 JSON 或 CSV 题库文件。")
    with path.open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("文件不能超过 5 MB。")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gb18030")
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except RecursionError as error:
            raise ValueError("JSON 嵌套过深，请使用普通题目列表。") from error
        if isinstance(payload, dict):
            if payload.get("format") != "flandre-questions" or payload.get("version") != 1:
                raise ValueError("不支持此题库文件版本。")
            payload = payload.get("questions")
    else:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV 缺少表头。")
        names = [HEADERS.get(name.strip(), name.strip()) for name in reader.fieldnames]
        if "stem" not in names or len(set(names)) != len(names):
            raise ValueError("CSV 表头应包含 stem（或题干），且不能重复。")
        payload = []
        for row in reader:
            if None in row:
                raise ValueError("CSV 行的列数与表头不一致。")
            question = {name: row[original] or "" for original, name in zip(reader.fieldnames, names)}
            if question.pop("_flandre_escaped", "") == "1":
                for field in TEXT_FIELDS:
                    value = question.get(field, "")
                    if value.startswith("'"):
                        question[field] = value[1:]
            payload.append(question)
            if len(payload) > MAX_ROWS:
                raise ValueError("每次最多导入 5000 道题目。")
    return validate_questions(payload)


def import_questions(rows):
    rows = validate_questions(rows)
    added = skipped = 0
    # Validate the entire draft first; one transaction avoids a half-imported file.
    with store._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        # ponytail: keep the small library in memory for exact deduplication;
        # use an indexed content hash if libraries grow beyond memory limits.
        existing = {tuple(row) for row in connection.execute(
            f"SELECT {', '.join(FIELDS)} FROM questions"
        )}
        for question in rows:
            values = database_values(question)
            if values in existing:
                skipped += 1
                continue
            connection.execute(
                f"INSERT INTO questions ({', '.join(FIELDS)}) VALUES ({', '.join('?' for _ in FIELDS)})",
                values,
            )
            existing.add(values)
            added += 1
    return added, skipped


def export_rows(search="", subject="", question_type="", state="all", difficulty=""):
    conditions, parameters = store._question_conditions(search, subject, question_type, state, difficulty=difficulty)
    with store._connection() as connection:
        rows = connection.execute(
            f"SELECT {', '.join(FIELDS)} FROM questions WHERE {' AND '.join(conditions)} ORDER BY id",
            parameters,
        ).fetchall()
    return [validate_question(dict(row)) for row in rows]


def write_questions(path, rows, include_solutions=True):
    """Replace the destination only after a complete export, including PDF."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {".json", ".csv", ".pdf"}:
        raise ValueError("导出格式应为 JSON、CSV 或 PDF。")
    if not rows:
        raise ValueError("所选范围内没有题目。")
    if suffix != ".pdf":
        rows = validate_questions(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, suffix=suffix)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if suffix == ".json":
            temporary.write_text(json.dumps({"format": "flandre-questions", "version": 1,
                                            "questions": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        elif suffix == ".csv":
            with temporary.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=(*FIELDS, "_flandre_escaped"))
                writer.writeheader()
                for row in rows:
                    escaped = dict(row, _flandre_escaped="1", options=json.dumps(row["options"], ensure_ascii=False))
                    for field in TEXT_FIELDS:
                        value = escaped[field]
                        if value.startswith(("=", "+", "-", "@", "'")):
                            escaped[field] = "'" + value
                    writer.writerow(escaped)
        else:
            from html import escape
            from PySide6.QtGui import QPageSize, QTextDocument
            from PySide6.QtPrintSupport import QPrinter
            from app.ui.math_text import math_html

            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(temporary))
            printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            printer.setDocName("芙兰错题本 · 题目练习")
            sections = ["<h1>我的题目练习</h1>"]
            for index, question in enumerate(rows, 1):
                sections.append(f"<h2>{index}. {escape(question['subject'] or '未分类')} · "
                                f"{escape(question['question_type'] or '未设题型')}</h2>")
                if question.get("grade"):
                    sections.append(f"<p>年级：{escape(question['grade'])}</p>")
                sections.append(math_html(question_text(question), 650))
                if include_solutions:
                    sections.append("<h3>答案</h3>" + math_html(question["answer"] or "暂无标准答案", 650))
                    sections.append("<h3>解析</h3>" + math_html(question["explanation"] or "暂无解析", 650))
                    if question.get("notes"):
                        sections.append("<h3>个人笔记</h3>" + math_html(question["notes"], 650))
                sections.append("<hr>")
            document = QTextDocument()
            document.setDefaultStyleSheet("body {font-family:'Microsoft YaHei UI';font-size:11pt;color:#252030;}")
            document.setHtml("".join(sections))
            document.print_(printer)
            if not temporary.stat().st_size:
                raise OSError("PDF 生成失败。")
        if temporary.stat().st_size > MAX_BYTES and suffix != ".pdf":
            raise ValueError("导出文件超过 5 MB，请按学科或搜索条件分批导出。")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
