"""Remove v13 additions when constructing an older database fixture."""
def remove_learning_schema(db):
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND (name LIKE 'learning_%' OR name='attempt_snapshot')").fetchall():
        db.execute(f'DROP TRIGGER "{name}"')
    for table in ('learning_outbox', 'learning_entities'):
        db.execute(f'DROP TABLE {table}')
    db.execute("DELETE FROM sync_state WHERE key='learning_cursor'")
    db.execute('ALTER TABLE vocabulary_words DROP COLUMN mastery')
