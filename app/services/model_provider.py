import base64
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImageReader

from app.prompts import QUESTION_RECOGNITION_SYSTEM, QUESTION_RECOGNITION_USER
from app.services.credentials import get_api_key

MAX_API_IMAGE_EDGE = 2560
MAX_RAW_API_IMAGE_BYTES = 4 * 1024 * 1024


class ProviderError(RuntimeError):
    def __init__(self, message: str, raw_response: str = "", retry_without_json_mode: bool = False):
        super().__init__(message)
        self.raw_response = raw_response
        self.retry_without_json_mode = retry_without_json_mode


def _content_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return _content_text(content.get("content"))
    if isinstance(content, list):
        parts = [_content_text(part) for part in content]
        return "".join(part for part in parts if part)
    return ""


def _response_text(payload, depth: int = 0) -> str:
    if depth > 3 or not isinstance(payload, dict):
        return ""
    # OpenAI Chat Completions and legacy Completions responses.
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice = choices[0]
        message = choice.get("message")
        text = _content_text(message.get("content")) if isinstance(message, dict) else ""
        if not text:
            text = _content_text(choice.get("text"))
        if text:
            return text
    # OpenAI Responses API output.
    text = _content_text(payload.get("output_text"))
    if text:
        return text
    text = _content_text(payload.get("content"))
    if not text:
        text = _content_text(payload.get("text"))
    if text:
        return text
    output = payload.get("output")
    if isinstance(output, list):
        text = _content_text(output)
        if text:
            return text
    # Some relays wrap the otherwise compatible response in data/result.
    for key in ("data", "result", "response"):
        nested = payload.get(key)
        text = _content_text(nested) if isinstance(nested, str) else _response_text(nested, depth + 1)
        if text:
            return text
    return ""


def _response_shape(payload) -> str:
    if not isinstance(payload, dict):
        return f"JSON 顶层类型：{type(payload).__name__}"
    details = [f"顶层字段：{', '.join(map(str, list(payload)[:20])) or '无'}"]
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        details.append(f"choices[0] 字段：{', '.join(map(str, list(choices[0])[:20])) or '无'}")
    return "；".join(details)


def _endpoint(base_url: str, endpoint_path: str = "/chat/completions") -> str:
    try:
        parsed = urllib.parse.urlsplit(base_url.strip())
        parsed.port
    except ValueError:
        raise ProviderError("API 地址格式无效，请检查域名和端口。") from None
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ProviderError("API 地址必须是有效的 HTTP/HTTPS 地址，且不能包含用户名或密码。")
    if parsed.query or parsed.fragment:
        raise ProviderError("API 地址不能包含查询参数或片段，请只填写基础地址。")
    endpoint_path = endpoint_path.strip()
    if (
        not endpoint_path.startswith("/")
        or endpoint_path.startswith("//")
        or "?" in endpoint_path
        or "#" in endpoint_path
        or "\\" in endpoint_path
        or any(character.isspace() for character in endpoint_path)
        or not endpoint_path.rstrip("/")
    ):
        raise ProviderError("API 路径需以 / 开头，且不能包含查询参数、空格或反斜杠。")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ProviderError("远程中转站必须使用 HTTPS，避免明文发送 API Key。")
    path = parsed.path.rstrip("/")
    endpoint_path = endpoint_path.rstrip("/")
    if path.endswith(endpoint_path):
        final_path = path
    else:
        final_path = f"{path}{endpoint_path}"
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, final_path, "", "")
    )


def validate_profile(profile, require_model: bool = True) -> None:
    if not str(profile["name"]).strip():
        raise ProviderError("请填写配置名称。")
    if require_model and not str(profile["model_id"]).strip():
        raise ProviderError("请填写模型 ID。")
    if not 5 <= int(profile["timeout_seconds"]) <= 300:
        raise ProviderError("超时时间需在 5 到 300 秒之间。")
    _endpoint(profile["base_url"], profile["endpoint_path"])


def list_models(profile, api_key: str | None = None) -> list[str]:
    validate_profile(profile, require_model=False)
    if not api_key:
        api_key = get_api_key(profile["api_key_ref"])
    parsed = urllib.parse.urlsplit(profile["base_url"].strip())
    base_path = parsed.path.rstrip("/")
    if base_path.endswith("/chat/completions"):
        base_path = base_path[: -len("/chat/completions")]
    route = profile["endpoint_path"].rstrip("/")
    if route.endswith("/chat/completions"):
        route = route[: -len("chat/completions")] + "models"
        models_path = f"{base_path}{route}"
    else:
        models_path = f"{base_path}/models"
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, models_path, "", ""))
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=max(1, min(int(profile["timeout_seconds"]), 300))
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        messages = {
            401: "获取模型列表失败：鉴权失败，请检查 API Key。",
            403: "获取模型列表失败：服务拒绝访问。",
            404: "中转站未提供标准 /models 接口，可直接手动填写模型 ID。",
            429: "获取模型列表时请求过于频繁，请稍后重试。",
        }
        raise ProviderError(messages.get(error.code, f"获取模型列表失败：HTTP {error.code}。")) from None
    except urllib.error.URLError as error:
        reason = "连接超时" if isinstance(error.reason, TimeoutError) else "无法连接模型服务"
        raise ProviderError(f"{reason}，请检查网络和 API 地址。") from None
    except (TimeoutError, OSError):
        raise ProviderError("获取模型列表时连接超时或网络中断。") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError("模型列表接口返回了无效的 JSON 响应。") from None

    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ProviderError("模型列表响应不符合 OpenAI 格式；可以手动填写模型 ID。")
    models = sorted({item["id"].strip() for item in entries if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()})
    if not models:
        raise ProviderError("中转站没有返回可选择的模型；可以手动填写模型 ID。")
    return models


