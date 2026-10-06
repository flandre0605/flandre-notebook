"""Per-workspace sync state. Every operation uses an explicitly captured directory."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from uuid import UUID, uuid4

from app.database import store
from app.question_data import QUESTION_FIELDS, database_values, validate_question


def identity(value):
    if not isinstance(value, str):
        raise ValueError('同步编号无效。')
    return UUID(value).hex


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class SyncStore:
    def __init__(self, root, user_id, environment_id):
        self.root = Path(root).resolve()
        self.database = self.root / 'questions.db'
        self.user_id = user_id
        self.environment_id = environment_id
        self.archived_drafts = 0

    def connection(self):
        return store._connection(self.database)

    def bind(self):
        with self.connection() as db:
            previous = dict(db.execute('SELECT key,value FROM sync_state'))
            if previous.get('user_id', self.user_id) != self.user_id or previous.get('environment_id', self.environment_id) != self.environment_id:
                raise ValueError('此数据目录属于其他账号或环境，未打开。')
            if not previous.get('user_id') and db.execute('SELECT count(*) FROM questions').fetchone()[0]:
                raise ValueError('账号数据目录已有未绑定题库，请先在本地空间备份并导入。')
            for key, value in (('user_id', self.user_id), ('environment_id', self.environment_id), ('enabled', '1')):
                db.execute('INSERT INTO sync_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    def status(self):
        with self.connection() as db:
            counts = db.execute('SELECT sum(dirty),sum(conflict IS NOT NULL) FROM sync_entities').fetchone()
            state = dict(db.execute('SELECT key,value FROM sync_state'))
        return {'pending': counts[0] or 0, 'conflicts': counts[1] or 0,
                'last_success': state.get('last_success', ''), 'cursor': int(state.get('cursor', '0'))}

    def _file(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_relative_to((self.root / 'attachments').resolve()) or not path.is_file():
            raise ValueError('题目原图缺失或路径无效，保留待同步修改，请恢复图片后重试。')
        return path

    def prepare(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute('SELECT o.* FROM sync_outbox o JOIN sync_entities e ON e.id=o.entity_id '
                                 'WHERE e.conflict IS NULL ORDER BY o.rowid LIMIT 1').fetchone()
            if pending:
                return dict(pending)
            entity = db.execute('SELECT * FROM sync_entities WHERE dirty=1 AND conflict IS NULL ORDER BY rowid LIMIT 1').fetchone()
            if entity is None:
                return None
            operation = uuid4().hex
            payload = {}
            if not entity['deleted']:
                question = db.execute('SELECT * FROM questions WHERE id=?', (entity['local_id'],)).fetchone()
                if question is None:
                    raise ValueError('待同步题目不存在，未推进同步。')
                review = db.execute('SELECT mastery,due_at,last_reviewed_at,review_count FROM review_state WHERE question_id=?',
                                    (entity['local_id'],)).fetchone()
                payload = {'question': validate_question(dict(question)), 'review': dict(review) if review else None, 'attachments': []}
                for row in db.execute('SELECT a.*,s.id AS cloud_id FROM attachments a JOIN sync_attachments s ON s.local_id=a.id '
                                      'WHERE a.question_id=? ORDER BY a.id', (entity['local_id'],)):
                    source = self._file(row['relative_path'])
                    from app.services.attachments import validate_image
                    validate_image(source)
                    if source.stat().st_size > 20 * 1024 * 1024:
                        raise ValueError('待同步图片超过 20 MB，请缩小图片后重试。')
                    target = self.staged_file(operation, row['cloud_id'], source.suffix.lower())
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    digest = hashlib.sha256(target.read_bytes()).hexdigest()
                    payload['attachments'].append(dict(id=row['cloud_id'],
                        key=f"{self.user_id}/{entity['id']}/{row['cloud_id']}/{digest}{source.suffix.lower()}",
                        sha256=digest, size=target.stat().st_size, mime_type=row['mime_type'], original_name=row['original_name']))
                if len(payload['attachments']) > 50 or len(dump(payload).encode()) > 1024 * 1024:
                    raise ValueError('单题内容或附件数量超过同步上限（1 MB 文本、50 张图片）。')
                if len(payload['attachments']) != db.execute('SELECT count(*) FROM attachments WHERE question_id=?',
                                                            (entity['local_id'],)).fetchone()[0]:
                    raise ValueError('附件编号映射缺失，未跳过任何原图。')
            db.execute('INSERT INTO sync_outbox VALUES(?,?,?,?,?,?)',
                       (operation, entity['id'], entity['revision'], entity['base_version'], entity['deleted'], dump(payload)))
            return dict(db.execute('SELECT * FROM sync_outbox WHERE operation_id=?', (operation,)).fetchone())

    def staged_file(self, operation, attachment_id, suffix):
        if suffix not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise ValueError('附件格式无法同步。')
        base = self.root / 'attachments' / '_sync_staging'
        path = base / identity(operation) / (identity(attachment_id) + suffix)
        if path.resolve() != path or not path.resolve().is_relative_to(base):
            raise ValueError('同步暂存目录包含外部链接。')
        return path

    def acknowledge(self, pending, record):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM sync_outbox WHERE operation_id=?', (pending['operation_id'],)).fetchone()
            if row is None:
                raise ValueError('待同步操作已变化，未应用云端确认。')
            db.execute('UPDATE sync_entities SET base_version=?,dirty=CASE WHEN revision=? THEN 0 ELSE 1 END WHERE id=?',
                       (record['version'], pending['revision'], pending['entity_id']))
            db.execute('DELETE FROM sync_outbox WHERE operation_id=?', (pending['operation_id'],))
        # Staging is immutable and belongs only to this acknowledged operation.
        base = self.root / 'attachments' / '_sync_staging'
        directory = base / identity(pending['operation_id'])
        if directory.resolve() == directory and directory.parent == base and directory.exists():
            try:
                shutil.rmtree(directory)
            except OSError:
                pass  # A harmless unreferenced staging copy may remain.

    def conflict(self, entity_id, record):
        with self.connection() as db:
            db.execute('UPDATE sync_entities SET conflict=? WHERE id=?', (dump(record), entity_id))

    def validate_record(self, record):
        if not isinstance(record, dict) or record.get('user_id') != self.user_id:
            raise ValueError('云端返回了不属于当前账号的数据，已停止同步。')
        record = dict(record, id=identity(record.get('id')))
        if (type(record.get('version')) is not int or record['version'] < 1
                or type(record.get('seq')) is not int or record['seq'] < 1
                or type(record.get('deleted')) is not bool):
            raise ValueError('云端版本或变更编号无效，未推进同步。')
        if record['deleted']:
            return record
        payload = record.get('payload')
        if not isinstance(payload, dict) or len(dump(payload).encode()) > 1024 * 1024:
            raise ValueError('云端题目格式或大小无效。')
        payload = dict(payload, question=validate_question(payload.get('question')))
        review = payload.get('review')
        if review is not None:
            if not isinstance(review, dict) or review.get('mastery') not in ('mastered', 'unsure', 'unknown'):
                raise ValueError('云端掌握状态无效。')
            if type(review.get('review_count')) is not int or review['review_count'] < 1:
                raise ValueError('云端复习次数无效。')
            for field in ('due_at', 'last_reviewed_at'):
                if not isinstance(review.get(field), str):
                    raise ValueError('云端复习时间无效。')
                datetime.strptime(review[field], '%Y-%m-%d %H:%M:%S')
        manifest = payload.get('attachments')
        if not isinstance(manifest, list) or len(manifest) > 50:
            raise ValueError('云端附件列表无效。')
        ids = set()
        for image in manifest:
            if not isinstance(image, dict) or identity(image.get('id')) != image['id'] or image['id'] in ids:
                raise ValueError('云端附件编号无效或重复。')
            ids.add(image['id'])
            if not isinstance(image.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', image['sha256']):
                raise ValueError('云端附件校验值无效。')
            key = image.get('key', '')
            if not isinstance(key, str) or not re.fullmatch(
                    re.escape(f"{self.user_id}/{record['id']}/{image['id']}/{image['sha256']}") + r'\.(png|jpg|jpeg|webp)', key):
                raise ValueError('云端附件归属或路径无效。')
            mime = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.webp':'image/webp'}[Path(key).suffix]
            if image.get('mime_type') != mime or type(image.get('size')) is not int or not 1 <= image['size'] <= 20 * 1024 * 1024:
                raise ValueError('云端附件格式或大小无效。')
            if not isinstance(image.get('original_name'), str) or len(image['original_name']) > 260:
                raise ValueError('云端附件名称无效。')
        return dict(record, payload=payload)

    def materialize(self, record, client):
        record = self.validate_record(record)
        files = {}
        if record['deleted']:
            return record, files
        for image in record['payload']['attachments']:
            relative = f"attachments/cloud/{image['id']}-{image['sha256']}{Path(image['key']).suffix}"
            target = (self.root / relative).resolve()
            if not target.is_relative_to(self.root) or not target.is_relative_to((self.root / 'attachments').resolve()):
                raise ValueError('账号图片目录包含外部链接，未同步。')
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != image['sha256']:
                content = client.download(image['key'])
                if len(content) != image['size'] or hashlib.sha256(content).hexdigest() != image['sha256']:
                    raise ValueError('下载原图校验未通过，保留同步游标，请重试。')
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + '.' + uuid4().hex + '.part')
                try:
                    temporary.write_bytes(content)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            files[image['id']] = relative
            from app.services.attachments import validate_image
            validate_image(target)
        return record, files

    def apply_page(self, prepared, cursor):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE sync_state SET value='1' WHERE key='applying'")
            for record, files in prepared:
                self._apply(db, record, files)
            db.execute("UPDATE sync_state SET value=? WHERE key='cursor'", (str(cursor),))
            db.execute("UPDATE sync_state SET value='0' WHERE key='applying'")

    def _apply(self, db, record, files):
        entity = db.execute('SELECT * FROM sync_entities WHERE id=?', (record['id'],)).fetchone()
        if entity and entity['base_version'] >= record['version']:
            return
        if entity and (entity['dirty'] or entity['conflict'] is not None):
            db.execute('UPDATE sync_entities SET conflict=? WHERE id=?', (dump(record), record['id']))
            return  # Local content remains intact; cursor may advance over a retained conflict.
        if entity and entity['local_id'] is not None:
            self._archive_edit_draft(db, entity, record)
        if record['deleted']:
            if entity and entity['local_id'] is not None:
                db.execute('DELETE FROM questions WHERE id=?', (entity['local_id'],))
                db.execute('DELETE FROM workspace_state WHERE key=?', (f"question:{entity['local_id']}",))
            db.execute('INSERT INTO sync_entities(id,local_id,base_version,deleted,dirty) VALUES(?,NULL,?,1,0) '
                       'ON CONFLICT(id) DO UPDATE SET local_id=NULL,base_version=excluded.base_version,deleted=1,dirty=0',
                       (record['id'], record['version']))
            return
        question = record['payload']['question']
        if entity and entity['local_id'] is not None:
            qid = entity['local_id']
            db.execute(f"UPDATE questions SET {','.join(f'{field}=?' for field in QUESTION_FIELDS)},updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (*database_values(question), qid))
            db.execute('DELETE FROM attachments WHERE question_id=?', (qid,))
        else:
            qid = db.execute(f"INSERT INTO questions({','.join(QUESTION_FIELDS)}) VALUES({','.join('?' for _ in QUESTION_FIELDS)})",
                             database_values(question)).lastrowid
        for image in record['payload']['attachments']:
            aid = db.execute('INSERT INTO attachments(question_id,relative_path,original_name,mime_type) VALUES(?,?,?,?)',
                             (qid, files[image['id']], image['original_name'], image['mime_type'])).lastrowid
            db.execute('INSERT INTO sync_attachments VALUES(?,?)', (aid, image['id']))
        db.execute('DELETE FROM review_state WHERE question_id=?', (qid,))
        review = record['payload'].get('review')
        if review:
            db.execute('INSERT INTO review_state VALUES(?,?,?,?,?)',
                       (qid, review['mastery'], review['due_at'], review['last_reviewed_at'], review['review_count']))
        db.execute('INSERT INTO sync_entities(id,local_id,base_version,deleted,dirty) VALUES(?,?,?,0,0) '
                   'ON CONFLICT(id) DO UPDATE SET local_id=excluded.local_id,base_version=excluded.base_version,deleted=0,dirty=0,conflict=NULL',
                   (record['id'], qid, record['version']))

    def _archive_edit_draft(self, db, entity, remote):
        key = f"question:{entity['local_id']}"
        draft = db.execute('SELECT payload FROM workspace_state WHERE key=?', (key,)).fetchone()
        if draft is None:
            return
        folder = self.root / 'attachments' / '_conflicts' / (entity['id'] + '-' + uuid4().hex)
        if not folder.resolve().is_relative_to(self.root):
            raise ValueError('草稿副本目录包含外部链接。')
        folder.mkdir(parents=True)
        (folder / 'local-edit-draft.json').write_text(dump({'workspace_key': key, 'draft': json.loads(draft['payload']),
            'remote': remote}), encoding='utf-8')
        db.execute('DELETE FROM workspace_state WHERE key=?', (key,))
        self.archived_drafts += 1

    def conflicts(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT e.*,q.stem FROM sync_entities e LEFT JOIN questions q ON q.id=e.local_id '
                                                   'WHERE e.conflict IS NOT NULL ORDER BY e.rowid')]

    def resolve(self, entity_id, keep_local, client):
        with self.connection() as db:
            row = db.execute('SELECT * FROM sync_entities WHERE id=? AND conflict IS NOT NULL', (entity_id,)).fetchone()
        if row is None:
            raise ValueError('冲突已发生变化，请重新打开列表。')
        remote = json.loads(row['conflict'])
        if remote is None:
            raise ValueError('云端记录缺失，未自动重新创建，请保留本地备份并检查后台。')
        prepared = self.materialize(remote, client)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM sync_entities WHERE id=?', (entity_id,)).fetchone()
            if current['revision'] != row['revision'] or current['conflict'] != row['conflict']:
                raise ValueError('处理期间题目已变化，保留两份内容，请重试。')
            # Preserve a local conflict copy including images; safe to inspect after choosing cloud.
            if current['local_id'] is not None:
                self._archive_conflict(db, current)
            pending = db.execute('SELECT * FROM sync_outbox WHERE entity_id=?', (entity_id,)).fetchone()
            if pending:
                archive = self.root / 'attachments' / '_conflicts' / (entity_id + '-' + pending['operation_id'] + '.json')
                if not archive.resolve().is_relative_to(self.root):
                    raise ValueError('冲突备份目录包含外部链接。')
                archive.parent.mkdir(parents=True, exist_ok=True)
                archive.write_text(dump(dict(pending)), encoding='utf-8')
                # Referenced immutable images remain backed up in _sync_staging.
                db.execute('DELETE FROM sync_outbox WHERE entity_id=?', (entity_id,))
            if keep_local:
                if remote['deleted'] and current['local_id'] is not None:
                    # Explicit recovery is a new question, never resurrection of a tombstone.
                    db.execute('UPDATE sync_entities SET local_id=NULL,dirty=0,deleted=1,base_version=?,conflict=NULL WHERE id=?',
                               (remote['version'], entity_id))
                    db.execute('INSERT INTO sync_entities(id,local_id) VALUES(?,?)', (uuid4().hex, current['local_id']))
                else:
                    db.execute('UPDATE sync_entities SET base_version=?,revision=revision+1,dirty=1,conflict=NULL WHERE id=?',
                               (remote['version'], entity_id))
            else:
                db.execute('UPDATE sync_entities SET dirty=0,conflict=NULL,base_version=0 WHERE id=?', (entity_id,))
                db.execute("UPDATE sync_state SET value='1' WHERE key='applying'")
                self._apply(db, *prepared)
                db.execute("UPDATE sync_state SET value='0' WHERE key='applying'")

    def _archive_conflict(self, db, entity):
        question = dict(db.execute('SELECT * FROM questions WHERE id=?', (entity['local_id'],)).fetchone())
        folder = self.root / 'attachments' / '_conflicts' / (entity['id'] + '-' + uuid4().hex)
        if not folder.resolve().is_relative_to(self.root):
            raise ValueError('冲突备份目录包含外部链接。')
        folder.mkdir(parents=True)
        images = []
        for row in db.execute('SELECT * FROM attachments WHERE question_id=?', (entity['local_id'],)):
            source = self._file(row['relative_path'])
            name = uuid4().hex + source.suffix
            shutil.copyfile(source, folder / name)
            images.append({'file': name, 'original_name': row['original_name']})
        review = db.execute('SELECT * FROM review_state WHERE question_id=?', (entity['local_id'],)).fetchone()
        (folder / 'local-question.json').write_text(dump({'question': question, 'review': dict(review) if review else None, 'attachments': images,
                                                       'remote': json.loads(entity['conflict'])}), encoding='utf-8')

    def succeeded(self):
        with self.connection() as db:
            db.execute('INSERT INTO sync_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('last_success', datetime.now().astimezone().isoformat(timespec='seconds')))

    def import_guest(self, source_root):
        import tempfile
        import zipfile
        from app.services.backup import create_backup
        source_root = Path(source_root).resolve()
        if source_root == self.root or not (source_root / 'questions.db').is_file():
            raise ValueError('请选择存在的本地题库，不能将账号题库导入自身。')
        source_id = hashlib.sha256(str(source_root).encode('utf-8')).hexdigest()
        archive_path = self.root / 'imports' / ('local-before-import-' + uuid4().hex + '.zip')
        create_backup(archive_path, source_root)
        copied = []
        count = 0
        try:
            with tempfile.TemporaryDirectory(prefix='flandre-import-') as temporary, zipfile.ZipFile(archive_path) as archive:
                database = Path(temporary) / 'questions.db'
                database.write_bytes(archive.read('database.sqlite3'))
                store.initialize(database)  # Upgrade only the copy, preserving the source.
                with store._connection(database) as source, self.connection() as db:
                    db.execute('BEGIN IMMEDIATE')
                    for old in source.execute('SELECT * FROM questions ORDER BY id'):
                        if db.execute('SELECT 1 FROM sync_imports WHERE source=? AND source_id=?', (source_id, old['id'])).fetchone():
                            continue
                        question = validate_question(dict(old))
                        qid = db.execute(f"INSERT INTO questions({','.join(QUESTION_FIELDS)}) VALUES({','.join('?' for _ in QUESTION_FIELDS)})",
                                         database_values(question)).lastrowid
                        for image in source.execute('SELECT * FROM attachments WHERE question_id=?', (old['id'],)):
                            relative = image['relative_path']
                            if not isinstance(relative, str) or not re.fullmatch(r'attachments/[A-Za-z0-9_./-]+', relative) or '..' in Path(relative).parts:
                                raise ValueError('本地附件路径无效，导入已回滚。')
                            content = archive.read(relative)
                            destination = self.root / 'attachments' / (uuid4().hex + Path(relative).suffix.lower())
                            if not destination.resolve().is_relative_to(self.root):
                                raise ValueError('账号图片目录包含外部链接。')
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            copied.append(destination)
                            destination.write_bytes(content)
                            from app.services.attachments import validate_image
                            validate_image(destination)
                            db.execute('INSERT INTO attachments(question_id,relative_path,original_name,mime_type) VALUES(?,?,?,?)',
                                       (qid, 'attachments/' + destination.name, image['original_name'], image['mime_type']))
                        review = source.execute('SELECT * FROM review_state WHERE question_id=?', (old['id'],)).fetchone()
                        if review:
                            db.execute('INSERT INTO review_state VALUES(?,?,?,?,?)',
                                       (qid, review['mastery'], review['due_at'], review['last_reviewed_at'], review['review_count']))
                        entity_id = db.execute('SELECT id FROM sync_entities WHERE local_id=?', (qid,)).fetchone()[0]
                        db.execute('INSERT INTO sync_imports VALUES(?,?,?)', (source_id, old['id'], entity_id))
                        count += 1
            return {'imported': count, 'backup': str(archive_path)}
        except Exception:
            for file in copied:
                file.unlink(missing_ok=True)
            raise
