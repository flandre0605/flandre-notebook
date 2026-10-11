"""Stable learning identities and transactional dirty markers."""
from uuid import uuid4


def install(db):
    db.execute("ALTER TABLE vocabulary_words ADD COLUMN mastery TEXT NOT NULL DEFAULT 'unknown'")
    db.execute("UPDATE vocabulary_words SET mastery=CASE WHEN streak>0 THEN 'mastered' ELSE 'unknown' END")
    # A deleted question must not erase the already completed learning history.
    db.execute("ALTER TABLE practice_attempts RENAME TO old_attempts")
    db.execute("""CREATE TABLE practice_attempts (
        id INTEGER PRIMARY KEY, question_id INTEGER REFERENCES questions(id) ON DELETE SET NULL,
        answered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        result TEXT NOT NULL CHECK(result IN ('correct','incorrect','skipped')),
        duration_seconds INTEGER NOT NULL DEFAULT 0, mistake_reason TEXT NOT NULL DEFAULT '',
        mastery TEXT NOT NULL CHECK(mastery IN ('mastered','unsure','unknown')), user_answer TEXT NOT NULL DEFAULT '',
        question_stem TEXT NOT NULL DEFAULT '', question_subject TEXT NOT NULL DEFAULT '',
        question_cloud_id TEXT NOT NULL DEFAULT '')""")
    db.execute("""INSERT INTO practice_attempts SELECT a.id,a.question_id,a.answered_at,a.result,
        a.duration_seconds,a.mistake_reason,a.mastery,a.user_answer,q.stem,q.subject,COALESCE(s.id,'')
        FROM old_attempts a JOIN questions q ON q.id=a.question_id
        LEFT JOIN sync_entities s ON s.local_id=q.id""")
    db.execute("DROP TABLE old_attempts")
    db.execute("CREATE INDEX idx_attempts_question_id ON practice_attempts(question_id)")
    db.execute("""CREATE TABLE learning_entities (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, local_id INTEGER,
        revision INTEGER NOT NULL DEFAULT 1, base_version INTEGER NOT NULL DEFAULT 0,
        dirty INTEGER NOT NULL DEFAULT 1, deleted INTEGER NOT NULL DEFAULT 0,
        conflict TEXT, payload TEXT NOT NULL DEFAULT '{}')""")
    db.execute("""CREATE TABLE learning_outbox (
        operation_id TEXT PRIMARY KEY, entity_id TEXT UNIQUE NOT NULL,
        revision INTEGER NOT NULL, base_version INTEGER NOT NULL,
        kind TEXT NOT NULL, deleted INTEGER NOT NULL, payload TEXT NOT NULL)""")
    db.execute("INSERT INTO sync_state VALUES('learning_cursor','0')")
    for kind, table in (('word', 'vocabulary_words'), ('attempt', 'practice_attempts')):
        for (local_id,) in db.execute(f'SELECT id FROM {table}').fetchall():
            db.execute('INSERT INTO learning_entities(id,kind,local_id) VALUES(?,?,?)', (uuid4().hex, kind, local_id))
        db.execute(f"""CREATE TRIGGER learning_{kind}_insert AFTER INSERT ON {table}
            WHEN (SELECT value FROM sync_state WHERE key='applying')='0' BEGIN
            INSERT INTO learning_entities(id,kind,local_id) VALUES(lower(hex(randomblob(16))),'{kind}',NEW.id);
            END""")
    db.execute("""CREATE TRIGGER attempt_snapshot AFTER INSERT ON practice_attempts
        WHEN (SELECT value FROM sync_state WHERE key='applying')='0'
        AND NEW.question_stem='' AND NEW.question_subject='' AND NEW.question_cloud_id='' BEGIN
        UPDATE practice_attempts SET question_stem=COALESCE((SELECT stem FROM questions WHERE id=NEW.question_id),NEW.question_stem),
        question_subject=COALESCE((SELECT subject FROM questions WHERE id=NEW.question_id),NEW.question_subject),
        question_cloud_id=COALESCE((SELECT id FROM sync_entities WHERE local_id=NEW.question_id),NEW.question_cloud_id)
        WHERE id=NEW.id; END""")
    for operation, row in (('UPDATE', 'NEW'), ('DELETE', 'OLD')):
        db.execute(f"""CREATE TRIGGER learning_word_{operation.lower()} AFTER {operation} ON vocabulary_words
            WHEN (SELECT value FROM sync_state WHERE key='applying')='0' BEGIN
            UPDATE learning_entities SET revision=revision+1,dirty=1,
            deleted={1 if operation == 'DELETE' else 0},local_id={'NULL' if operation == 'DELETE' else 'local_id'}
            WHERE kind='word' AND local_id={row}.id; END""")
