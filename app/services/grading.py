import re
import unicodedata
from fractions import Fraction
from app.question_data import choice_mode, parse_options


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(value.split())


def _judgement(value: str) -> bool | None:
    value = _normalise(value).strip(".。!！")
    if value in {"对", "正确", "是", "√", "true", "yes", "1"}:
        return True
    if value in {"错", "错误", "否", "×", "✗", "false", "no", "0"}:
        return False
    return None


def _number(value: str) -> Fraction | None:
    """Exact numeric answers only; never execute an expression supplied by a model."""
    value = unicodedata.normalize("NFKC", value).strip().replace("−", "-")
    if len(value) > 128:
        return None
    for left, right in (("$$", "$$"), ("$", "$"), (r"\(", r"\)"), (r"\[", r"\]")):
        if value.startswith(left) and value.endswith(right):
            value = value[len(left):-len(right)].strip()
            break
    value = re.sub(r"\\(?:dfrac|tfrac|frac)\{([+-]?\d+)\}\{([+-]?\d+)\}", r"\1/\2", value)
    value = value.replace(" ", "")
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    percent = value.endswith("%")
    if percent:
        value = value[:-1]
    if not re.fullmatch(r"[+-]?(?:\d+/[+-]?\d+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,2})?)", value):
        return None
    exponent = re.search(r"[eE]([+-]?\d+)$", value)
    if exponent and abs(int(exponent.group(1))) > 50:
        return None
    try:
        number = Fraction(*(int(part) for part in value.split("/"))) if "/" in value else Fraction(value)
        return number / 100 if percent else number
    except (ValueError, ZeroDivisionError):
        return None


def _choice_labels(value, options, multiple):
    value = unicodedata.normalize("NFKC", value).strip().upper()
    if re.fullmatch(r"[A-Z](?:[A-Z]|[,，、;；\s])*", value):
        labels = re.sub(r"[,，、;；\s]", "", value)
        if len(labels) == len(set(labels)) and set(labels) <= options.keys() and (multiple or len(labels) == 1):
            return frozenset(labels)
    if not multiple:
        matches = [label for label, text in options.items() if _normalise(value) in
                   {_normalise(text), _normalise(f"{label}. {text}"), _normalise(f"{label}、{text}")}]
        if len(matches) == 1:
            return frozenset(matches)
    return None


def grade_answer(question_type: str, expected: str, submitted: str, options=None) -> bool | None:
    """Return correctness, or None when the answer needs human judgement."""
    expected, submitted = expected.strip(), submitted.strip()
    if not expected or not submitted:
        return None

    kind = _normalise(question_type)
    if any(word in kind for word in ("解答", "简答", "主观", "论述", "证明", "essay", "subjective")):
        return None

    mode = choice_mode(question_type)
    if options is not None and mode:
        try:
            options = parse_options(options)
        except ValueError:
            return None
    if options and mode:
        candidates = [_choice_labels(value, options, mode == "multiple") for value in expected.split("|") if value.strip()]
        actual = _choice_labels(submitted, options, mode == "multiple")
        if not candidates or any(value is None for value in candidates) or actual is None:
            return None
        return actual in candidates

    candidates = [_normalise(value) for value in expected.split("|") if value.strip()]
    actual = _normalise(submitted)
    if "判断" in kind or "truefalse" in kind or "true_false" in kind:
        actual_judgement = _judgement(actual)
        expected_judgements = {_judgement(value) for value in candidates}
        expected_judgements.discard(None)
        return actual_judgement in expected_judgements if expected_judgements else None

    if "多选" in kind or "multiple" in kind:
        def choices(value: str) -> str:
            return "".join(sorted(re.sub(r"[,，、;；\s]", "", value)))

        return any(choices(actual) == choices(value) for value in candidates)

    numbers = [_number(value) for value in expected.split("|") if value.strip()]
    if numbers and all(value is not None for value in numbers):
        actual_number = _number(submitted)
        return actual_number in numbers if actual_number is not None else None
    if re.search(r"\\[A-Za-z]+|\\[([]|\$", expected):
        # General formula/semantic equivalence still requires human judgement.
        return True if _normalise(expected) == _normalise(submitted) else None

    return actual in candidates
