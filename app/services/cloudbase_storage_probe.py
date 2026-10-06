"""Small synthetic PNG checks, confined to a dedicated private PG bucket."""
import json
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4
import zlib

from app.services.cloudbase_login import LoginCheckError, _NoRedirect, login_session

BUCKET_ID = 'flandre-image-probe'
MAX_RESPONSE = 128 * 1024


class StorageProbeError(RuntimeError):
    pass


def _png(rgb):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0' + bytes(rgb))) + chunk(b'IEND', b''))


def _request(environment_id, method, token, key, body=None, sign=False):
    if (not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,100}', environment_id)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}/flandre-probe-[a-f0-9]{32}\.png', key)):
        raise StorageProbeError('环境或测试图片路径不正确。')
    path = 'sign/' if sign else ''
    url = (f'https://{environment_id}.api.tcloudbasegateway.com/v1/storages/object/'
           f'{path}{BUCKET_ID}/' + urllib.parse.quote(key, safe='/'))
    headers = {'Accept': '*/*', 'Cache-Control': 'no-store'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if body is not None:
        headers['Content-Type'] = 'application/json' if sign else 'image/png'
    request = urllib.request.Request(url, method=method, headers=headers, data=body)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=20) as response:
            status, data = response.status, response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as error:
        with error:
            status, data = error.code, error.read(MAX_RESPONSE + 1)
    except (urllib.error.URLError, OSError, TimeoutError):
        raise StorageProbeError('网络请求未完成；测试图片可能保留，请恢复网络后检查专用测试桶。') from None
    if len(data) > MAX_RESPONSE:
        raise StorageProbeError('图片接口响应过大，未判定成功。')
    return status, data


def _json(data):
    try:
        result = json.loads(data)
        return result if isinstance(result, dict) else {}
    except (ValueError, UnicodeError):
        return {}


def _ok(response, step):
    status, data = response
    if status != 200:
        hint = '请先执行私有测试桶脚本。' if status == 404 else '请核对 PG 云存储配置和权限。'
        raise StorageProbeError(f'{step}未完成（HTTP {status}）。{hint}')
    return data


def _read(environment_id, token, key, expected):
    data = _ok(_request(environment_id, 'GET', token, key), '下载自己的测试图片')
    if data != expected:
        raise StorageProbeError('下载内容与上传内容不一致，未判定成功。')


def _blocked(response, step):
    status, data = response
    # 404 counts only at a known-existing object after successful owner access.
    # 400 is not blindly accepted: bad routes/arguments are not permission evidence.
    payload = _json(data)
    code = payload.get('code', payload.get('Code'))
    if status in (401, 403, 404) or (status == 400 and code in (
            'STORAGE_PERMISSION_DENIED', 'STORAGE_EXCEED_AUTHORITY', '42501')):
        return
    raise StorageProbeError(f'{step}未通过（HTTP {status}），未将异常接口或可访问的响应视为隔离成功。')


def verify_storage(environment_id, username, password, device_id,
                   second_username='', second_password=''):
    sessions, records, checks = [], [], []
    primary_error = None
    try:
        sessions.append(login_session(environment_id, username, password, device_id))
        if second_username:
            sessions.append(login_session(environment_id, second_username, second_password, device_id))
            if sessions[0]['user_id'] == sessions[1]['user_id']:
                raise StorageProbeError('两个账号相同，不能验证图片的多用户隔离。')
        for index, session in enumerate(sessions):
            key = f"{session['user_id']}/flandre-probe-{uuid4().hex}.png"
            original, updated = _png((220, 30, index)), _png((20, 160, index))
            token = session['access_token']
            records.append((token, key))  # Include failed/ambiguous uploads in cleanup.
            payload = _json(_ok(_request(environment_id, 'POST', token, key, original), '上传测试图片'))
            if not payload.get('Id') or payload.get('Key') != f'{BUCKET_ID}/{key}':
                # Some deployments return a key relative to the bucket.
                if not payload.get('Id') or payload.get('Key') != key:
                    raise StorageProbeError('上传响应缺少正确的图片编号或路径，未判定成功。')
            _read(environment_id, token, key, original)
            _ok(_request(environment_id, 'PUT', token, key, updated), '覆盖自己的测试图片')
            _read(environment_id, token, key, updated)
            signed = _json(_ok(_request(environment_id, 'POST', token, key,
                              json.dumps({'expiresIn': 60}).encode(), sign=True), '生成自己的临时图片链接'))
            if not isinstance(signed.get('signedURL'), str) or not signed['signedURL']:
                raise StorageProbeError('临时图片链接响应不完整，未判定成功。')
            # Never expose or follow the signed URL: it is a temporary credential.
            checks.append(f'账号 {index + 1}：上传、原样下载、覆盖后下载及生成临时链接通过')
            _blocked(_request(environment_id, 'GET', None, key), '无凭据直接下载图片')
            _read(environment_id, token, key, updated)
        checks.append('无登录凭据：无法直接下载本轮私有图片（未测公开密钥匿名角色）')
        if len(sessions) == 2:
            for index, session in enumerate(sessions):
                token = session['access_token']
                target_token, target = records[1 - index]
                expected = _png((20, 160, 1 - index))
                _read(environment_id, target_token, target, expected)
                _blocked(_request(environment_id, 'GET', token, target), '跨账号下载图片')
                _blocked(_request(environment_id, 'POST', token, target,
                                  b'{"expiresIn":60}', sign=True), '跨账号生成临时链接')
                _blocked(_request(environment_id, 'PUT', token, target, _png((1, 2, 3))), '跨账号覆盖图片')
                _blocked(_request(environment_id, 'DELETE', token, target), '跨账号删除图片')
                _read(environment_id, target_token, target, expected)
                forged = target.split('/')[0] + f'/flandre-probe-{uuid4().hex}.png'
                records.append((token, forged))
                _blocked(_request(environment_id, 'POST', token, forged, _png((1, 2, 3))), '冒用其他账号目录上传')
                records.pop()  # Rejected insertion created no object to delete.
            checks.append('两个账号：互相下载、生成临时链接、覆盖、删除及冒用目录上传均被阻止')
        else:
            checks.append('两个普通账号的图片隔离：待验证')
        for token, key in records[:len(sessions)]:
            _ok(_request(environment_id, 'DELETE', token, key), '删除自己的测试图片')
            if _request(environment_id, 'GET', token, key)[0] != 404:
                raise StorageProbeError('删除后未确认图片不存在，未判定成功。')
        checks.append('自己的图片：删除及删除后不存在检查通过')
        return {'user_id': sessions[0]['user_id'], 'checks': checks}
    except (StorageProbeError, LoginCheckError) as error:
        primary_error = error
        raise
    finally:
        remaining = []
        for token, key in records:
            try:
                status, _ = _request(environment_id, 'DELETE', token, key)
                # Denied spoof paths are not necessarily ours; confirm absent via uploader.
                if status not in (200, 404) or _request(environment_id, 'GET', token, key)[0] != 404:
                    remaining.append(key)
            except StorageProbeError:
                remaining.append(key)
        for session in sessions:
            session.clear()
        if remaining:
            prefix = str(primary_error) + '\n' if primary_error else ''
            raise StorageProbeError(prefix + '部分测试图片未确认清理，请在控制台检查 flandre-image-probe；'
                                    '本轮测试路径：' + '、'.join(remaining))
