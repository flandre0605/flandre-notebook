"""Short-lived CloudBase test sessions; never persisted or logged."""
import json
import re
import urllib.error
import urllib.request


class LoginCheckError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _summary(payload):
    if not isinstance(payload, dict):
        raise LoginCheckError("登录响应格式异常，尚未验证成功。")
    errors = {
        "invalid_username_or_password": "用户名或密码不正确，请检查后再试。",
        "captcha_required": "服务要求验证码，请在控制台确认账号状态后再试。",
        "password_not_set": "该账号尚未设置密码。",
        "invalid_status": "账号暂时被锁定，请稍后再试。",
        "unimplemented": "请确认该环境已启用用户名密码登录。",
    }
    if payload.get("error"):
        # Never display an arbitrary server message: it may echo credentials.
        code = payload["error"]
        message = errors.get(code) if isinstance(code, str) else None
        raise LoginCheckError(message or "云端未接受登录，请检查环境和登录配置。")
    user_id, expires = payload.get("sub"), payload.get("expires_in")
    if (not isinstance(payload.get("access_token"), str) or not payload["access_token"]
            or str(payload.get("token_type", "")).lower() != "bearer"
            or not isinstance(user_id, str) or not 1 <= len(user_id) <= 64
            or type(expires) is not int or expires <= 0):
        raise LoginCheckError("登录响应缺少有效凭据或用户编号，尚未验证成功。")
    # Access and refresh tokens are discarded rather than returned to the UI.
    return {"user_id": user_id, "expires_in": expires}


def login_session(environment_id, username, password, device_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,100}", environment_id):
        raise LoginCheckError("云环境编号格式不正确。")
    if not username.strip() or not password:
        raise LoginCheckError("请填写用户名和密码。")
    request = urllib.request.Request(
        f"https://{environment_id}.api.tcloudbasegateway.com/auth/v1/signin",
        data=json.dumps({"username": username.strip(), "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "x-device-id": device_id}, method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            body = response.read(128 * 1024 + 1)
    except urllib.error.HTTPError as error:
        with error:
            body = error.read(128 * 1024 + 1)
        try:
            payload = json.loads(body) if len(body) <= 128 * 1024 else None
        except (ValueError, UnicodeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            _summary(payload)
        raise LoginCheckError(f"登录请求失败（HTTP {error.code}），未自动重试。") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise LoginCheckError("无法连接云端，请检查网络后手动重试。") from None
    try:
        if len(body) > 128 * 1024:
            raise ValueError("oversized response")
        payload = json.loads(body)
        summary = _summary(payload)
        return dict(summary, access_token=payload["access_token"])
    except (ValueError, UnicodeError):
        raise LoginCheckError("云端返回的内容无法识别，尚未验证成功。") from None


def validate_login(environment_id, username, password, device_id):
    session = login_session(environment_id, username, password, device_id)
    return {"user_id": session["user_id"], "expires_in": session["expires_in"]}
