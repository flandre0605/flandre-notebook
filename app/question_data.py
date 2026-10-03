"""Shared question format for storage, files, model drafts and UI."""
import json
import re

QUESTION_LABELS = dict(stem="题干", subject="学科", question_type="题型", answer="答案", explanation="解析",
                       tags="标签", knowledge_points="知识点", difficulty="难度", source="来源",
                       grade="年级", notes="个人笔记", options="选项", is_wrong="错题")
QUESTION_FIELDS = tuple(QUESTION_LABELS)
TEXT_FIELDS = tuple(field for field in QUESTION_FIELDS if field not in ("options", "is_wrong"))


def parse_options(value, draft=False):
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except (ValueError, RecursionError) as error:
            raise ValueError("选项格式无效，应为标号与内容组成的对象。") from error
    if not isinstance(value, dict) or len(value) > 12:
        raise ValueError("选项应为最多 12 项的对象。")
    if value and len(value) < 2 and not draft:
        raise ValueError("设置选项时至少需要两项。")
    options = {}
    for label, text in value.items():
        if not isinstance(label, str) or not re.fullmatch(r"[A-Z]", label):
            raise ValueError("选项标号必须为 A～Z 的大写字母。")
        if not isinstance(text, str) or len(text) > 20000 or (not draft and not text.strip()):
            raise ValueError(f"选项 {label} 内容不能为空且最多 20000 字。")
        options[label] = text if draft else text.strip()
    return dict(sorted(options.items()))


def validate_question(question, original=None, draft=False):
    if not isinstance(question, dict):
        raise ValueError("题目应为一个对象。")
    defaults = dict(original) if original is not None else {}
    result = {}
    for field in TEXT_FIELDS:
        value = question.get(field, defaults.get(field, ""))
        if not isinstance(value, str) or len(value) > 20000:
            raise ValueError(f"{field} 应为不超过 20000 字的文本。")
        result[field] = value if draft else value.strip()
    if not draft and not result["stem"]:
        raise ValueError("题干不能为空。")
    if result["difficulty"] not in ("", "简单", "中等", "困难"):
        raise ValueError("难度应为简单、中等、困难，或留空。")
    if len(result["grade"]) > 100 or "\n" in result["grade"] or "\r" in result["grade"]:
        raise ValueError("年级应为不超过 100 字的单行文本。")
    wrong = question.get("is_wrong", defaults.get("is_wrong", 0))
    if isinstance(wrong, str):
        wrong = wrong.strip().casefold()
    if wrong in (0, False, "0", "false", "否", "普通", ""):
        result["is_wrong"] = 0
    elif wrong in (1, True, "1", "true", "是", "错题"):
        result["is_wrong"] = 1
    else:
        raise ValueError("错题标记应为 0 或 1。")
    result["options"] = parse_options(question.get("options", defaults.get("options", {})), draft)
    return result


def database_values(question):
    return tuple(json.dumps(question[field], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                 if field == "options" else question[field] for field in QUESTION_FIELDS)


def question_text(question):
    question = dict(question)
    options = parse_options(question.get("options", {}), draft=True)
    return question["stem"] + ("\n\n" + "\n".join(f"{label}. {text}" for label, text in options.items()) if options else "")


def choice_mode(question_type):
    kind = question_type.casefold()
    if "多选" in kind or "multiple" in kind:
        return "multiple"
    if any(word in kind for word in ("单选", "选择", "single", "choice")):
        return "single"
    return ""
