"""Word and immutable attempt sync, using the question protocol's retry rules."""
from datetime import datetime
import json
import re
from uuid import uuid4

from app.services.cloud_sync_store import dump, identity

WORD_FIELDS = ('word', 'meaning', 'phonetic', 'example', 'book', 'mastery', 'review_count', 'streak', 'due_at', 'last_reviewed_at')
ATTEMPT_FIELDS = ('question_cloud_id', 'question_stem', 'question_subject', 'answered_at', 'user_answer', 'result', 'mastery', 'duration_seconds', 'mistake_reason')


def validate_payload(kind, value):
    if not isinstance(value, dict) or len(dump(value).encode()) > 131072:
        raise ValueError('学习记录格式或长度无效。')
    fields = WORD_FIELDS if kind == 'word' else ATTEMPT_FIELDS if kind == 'attempt' else ()
    if not fields or set(value) != set(fields):
        raise ValueError('学习记录字段无效。')
    limits = dict(word=300, meaning=4000, phonetic=300, example=4000, book=100,
                  question_stem=20000, question_subject=20000, user_answer=20000, mistake_reason=20000)
    for field in fields:
        item = value[field]
        if field in ('review_count', 'streak', 'duration_seconds'):
            if type(item) is not int or not 0 <= item <= 2147483647:
                raise ValueError('学习次数或用时无效。')
        elif field in ('due_at', 'last_reviewed_at', 'answered_at'):
            if item is None and kind == 'word':
                continue
            if not isinstance(item, str) or len(item) != 19:
                raise ValueError('学习记录日期无效。')
            datetime.strptime(item, '%Y-%m-%d %H:%M:%S')
        elif field == 'question_cloud_id':
            if not isinstance(item, str) or not re.fullmatch(r'[a-f0-9]{32}|', item):
                raise ValueError('题目标识无效。')
        elif field == 'mastery':
            if item not in ('unknown', 'unsure', 'mastered'):
                raise ValueError('掌握程度无效。')
        elif field == 'result':
            if item not in ('correct', 'incorrect', 'skipped'):
                raise ValueError('作答结果无效。')
        elif not isinstance(item, str) or len(item) > limits[field] or '\0' in item:
            raise ValueError('学习记录文本无效。')
    if kind == 'word' and not value['word'].strip():
        raise ValueError('单词不能为空。')
    return value


