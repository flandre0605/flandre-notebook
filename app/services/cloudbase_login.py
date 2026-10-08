"""CloudBase ordinary-user authentication; passwords are never persisted or logged."""
import json
import re
import time
import urllib.error
import urllib.request


class LoginCheckError(RuntimeError):
    pass


class SessionExpired(LoginCheckError):
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
    # Verification tools display only this summary.
    return {"user_id": user_id, "expires_in": expires}


def _auth_request(environment_id, path, arguments, device_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,100}", environment_id):
        raise LoginCheckError("云环境编号格式不正确。")
    request = urllib.request.Request(
        f"https://{environment_id}.api.tcloudbasegateway.com/auth/v1/{path}",
        data=json.dumps(arguments).encode("utf-8"),
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
        if isinstance(payload, dict) and payload.get("error"):
            _auth_error(payload)
        raise LoginCheckError(f"账号请求未确认完成（HTTP {error.code}）。注册时请先尝试登录，避免重复提交。") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise LoginCheckError("无法连接云端，请检查网络后手动重试。") from None
    try:
        if len(body) > 128 * 1024:
            raise ValueError("oversized response")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("invalid response")
        if payload.get("error"):
            _auth_error(payload)
        return payload
    except (ValueError, UnicodeError):
        raise LoginCheckError("云端返回的内容无法识别，尚未验证成功。") from None


def _auth_error(payload):
    if payload.get('error') in ('invalid_grant', 'invalid_refresh_token', 'unauthenticated'):
        raise SessionExpired('登录已失效，请重新登录。本地题库和待同步修改已保留。')
    messages = {
        "invalid_verification_code": "验证码不正确，请检查后重试。",
        "verification_code_expired": "验证码已过期，请重新获取。",
        "verification_expired": "验证码已过期，请重新获取。",
        "invalid_verification_token": "邮箱验证已失效，请重新获取验证码。",
        "invalid_email": "邮箱格式不正确。",
        "email_already_exists": "此邮箱已注册，请返回登录。",
        "email_exists": "此邮箱已注册，请返回登录。",
        "username_already_exists": "用户名已被使用，请换一个。",
        "username_exists": "用户名已被使用，请换一个。",
        "already_exists": "邮箱或用户名已被使用，请尝试登录或更换。",
        "weak_password": "密码未达到云端强度要求，请使用更强的密码。",
        "rate_limit_exceeded": "请求过于频繁，请稍后再试。",
        "resource_exhausted": "验证码发送暂时受限，请稍后再试。",
        "captcha_required": "云端要求额外的人机验证，本版暂不支持此验证，请稍后再试。",
        "unimplemented": "云端未启用此方式。请管理员开启邮箱验证码及用户名密码登录。",
    }
    code = payload.get("error")
    if isinstance(code, str) and code in messages:
        raise LoginCheckError(messages[code])
    _summary(payload)  # Reuse the existing safe sign-in error mapping.


def _session(payload):
    summary = _summary(payload)
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", summary["user_id"])
            or len(payload["access_token"]) > 4096 or summary["expires_in"] > 86400):
        raise LoginCheckError("登录响应无效。")
    result = dict(summary, access_token=payload["access_token"])
    if 'refresh_token' in payload:
        value = payload['refresh_token']
        if not isinstance(value, str) or not 1 <= len(value) <= 4096:
            raise LoginCheckError('续期凭据无效。')
        result['refresh_token'] = value
    return result


def refresh_session(environment_id, refresh_token, device_id, expected_user):
    payload = _session(_auth_request(environment_id, 'token',
        {'grant_type':'refresh_token', 'refresh_token':refresh_token}, device_id))
    if payload['user_id'] != expected_user:
        payload.clear()
        raise SessionExpired('续期账号不匹配，请重新登录。原题库未改变。')
    if not payload.get('refresh_token'):
        raise LoginCheckError('续期响应缺少新的凭据，请重新登录。')
    return payload


def login_session(environment_id, username, password, device_id):
    if not username.strip() or not password:
        raise LoginCheckError("请填写用户名和密码。")
    return _session(_auth_request(environment_id, "signin",
        {"username": username.strip(), "password": password}, device_id))


def registration_fields(email, username=None, password=None):
    email = email.strip()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise LoginCheckError("请填写有效的邮箱地址。")
    if username is not None and not re.fullmatch(r"[A-Za-z0-9_-]{5,24}", username):
        raise LoginCheckError("用户名需为 5～24 位字母、数字、下划线或短横线。")
    if password is not None and (not 8 <= len(password) <= 32
            or not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password)):
        raise LoginCheckError("密码需为 8～32 位，包含字母和数字。")
    return email


class EmailChallenge:
    """Email-bound, short-lived verification. Never persisted or retried automatically."""
    def __init__(self, email, payload):
        identity, seconds = payload.get("verification_id"), payload.get("expires_in")
        if (not isinstance(identity, str) or not 1 <= len(identity) <= 4096
                or type(seconds) is not int or not 0 < seconds <= 3600):
            raise LoginCheckError("验证码发送响应无效，请稍后重新获取。")
        self.email, self.identity = email, identity
        self.deadline = time.monotonic() + seconds

    def signup(self, environment_id, email, username, password, code, device_id):
        email = registration_fields(email, username, password)
        if email != self.email or not self.identity or time.monotonic() >= self.deadline:
            raise LoginCheckError("请为当前邮箱重新获取验证码。")
        if not re.fullmatch(r"[0-9]{6}", code):
            raise LoginCheckError("请输入邮件中的 6 位数字验证码。")
        verified = _auth_request(environment_id, "verification/verify",
            {"verification_id": self.identity, "verification_code": code}, device_id)
        token = verified.get("verification_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 4096:
            raise LoginCheckError("邮箱验证响应无效，请重新获取验证码。")
        self.identity = ""  # A verified challenge is consumed; uncertain signup outcomes require sign-in first.
        try:
            return _session(_auth_request(environment_id, "signup", {"email": email,
                "username": username, "password": password, "verification_token": token}, device_id))
        except LoginCheckError as error:
            raise LoginCheckError(f"{error} 若已收到注册结果请先登录；继续注册需重新获取验证码。") from None


def send_registration_code(environment_id, email, device_id):
    email = registration_fields(email)
    result = _auth_request(environment_id, "verification", {"email": email, "target": "ANY"}, device_id)
    if result.get("is_user") is True:
        raise LoginCheckError("此邮箱已注册，请返回登录。")
    return EmailChallenge(email, result)


def validate_login(environment_id, username, password, device_id):
    session = login_session(environment_id, username, password, device_id)
    return {"user_id": session["user_id"], "expires_in": session["expires_in"]}
