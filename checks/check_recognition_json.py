"""Response formatting regression check; no network or user data."""
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import model_provider as provider


def check():
    question = dict(stem=r"计算 $\lim_{x\to0}x$", answer="0")
    valid = json.dumps({"questions": [question]}, ensure_ascii=False)
    assert provider._parse_json_content(f"```json\n{valid}\n```")["questions"] == [question]
    # An incomplete batch must never be salvaged as just its first complete child.
    try:
        provider._parse_json_content('{"questions":[' + json.dumps(question) + ',')
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("Accepted incomplete batch")
    malformed = r'{"questions":[{"stem":"$\lim_{x\to0}x$","answer":"0"}]}'
    with patch.object(provider, "_image_for_request", return_value=("image/png", "mock")):
        with patch.object(provider, "_request", side_effect=[malformed, valid]) as request:
            result = provider.recognize_image({}, "unused.png")
            assert result[0]["stem"] == question["stem"] and request.call_count == 2
            assert request.call_args_list[0].kwargs["max_tokens"] == 6000
            assert request.call_args.args[1][1]["content"] == malformed
        with patch.object(provider, "_request", side_effect=[malformed, "still not JSON"]) as request:
            try:
                provider.recognize_image({}, "unused.png")
            except provider.ProviderError as error:
                assert malformed in error.raw_response and request.call_count == 2
            else:
                raise AssertionError("Accepted invalid repair")
        with patch.object(provider, "_request", return_value=valid) as request:
            assert provider.recognize_image({}, "unused.png")[0]["answer"] == "0"
            assert request.call_count == 1
    profile = dict(api_key_ref="mock", base_url="https://example.com/v1",
                   endpoint_path="/chat/completions", model_id="mock", timeout_seconds=5)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({"choices": [
        {"finish_reason": "length", "message": {"content": valid}}
    ]}).encode()
    with patch.object(provider, "get_api_key", return_value="mock"), patch.object(
        provider.urllib.request, "urlopen", return_value=response
    ):
        try:
            provider._request(profile, [])
        except provider.ProviderError as error:
            assert "长度上限" in str(error) and error.raw_response == valid
        else:
            raise AssertionError("Accepted truncated response")
    print("PASS: fenced JSON, incomplete batch rejection, one formatting retry, raw response and truncation")


if __name__ == "__main__":
    check()
