"""Account-private photo receipts. No formal question is written on download."""
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from app.database import store
from app.services.cloud_sync import CloudClient, CloudSyncError, INBOX_BUCKET_ID
from app.services.cloud_sync_store import identity, dump
from app.services import attachments, recognition_drafts


class InboxClient(CloudClient):
    bucket_id = INBOX_BUCKET_ID


class InboxStore:
    def __init__(self, root, user_id):
        self.root = Path(root).resolve()
        self.database = self.root / 'questions.db'
        self.user_id = user_id

    def connection(self):
        return store._connection(self.database)

    def validate(self, row):
        if not isinstance(row, dict) or row.get('user_id') != self.user_id:
            raise CloudSyncError('待整理图片不属于当前账号，未接收。')
        result = dict(row)
        result['id'] = identity(row.get('id'))
        if type(row.get('seq')) is not int or row['seq'] < 1 or row.get('status') not in ('pending','processed','dismissed'):
            raise CloudSyncError('待整理记录状态无效。')
        payload = row.get('payload')
        if not isinstance(payload, dict) or len(dump(payload).encode()) > 16384:
            raise CloudSyncError('待整理内容无效。')
        if (not isinstance(payload.get('source_name'), str) or not 1 <= len(payload['source_name']) <= 200
                or not isinstance(payload.get('note'), str) or len(payload['note']) > 1000):
            raise CloudSyncError('图片名称或备注无效。')
        images = payload.get('images')
        if not isinstance(images, list) or not 1 <= len(images) <= 2:
            raise CloudSyncError('待整理原图缺失。')
        roles, ids = set(), set()
        for image in images:
            if not isinstance(image, dict):
                raise CloudSyncError('待整理图片信息无效。')
            aid, digest, mime, key = (image.get(k) for k in ('id','sha256','mime_type','key'))
            suffixes = {'image/png':('.png',),'image/jpeg':('.jpg','.jpeg'),'image/webp':('.webp',)}.get(mime, ())
            if (not isinstance(aid,str) or not re.fullmatch('[a-f0-9]{32}',aid)
                    or aid in ids or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest)
                    or type(image.get('size')) is not int or not 1 <= image['size'] <= attachments.MAX_IMAGE_BYTES
                    or image.get('role') not in ('original','crop') or image['role'] in roles
                    or key not in {f'{self.user_id}/{result["id"]}/{aid}/{digest}{s}' for s in suffixes}):
                raise CloudSyncError('待整理图片路径、归属或校验信息无效。')
            roles.add(image['role']); ids.add(aid)
        if 'original' not in roles:
            raise CloudSyncError('待整理记录必须保留原图。')
        return result

    def path(self, image):
        base = self.root / 'attachments' / 'inbox'
        target = base / (image['id'] + '-' + image['sha256'] + Path(image['key']).suffix)
        if target.resolve() != target.absolute() or not target.resolve().is_relative_to(self.root):
            raise CloudSyncError('待整理图片目录无效。')
        return target

    def materialize(self, row, client):
        for image in row['payload']['images']:
            path = self.path(image)
            if path.is_file():
                content = path.read_bytes()
            else:
                content = client.download(image['key'])
            if len(content) != image['size'] or hashlib.sha256(content).hexdigest() != image['sha256']:
                raise CloudSyncError('待整理图片校验失败，未推进接收进度。')
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                temporary = path.with_name(uuid4().hex + '.part')
                try:
                    with temporary.open('xb') as output:
                        output.write(content)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            attachments.validate_image(path)

    def pending(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM mobile_inbox WHERE status='pending' AND local_done=0 ORDER BY seq")]

    def acknowledge(self, client):
        with self.connection() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM mobile_inbox WHERE needs_ack=1')]
        for row in rows:
            remote = self.validate(client.rpc('flandre_inbox_finish', {'p_id':row['id'],'p_status':'processed'}) .get('record'))
            if remote['id'] != row['id'] or remote['status'] == 'pending' or dump(remote['payload']) != row['payload']:
                raise CloudSyncError('收录回执无效，本地收录和回执队列已保留。')
            with self.connection() as db:
                db.execute('UPDATE mobile_inbox SET status=?,seq=?,needs_ack=0 WHERE id=? AND local_done=1',
                           (remote['status'], remote['seq'], row['id']))

    def receive(self, client):
        self.acknowledge(client)
        received = 0
        for _ in range(100):
            with self.connection() as db:
                saved = db.execute("SELECT value FROM sync_state WHERE key='inbox_cursor'").fetchone()
            cursor = int(saved[0]) if saved else 0
            page = client.rpc('flandre_inbox_pull', {'p_after':cursor, 'p_limit':10})
            if not isinstance(page.get('records'),list) or len(page['records'])>10 or type(page.get('cursor')) is not int:
                raise CloudSyncError('待整理分页格式无效。')
            rows = []
            for row in page['records']:
                row = self.validate(row)
                if row['seq'] <= cursor:
                    raise CloudSyncError('待整理分页顺序无效。')
                cursor = row['seq']
                if row['status']=='pending':
                    self.materialize(row, client)
                rows.append(row)
            if page['cursor'] != cursor:
                raise CloudSyncError('待整理接收游标无效。')
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                for row in rows:
                    old = db.execute('SELECT payload FROM mobile_inbox WHERE id=?',(row['id'],)).fetchone()
                    if old and old[0] != dump(row['payload']):
                        raise CloudSyncError('已接收原图的内容被替换，未覆盖本地草稿。')
                    db.execute('INSERT INTO mobile_inbox(id,seq,status,payload) VALUES(?,?,?,?) '
                               'ON CONFLICT(id) DO UPDATE SET seq=excluded.seq,status=excluded.status',
                               (row['id'],row['seq'],row['status'],dump(row['payload'])))
                db.execute("INSERT INTO sync_state VALUES('inbox_cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(cursor),))
            received += len(rows)
            if len(rows)<10:
                return received
        raise CloudSyncError('本轮已接收 1000 项变化，请再次刷新。')

    def draft(self, item_id, profile_id=''):
        item_id = identity(item_id)
        with self.connection() as db:
            row = db.execute('SELECT * FROM mobile_inbox WHERE id=?',(item_id,)).fetchone()
        if row is None or row['status']!='pending' or row['local_done']:
            raise ValueError('这张图片已处理，未再次创建识题草稿。')
        if row['recognition_key']:
            try:
                recognition_drafts.load(row['recognition_key'])
                return row['recognition_key']
            except ValueError:
                pass  # Explicitly discarded draft: the immutable inbox photo remains.
        payload = json.loads(row['payload'])
        image = next((i for i in payload['images'] if i['role']=='crop'),payload['images'][0])
        key, state, path = recognition_drafts.create(self.path(image),profile_id)
        state['source_name'] = payload['source_name']
        try:
            recognition_drafts.save(key,state)
            with self.connection() as db:
                db.execute('UPDATE mobile_inbox SET recognition_key=? WHERE id=? AND local_done=0', (key,item_id))
                db.execute('INSERT INTO mobile_inbox_drafts VALUES(?,?)', (key,item_id))
        except Exception:
            recognition_drafts.discard(key,state)
            raise
        return key

    def original_for_draft(self, key):
        with self.connection() as db:
            row = db.execute('SELECT payload FROM mobile_inbox WHERE id='
                             '(SELECT inbox_id FROM mobile_inbox_drafts WHERE key=?)',(key,)).fetchone()
        if not row:
            return None
        image = next(i for i in json.loads(row[0])['images'] if i['role']=='original')
        return attachments.validate_image(self.path(image))


def link_replacement_draft(previous_key, new_key):
    """All re-recognition branches share the same durable duplicate guard."""
    if not previous_key:
        return
    with store._connection() as db:
        row = db.execute('SELECT inbox_id FROM mobile_inbox_drafts WHERE key=?',(previous_key,)).fetchone()
        if row:
            db.execute('INSERT INTO mobile_inbox_drafts VALUES(?,?)',(new_key,row['inbox_id']))
            db.execute('UPDATE mobile_inbox SET recognition_key=? WHERE id=?',(new_key,row['inbox_id']))