class LearningStore:
    def __init__(self, local):
        self.local = local

    def status(self):
        with self.local.connection() as db:
            row = db.execute('SELECT COALESCE(sum(dirty),0),COALESCE(sum(conflict IS NOT NULL),0) FROM learning_entities').fetchone()
            cursor = db.execute("SELECT value FROM sync_state WHERE key='learning_cursor'").fetchone()[0]
        return dict(pending=row[0], conflicts=row[1], cursor=int(cursor))

    def content(self, db, entity):
        if entity['deleted']:
            return {}
        table, fields = ('vocabulary_words', WORD_FIELDS) if entity['kind'] == 'word' else ('practice_attempts', ATTEMPT_FIELDS)
        row = db.execute(f"SELECT {','.join(fields)} FROM {table} WHERE id=?", (entity['local_id'],)).fetchone()
        if row is None:
            raise ValueError('待传学习记录不存在，请保留备份后检查。')
        value = dict(row)
        if entity['kind'] == 'attempt' and not value['question_cloud_id']:
            link = db.execute('SELECT s.id FROM sync_entities s JOIN practice_attempts a ON a.question_id=s.local_id WHERE a.id=?',
                              (entity['local_id'],)).fetchone()
            if link:
                value['question_cloud_id'] = link[0]
        return validate_payload(entity['kind'], value)

    def prepare(self):
        with self.local.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT o.* FROM learning_outbox o JOIN learning_entities e ON e.id=o.entity_id '
                             'WHERE e.conflict IS NULL ORDER BY o.rowid LIMIT 1').fetchone()
            if row:
                return dict(row)
            entity = db.execute('SELECT * FROM learning_entities WHERE dirty=1 AND conflict IS NULL ORDER BY rowid LIMIT 1').fetchone()
            if entity is None:
                return None
            value = self.content(db, entity)
            op = uuid4().hex
            db.execute('INSERT INTO learning_outbox VALUES(?,?,?,?,?,?,?)',
                       (op, entity['id'], entity['revision'], entity['base_version'], entity['kind'], entity['deleted'], dump(value)))
            return dict(db.execute('SELECT * FROM learning_outbox WHERE operation_id=?', (op,)).fetchone())

    def record(self, row):
        if not isinstance(row, dict) or row.get('user_id') != self.local.user_id:
            raise ValueError('学习记录不属于当前账号。')
        row = dict(row, id=identity(row.get('id')))
        if any(type(row.get(key)) is not int or row[key] < 1 for key in ('version', 'seq')) or type(row.get('deleted')) is not bool:
            raise ValueError('学习记录版本无效。')
        if row.get('kind') not in ('word', 'attempt') or row['kind'] == 'attempt' and row['deleted']:
            raise ValueError('学习记录类型无效。')
        if row['deleted']:
            if row.get('payload') != {}:
                raise ValueError('删除标记内容无效。')
        else:
            validate_payload(row['kind'], row.get('payload'))
        return row

    def acknowledge(self, pending, remote):
        with self.local.connection() as db:
            db.execute('UPDATE learning_entities SET base_version=?,payload=?,dirty=CASE WHEN revision=? THEN 0 ELSE 1 END WHERE id=?',
                       (remote['version'], dump(remote['payload']), pending['revision'], pending['entity_id']))
            db.execute('DELETE FROM learning_outbox WHERE operation_id=?', (pending['operation_id'],))

    def conflict(self, entity_id, remote):
        if remote is None:
            raise ValueError('云端学习冲突缺少原始记录，未清除待传内容。')
        with self.local.connection() as db:
            db.execute('UPDATE learning_entities SET conflict=? WHERE id=?', (dump(remote), entity_id))

    def _apply(self, db, remote, force=False):
        entity = db.execute('SELECT * FROM learning_entities WHERE id=?', (remote['id'],)).fetchone()
        if entity and entity['kind'] != remote['kind']:
            raise ValueError('学习记录类型发生变化。')
        if not force and entity and entity['base_version'] >= remote['version']:
            return
        if not force and entity and (entity['dirty'] or entity['conflict']):
            db.execute('UPDATE learning_entities SET conflict=? WHERE id=?', (dump(remote), remote['id']))
            return
        local_id = entity['local_id'] if entity else None
        value = remote['payload']
        if remote['kind'] == 'word':
            if remote['deleted']:
                if local_id is not None:
                    db.execute('DELETE FROM vocabulary_words WHERE id=?', (local_id,))
                local_id = None
            else:
                duplicate = db.execute('SELECT id FROM vocabulary_words WHERE word=? COLLATE NOCASE', (value['word'],)).fetchone()
                if duplicate and duplicate[0] != local_id and not force:
                    db.execute('INSERT INTO learning_entities(id,kind,local_id,conflict) VALUES(?,?,?,?) '
                               'ON CONFLICT(id) DO UPDATE SET conflict=excluded.conflict',
                               (remote['id'], 'word', duplicate[0], dump(remote)))
                    return
                if duplicate and duplicate[0] != local_id:
                    if local_id is not None:
                        raise ValueError('另一个词条使用相同单词，请先修改词条再处理冲突。')
                    local_id = duplicate[0]
                if local_id is None:
                    local_id = db.execute(f"INSERT INTO vocabulary_words({','.join(WORD_FIELDS)}) VALUES({','.join('?' for _ in WORD_FIELDS)})",
                                          tuple(value[f] for f in WORD_FIELDS)).lastrowid
                else:
                    db.execute(f"UPDATE vocabulary_words SET {','.join(f'{f}=?' for f in WORD_FIELDS)} WHERE id=?",
                               (*[value[f] for f in WORD_FIELDS], local_id))
        elif local_id is None:
            question = db.execute('SELECT local_id FROM sync_entities WHERE id=?', (value['question_cloud_id'],)).fetchone()
            local_id = db.execute(f"INSERT INTO practice_attempts(question_id,{','.join(ATTEMPT_FIELDS)}) VALUES({','.join('?' for _ in range(1+len(ATTEMPT_FIELDS)))})",
                                  (question[0] if question else None, *[value[f] for f in ATTEMPT_FIELDS])).lastrowid
        elif force:
            question = db.execute('SELECT local_id FROM sync_entities WHERE id=?', (value['question_cloud_id'],)).fetchone()
            db.execute(f"UPDATE practice_attempts SET question_id=?,{','.join(f'{f}=?' for f in ATTEMPT_FIELDS)} WHERE id=?",
                       (question[0] if question else None, *[value[f] for f in ATTEMPT_FIELDS],local_id))
        elif entity and json.loads(entity['payload']) != value:
            raise ValueError('已完成的作答历史不能被云端改写。')
        db.execute('INSERT INTO learning_entities(id,kind,local_id,base_version,dirty,deleted,payload) VALUES(?,?,?,?,0,?,?) '
                   'ON CONFLICT(id) DO UPDATE SET local_id=excluded.local_id,base_version=excluded.base_version,dirty=0,deleted=excluded.deleted,payload=excluded.payload,conflict=NULL',
                   (remote['id'], remote['kind'], local_id, remote['version'], int(remote['deleted']), dump(value)))

    def apply(self, rows, cursor):
        with self.local.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE sync_state SET value='1' WHERE key='applying'")
            for row in rows:
                self._apply(db, row)
            db.execute("UPDATE sync_state SET value=? WHERE key='learning_cursor'", (str(cursor),))
            db.execute("UPDATE sync_state SET value='0' WHERE key='applying'")

    def conflicts(self):
        with self.local.connection() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM learning_entities WHERE conflict IS NOT NULL ORDER BY rowid')]
            for row in rows:
                row['local_payload'] = self.content(db, row)
                row['stem'] = '单词：' + row['local_payload'].get('word', '已删除') if row['kind'] == 'word' else '作答历史'
        return rows

    def resolve(self, entity_id, keep):
        with self.local.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            entity = db.execute('SELECT * FROM learning_entities WHERE id=? AND conflict IS NOT NULL', (entity_id,)).fetchone()
            if entity is None:
                raise ValueError('冲突已变化，请刷新。')
            remote = self.record(json.loads(entity['conflict']))
            local = self.content(db, entity)
            folder = self.local.root / 'attachments' / '_conflicts'
            if not folder.resolve().is_relative_to(self.local.root):
                raise ValueError('冲突副本目录包含外部链接。')
            folder.mkdir(parents=True, exist_ok=True)
            (folder / ('learning-' + uuid4().hex + '.json')).write_text(dump(dict(local=local, remote=remote)), encoding='utf-8')
            db.execute('DELETE FROM learning_outbox WHERE entity_id=?', (entity_id,))
            # Same spelling from two devices becomes one chosen identity; preserve the other cloud identity as a tombstone.
            db.execute("UPDATE learning_entities SET local_id=NULL,deleted=1,dirty=1,revision=revision+1,conflict=NULL WHERE kind='word' AND local_id=? AND id<>?",
                       (entity['local_id'], entity_id))
            if keep:
                if entity['kind'] != 'word':
                    raise ValueError('历史不可改写，请采用原始云端记录。')
                db.execute('UPDATE learning_entities SET base_version=?,revision=revision+1,dirty=1,conflict=NULL WHERE id=?', (remote['version'], entity_id))
            else:
                db.execute("UPDATE sync_state SET value='1' WHERE key='applying'")
                self._apply(db, remote, True)
                db.execute("UPDATE sync_state SET value='0' WHERE key='applying'")


