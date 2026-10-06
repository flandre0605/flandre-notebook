"""Test only the dedicated probe table, using ordinary user credentials."""
import json
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from app.services.cloudbase_login import LoginCheckError, _NoRedirect, login_session


class ProbeError(RuntimeError):
    pass


def _request(environment_id, method, token, row_id=None, data=None):
    query = {"select": "id,user_id,note", "limit": "100"}
    if row_id:
        query["id"] = f"eq.{row_id}"
    url = (f"https://{environment_id}.api.tcloudbasegateway.com/v1/rdb/rest/v1/"
           "flandre_connection_probe?" + urllib.parse.urlencode(query))
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "Prefer": "return=representation"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, method=method, headers=headers,
                                    data=None if data is None else json.dumps(data).encode("utf-8"))
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=20) as response:
            status, body = response.status, response.read(128 * 1024 + 1)
    except urllib.error.HTTPError as error:
        # Error responses can echo submitted values; expose only the HTTP status.
        with error:
            return error.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProbeError("网络请求未完成。请恢复网络后重新验证；测试记录可能暂时保留。") from None
    try:
        if len(body) > 128 * 1024:
            raise ValueError("oversized response")
        return status, json.loads(body)
    except (ValueError, UnicodeError):
        raise ProbeError("云端数据响应无法识别，未判定验证成功。") from None


def _rows(response, step):
    status, payload = response
    if status not in (200, 201) or not isinstance(payload, list):
        if status == 404:
            raise ProbeError(f"{step}未完成：请先在 SQL 编辑器执行建表脚本；新表可能需要稍候才可访问。")
        raise ProbeError(f"{step}未完成（HTTP {status}），请检查建表脚本和权限配置。")
    if any(not isinstance(row, dict) for row in payload):
        raise ProbeError(f"{step}返回格式异常。")
    return payload


def _own_row(response, row_id, user_id, note, step):
    rows = _rows(response, step)
    if (len(rows) != 1 or rows[0].get("id") != row_id
            or rows[0].get("user_id") != user_id or rows[0].get("note") != note):
        raise ProbeError(f"{step}未通过：记录或账号归属与预期不符。")


def _blocked(response, step, allow_empty=False):
    status, payload = response
    if status in (401, 403) or (allow_empty and status == 200 and payload == []):
        return
    raise ProbeError(f"{step}未通过（HTTP {status}）；未将返回数据的请求视为隔离成功。")


def verify_database(environment_id, username, password, device_id,
                    second_username="", second_password=""):
    session = login_session(environment_id, username, password, device_id)
    second = None
    records = []
    checks = []
    failures = []
    primary_error = None
    try:
        token, user_id = session["access_token"], session["user_id"]
        if second_username:
            second = login_session(environment_id, second_username, second_password, device_id)
            if second["user_id"] == user_id:
                raise ProbeError("第二个账号与第一个账号相同，不能用来验证多用户隔离。")
        row_id = str(uuid4())
        records.append((token, row_id))
        _own_row(_request(environment_id, "POST", token,
                          data={"id": row_id, "note": "Flandre connection check"}),
                 row_id, user_id, "Flandre connection check", "新增自己的测试记录")
        _own_row(_request(environment_id, "GET", token, row_id),
                 row_id, user_id, "Flandre connection check", "读取自己的测试记录")
        all_rows = _rows(_request(environment_id, "GET", token), "查询可见测试记录")
        if any(row.get("user_id") != user_id for row in all_rows):
            raise ProbeError("查询可见记录未通过：发现其他账号的数据。")
        _own_row(_request(environment_id, "PATCH", token, row_id, {"note": "Updated check"}),
                 row_id, user_id, "Updated check", "修改自己的测试记录")
        checks.append("自己的记录：新增、读取、修改通过")
        # Remember this attempted insertion for cleanup if a faulty policy permits it.
        spoof_id = str(uuid4())
        records.append((token, spoof_id))
        _blocked(_request(environment_id, "POST", token, data={
            "id": spoof_id, "user_id": "probe-other-" + uuid4().hex, "note": "Spoof check"}),
            "伪造其他账号归属")
        checks.append("伪造其他账号归属：被拒绝")
        _blocked(_request(environment_id, "GET", None, row_id), "无登录凭据读取", allow_empty=True)
        checks.append("无登录凭据：未读到测试记录（未测公开密钥的匿名角色）")
        if second:
            other_token, other_id = second["access_token"], second["user_id"]
            other_row = str(uuid4())
            records.append((other_token, other_row))
            _own_row(_request(environment_id, "POST", other_token,
                              data={"id": other_row, "note": "Second account check"}),
                     other_row, other_id, "Second account check", "第二个账号新增自己的记录")
            # B must not read, edit or delete A's row, and vice versa.
            for caller, target in ((other_token, row_id), (token, other_row)):
                _blocked(_request(environment_id, "GET", caller, target), "跨账号读取", allow_empty=True)
                _blocked(_request(environment_id, "PATCH", caller, target, {"note": "Cross check"}),
                         "跨账号修改", allow_empty=True)
                _blocked(_request(environment_id, "DELETE", caller, target), "跨账号删除", allow_empty=True)
            _own_row(_request(environment_id, "GET", token, row_id),
                     row_id, user_id, "Updated check", "跨账号操作后检查第一个账号的记录")
            _own_row(_request(environment_id, "GET", other_token, other_row),
                     other_row, other_id, "Second account check", "跨账号操作后检查第二个账号的记录")
            spoof_id = str(uuid4())
            records.append((other_token, spoof_id))
            _blocked(_request(environment_id, "POST", other_token,
                              data={"id": spoof_id, "user_id": user_id, "note": "Cross owner check"}),
                     "第二个账号冒用第一个账号归属")
            checks.append("两个账号：各自可写，互相读取、修改、删除及冒用归属均被阻止")
        else:
            checks.append("两个普通账号之间的隔离：待验证")
        _own_row(_request(environment_id, "DELETE", token, row_id),
                 row_id, user_id, "Updated check", "删除自己的测试记录")
        if _rows(_request(environment_id, "GET", token, row_id), "检查删除结果"):
            raise ProbeError("删除验证未通过：仍可读取已删除的测试记录。")
        checks.append("自己的记录：删除及删除后查询通过")
        return {"user_id": user_id, "expires_in": session["expires_in"], "checks": checks}
    except (ProbeError, LoginCheckError) as error:
        primary_error = error
        raise
    finally:
        # Clean up only random IDs from this run, never all of the account's records.
        for owner_token, record_id in records:
            try:
                _rows(_request(environment_id, "DELETE", owner_token, record_id), "清理测试记录")
            except ProbeError:
                failures.append(record_id)
        session.clear()
        if second:
            second.clear()
        if failures:
            prefix = f"{primary_error}\n" if isinstance(primary_error, (ProbeError, LoginCheckError)) else ""
            raise ProbeError(prefix + "验证结束，但部分测试记录未确认清理。请在控制台检查测试表；"
                             "本工具没有清理其他记录，也未判定整轮验证完成。")
