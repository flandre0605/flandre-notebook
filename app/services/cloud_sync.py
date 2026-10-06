"""Ordinary-user HTTP sync. Passwords and sessions are kept in memory only."""
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from app.services.cloudbase_login import _NoRedirect

ENVIRONMENT_ID = 'flandre-d5gtb0c714184017a'
BUCKET_ID = 'flandre-question-images'
INBOX_BUCKET_ID = 'flandre-inbox-images'


class CloudSyncError(RuntimeError):
    pass


class CloudSession:
    def __init__(self, login_result, username):
        self.user_id = login_result['user_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.user_id):
            raise CloudSyncError('用户编号格式无法用于账号目录，未打开题库。')
        self.username = username
        self.token = login_result['access_token']
        self.expires_at = time.monotonic() + login_result['expires_in']
        self.closed = False
        login_result.clear()

    def require_token(self):
        if self.closed or not self.token or time.monotonic() >= self.expires_at:
            raise CloudSyncError('登录已到期，请重新登录后同步。本地修改和待上传任务已保留。')
        return self.token

    def close(self):
        self.closed = True
        self.token = ''


class CloudClient:
    bucket_id = BUCKET_ID
    def __init__(self, session, environment_id=ENVIRONMENT_ID):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,100}', environment_id):
            raise CloudSyncError('云环境编号无效。')
        self.session = session
        self.environment_id = environment_id
        self.base = f'https://{environment_id}.api.tcloudbasegateway.com'

    def request(self, path, method, body=None, mime='application/json', limit=12 * 1024 * 1024):
        token = self.session.require_token()
        request = urllib.request.Request(self.base + path, method=method, data=body,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': mime, 'Accept': '*/*', 'Cache-Control': 'no-store'})
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=30) as response:
                status, content = response.status, response.read(limit + 1)
        except urllib.error.HTTPError as error:
            with error:
                status, content = error.code, error.read(64 * 1024 + 1)
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CloudSyncError('连接中断或超时。本地修改和操作编号已保留，恢复网络后点击同步重试。') from None
        if len(content) > limit:
            raise CloudSyncError('云端响应超过限制，未更新同步游标。')
        return status, content

    def rpc(self, name, arguments):
        if name not in ('flandre_sync_push', 'flandre_sync_pull', 'flandre_inbox_submit',
                        'flandre_inbox_pull', 'flandre_inbox_finish'):
            raise CloudSyncError('同步接口无效。')
        status, content = self.request('/v1/rdb/rest/rpc/' + name, 'POST', json.dumps(arguments).encode('utf-8'))
        if status != 200:
            if status == 404:
                raise CloudSyncError('云端接口尚未部署或未刷新。请核对对应的电脑端／手机待整理部署脚本后重试。')
            if status in (401, 403):
                raise CloudSyncError('云端未授权本次操作。请重新登录并检查账号权限，本地数据已保留。')
            raise CloudSyncError(f'云端未完成同步（HTTP {status}）。请核对部署和权限配置，本地修改已保留。')
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError):
            raise CloudSyncError('同步响应无法识别，未确认上传成功。') from None
        if not isinstance(value, dict):
            raise CloudSyncError('同步响应格式无效。')
        return value

    def _key(self, key):
        if not isinstance(key, str) or not re.fullmatch(
            re.escape(self.session.user_id) + r'/[a-f0-9]{32}/[a-f0-9]{32}/[a-f0-9]{64}\.(png|jpg|jpeg|webp)', key):
            raise CloudSyncError('图片路径不属于当前账号，未发送请求。')
        return '/v1/storages/object/' + self.bucket_id + '/' + urllib.parse.quote(key, safe='/')

    def download(self, key):
        status, content = self.request(self._key(key), 'GET', limit=20 * 1024 * 1024)
        if status != 200:
            raise CloudSyncError(f'图片下载未完成（HTTP {status}），保留本地内容和同步游标。')
        return content

    def upload(self, image, source):
        content = Path(source).read_bytes()
        if len(content) != image['size'] or hashlib.sha256(content).hexdigest() != image['sha256']:
            raise CloudSyncError('暂存原图已变化或缺失，未上传；请保留本地备份并检查原图。')
        status, _ = self.request(self._key(image['key']), 'POST', content, mime=image['mime_type'], limit=128 * 1024)
        if status not in (200, 409):
            raise CloudSyncError(f'图片上传未完成（HTTP {status}），保留本地原图和待同步操作。')
        # A 409 is success only when the existing immutable object has exact bytes.
        if self.download(image['key']) != content:
            raise CloudSyncError('云端图片内容校验不一致，未提交题目附件关联。')


def synchronize(local, client):
    uploaded, downloaded = 0, 0
    # Bound one run; unfinished changes remain visibly pending for another run.
    for _ in range(200):
        pending = local.prepare()
        if pending is None:
            break
        payload = json.loads(pending['payload'])
        for image in payload.get('attachments', []):
            source = local.staged_file(pending['operation_id'], image['id'], Path(image['key']).suffix)
            client.upload(image, source)
        result = client.rpc('flandre_sync_push', dict(p_id=pending['entity_id'], p_operation_id=pending['operation_id'],
            p_base_version=pending['base_version'], p_deleted=bool(pending['deleted']), p_payload=payload))
        if result.get('status') == 'conflict':
            remote = result.get('record')
            if remote is not None:
                remote = local.validate_record(remote)
                if remote['id'] != pending['entity_id']:
                    raise CloudSyncError('冲突响应对应其他题目，已停止同步。')
            local.conflict(pending['entity_id'], remote)
            continue
        if result.get('status') != 'applied':
            raise CloudSyncError('云端未明确确认操作，保留原操作编号以便重试。')
        record = local.validate_record(result.get('record'))
        if (record['id'] != pending['entity_id'] or record['version'] != pending['base_version'] + 1
                or record['deleted'] != bool(pending['deleted'])
                or (not record['deleted'] and record['payload'] != payload)):
            raise CloudSyncError('云端确认内容与本轮操作不一致，未清除待同步操作。')
        local.acknowledge(pending, record)
        uploaded += 1
    for _ in range(100):
        cursor = local.status()['cursor']
        page = client.rpc('flandre_sync_pull', {'p_after': cursor, 'p_limit': 10})
        rows = page.get('records')
        if not isinstance(rows, list) or len(rows) > 10 or type(page.get('cursor')) is not int:
            raise CloudSyncError('变更分页响应无效，未推进同步游标。')
        prepared = []
        for row in rows:
            row = local.validate_record(row)
            if row['seq'] <= cursor:
                raise CloudSyncError('变更顺序无效，未推进同步游标。')
            cursor = row['seq']
            prepared.append(local.materialize(row, client))
        if page['cursor'] != cursor:
            raise CloudSyncError('变更游标与记录不一致，未跳过任何记录。')
        local.apply_page(prepared, cursor)
        downloaded += len(prepared)
        if len(rows) < 10:
            break
    else:
        raise CloudSyncError('本轮已接收 1000 条变化，请再次同步以接收后续内容。')
    local.succeeded()
    return dict(uploaded=uploaded, downloaded=downloaded, archived_drafts=local.archived_drafts, **local.status())