def synchronize_learning(local, client, pull=True):
    learning = LearningStore(local)
    uploaded = downloaded = 0
    for _ in range(200):
        pending = learning.prepare()
        if pending is None:
            break
        payload = json.loads(pending['payload'])
        result = client.rpc('flandre_learning_push', dict(p_id=pending['entity_id'], p_operation_id=pending['operation_id'],
                            p_kind=pending['kind'], p_base_version=pending['base_version'], p_deleted=bool(pending['deleted']), p_payload=payload))
        remote = learning.record(result.get('record')) if result.get('record') is not None else None
        if remote is not None and (remote['id'] != pending['entity_id'] or remote['kind'] != pending['kind']):
            raise ValueError('学习同步确认对应其他记录。')
        if result.get('status') == 'conflict':
            learning.conflict(pending['entity_id'], remote)
            continue
        if result.get('status') != 'applied' or remote is None or remote['version'] != pending['base_version'] + 1 or remote['deleted'] != bool(pending['deleted']) or remote['payload'] != payload:
            raise ValueError('云端未确认本轮学习记录，保留原编号重试。')
        learning.acknowledge(pending, remote)
        uploaded += 1
    if not pull:
        return dict(uploaded=uploaded, downloaded=0)
    for _ in range(200):
        cursor = learning.status()['cursor']
        page = client.rpc('flandre_learning_pull', dict(p_after=cursor, p_limit=5))
        rows = page.get('records')
        if not isinstance(rows, list) or len(rows) > 5 or type(page.get('cursor')) is not int:
            raise ValueError('学习记录分页无效。')
        prepared = []
        for row in rows:
            row = learning.record(row)
            if row['seq'] <= cursor:
                raise ValueError('学习变更顺序无效。')
            cursor = row['seq']
            prepared.append(row)
        if page['cursor'] != cursor:
            raise ValueError('学习变更游标无效。')
        learning.apply(prepared, cursor)
        downloaded += len(prepared)
        if len(rows) < 5:
            return dict(uploaded=uploaded, downloaded=downloaded)
    raise ValueError('本轮学习记录超过 1000 项，请继续同步。')
