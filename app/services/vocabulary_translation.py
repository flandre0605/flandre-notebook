import json

from app.database import vocabulary
from app.prompts import VOCABULARY_TRANSLATION_SYSTEM
from app.services.model_provider import ProviderError, _parse_json_content, _request, validate_profile


def translate_words(profile, words):
    validate_profile(profile)
    if not words or len(words) > 20:
        raise ValueError("每批翻译 1～20 个单词。")
    expected = {}
    for word in words:
        word = vocabulary.validate_word(word)
        expected.setdefault(word.casefold(), word)
    messages = [
        {"role": "system", "content": VOCABULARY_TRANSLATION_SYSTEM},
        {"role": "user", "content": json.dumps({"words": list(expected.values())}, ensure_ascii=False)},
    ]
    try:
        content = _request(profile, messages, max_tokens=4000, json_mode=True)
    except ProviderError as error:
        if not error.retry_without_json_mode:
            raise
        content = _request(profile, messages, max_tokens=4000, json_mode=False)
    try:
        payload = _parse_json_content(content)
        entries = payload.get("words") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("模型没有返回 words 列表。")
        found = {}
        for entry in entries:
            if not isinstance(entry, dict) or not all(isinstance(entry.get(key, ""), str)
                                                     for key in ("word", "meaning", "phonetic", "example")):
                raise ValueError("模型词条字段必须是字符串。")
            word = vocabulary.validate_word(entry.get("word", ""))
            key = word.casefold()
            if key not in expected or key in found:
                raise ValueError("模型返回了额外或重复的单词。")
            meaning = entry.get("meaning", "").strip()
            phonetic = entry.get("phonetic", "").strip()
            example = entry.get("example", "").strip()
            if not meaning or len(meaning) > 4000 or not any('\u4e00' <= char <= '\u9fff' for char in meaning):
                raise ValueError("模型未提供有效的中文释义。")
            if len(phonetic) > 100 or len(example) > 4000:
                raise ValueError("模型返回的音标或例句过长。")
            found[key] = dict(word=expected[key], meaning=meaning, phonetic=phonetic, example=example)
        if found.keys() != expected.keys():
            raise ValueError("模型漏掉了部分单词，请重试。")
    except (json.JSONDecodeError, ValueError) as error:
        raise ProviderError(f"翻译格式无效：{error}", content) from None
    return [found[key] for key in expected]
