import re
import unicodedata


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


def grade_answer(question_type: str, expected: str, submitted: str) -> bool | None:
    """Return correctness, or None when the answer needs human judgement."""
    expected, submitted = expected.strip(), submitted.strip()
    if not expected or not submitted:
        return None

    kind = _normalise(question_type)
    if any(word in kind for word in ("解答", "简答", "主观", "论述", "证明", "essay", "subjective")):
        return None

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

    return actual in candidates