def _request(profile, messages, max_tokens=1200, json_mode=False) -> str:
    api_key = get_api_key(profile["api_key_ref"])
    url = _endpoint(profile["base_url"], profile["endpoint_path"])
    request_body = {
        "model": profile["model_id"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    if json_mode:
        request_body["response_format"] = {"type": "json_object"}
    body = json.dumps(request_body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=max(1, min(int(profile["timeout_seconds"]), 300))
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        error_body = error.read(2000).decode("utf-8", errors="replace").lower()
        if json_mode and error.code in {400, 422} and "response_format" in error_body:
            raise ProviderError(
                "中转站不支持 JSON 模式，正在使用提示词约束格式重试。",
                retry_without_json_mode=True,
            ) from None
        messages = {
            401: "鉴权失败，请检查 API Key。",
            403: "服务拒绝访问，请检查账号权限。",
            404: "接口或模型不存在，请检查中转站地址和模型 ID。",
            429: "请求过于频繁或额度不足，请稍后重试。",
        }
        raise ProviderError(messages.get(error.code, f"模型服务返回 HTTP {error.code}。")) from None
    except urllib.error.URLError as error:
        reason = "连接超时" if isinstance(error.reason, TimeoutError) else "无法连接模型服务"
        raise ProviderError(f"{reason}，请检查网络和 API 地址。") from None
    except (TimeoutError, OSError):
        raise ProviderError("连接超时或网络中断，请稍后重试。") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError("模型服务返回了无效的 JSON 响应。") from None

    content = _response_text(payload)
    if content:
        return content
    raise ProviderError(
        "请求已返回，但响应中没有识别到模型文本；请检查中转站接口格式。",
        _response_shape(payload),
    )


def test_profile(profile) -> str:
    return _request(
        profile,
        [{"role": "user", "content": "Reply with OK."}],
        max_tokens=16,
    )


def _parse_json_content(content: str) -> dict | list:
    candidate = content.strip().lstrip("\ufeff")
    try:
        payload = json.loads(candidate)
        if isinstance(payload, (dict, list)):
            return payload
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for start, character in enumerate(candidate):
        if character not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(candidate, start)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, (dict, list)):
            return payload
    raise json.JSONDecodeError("No valid JSON object or array", candidate, 0)


def _image_for_request(image_path: Path, mime_type: str) -> tuple[str, str]:
    reader = QImageReader(str(image_path))
    size = reader.size()
    if image_path.stat().st_size <= MAX_RAW_API_IMAGE_BYTES and (
        not size.isValid() or max(size.width(), size.height()) <= MAX_API_IMAGE_EDGE
    ):
        return mime_type, base64.b64encode(image_path.read_bytes()).decode("ascii")

    reader.setAutoTransform(True)
    if size.isValid() and max(size.width(), size.height()) > MAX_API_IMAGE_EDGE:
        reader.setScaledSize(
            size.scaled(
                QSize(MAX_API_IMAGE_EDGE, MAX_API_IMAGE_EDGE),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
        )
    image = reader.read()
    if image.isNull():
        return mime_type, base64.b64encode(image_path.read_bytes()).decode("ascii")

    output_format = "PNG" if mime_type == "image/png" or image.hasAlphaChannel() else "JPEG"
    output_mime = "image/png" if output_format == "PNG" else "image/jpeg"
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, output_format, 90 if output_format == "JPEG" else -1):
        return mime_type, base64.b64encode(image_path.read_bytes()).decode("ascii")
    return output_mime, base64.b64encode(bytes(buffer.data())).decode("ascii")


def recognize_image(profile, image_path: str | Path) -> list[dict[str, str]]:
    image_path = Path(image_path)
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    # ponytail: 2560 px balances OCR readability and memory; raise only if recognition quality needs it.
    mime_type, encoded = _image_for_request(image_path, mime_type)
    messages = [
        {"role": "system", "content": QUESTION_RECOGNITION_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": QUESTION_RECOGNITION_USER},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                },
            ],
        },
    ]
    try:
        content = _request(profile, messages, json_mode=True)
    except ProviderError as error:
        if not error.retry_without_json_mode:
            raise
        content = _request(profile, messages, json_mode=False)
    try:
        draft = _parse_json_content(content)
    except json.JSONDecodeError:
        raise ProviderError("模型返回内容不是有效 JSON，原始响应已保留。", content) from None
    if isinstance(draft, dict) and isinstance(draft.get("questions"), list):
        questions = draft["questions"]
    elif isinstance(draft, dict) and isinstance(draft.get("stem"), str):
        questions = [draft]
    elif isinstance(draft, list):
        questions = draft
    else:
        raise ProviderError("模型响应没有包含题目列表，原始响应已保留。", content)
    if not questions or any(
        not isinstance(question, dict) or not isinstance(question.get("stem"), str)
        for question in questions
    ):
        raise ProviderError("模型响应中的题目缺少题干字段，原始响应已保留。", content)
    fields = ("stem", "subject", "question_type", "answer", "explanation")
    return [
        {
            field: question.get(field, "") if isinstance(question.get(field, ""), str) else ""
            for field in fields
        }
        for question in questions
    ]
