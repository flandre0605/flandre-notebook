"""Durable change markers share the transaction of every business mutation."""


def install(connection):
    statements = [
        "CREATE TABLE sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "INSERT INTO sync_state VALUES ('enabled','0'),('applying','0'),('cursor','0')",
        """CREATE TABLE sync_entities (
            id TEXT PRIMARY KEY, local_id INTEGER UNIQUE,
            revision INTEGER NOT NULL DEFAULT 1, base_version INTEGER NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0, dirty INTEGER NOT NULL DEFAULT 1,
            conflict TEXT)""",
        """CREATE TABLE sync_attachments (
            local_id INTEGER PRIMARY KEY REFERENCES attachments(id) ON DELETE CASCADE,
            id TEXT UNIQUE NOT NULL)""",
        """CREATE TABLE sync_outbox (
            operation_id TEXT PRIMARY KEY, entity_id TEXT UNIQUE NOT NULL REFERENCES sync_entities(id),
            revision INTEGER NOT NULL, base_version INTEGER NOT NULL,
            deleted INTEGER NOT NULL, payload TEXT NOT NULL)""",
        """CREATE TABLE sync_imports (
            source TEXT NOT NULL, source_id INTEGER NOT NULL, entity_id TEXT NOT NULL,
            PRIMARY KEY(source, source_id))""",
    ]
    enabled = "(SELECT value FROM sync_state WHERE key='enabled')='1' AND (SELECT value FROM sync_state WHERE key='applying')='0'"
    statements += [
        f"""CREATE TRIGGER sync_question_insert AFTER INSERT ON questions WHEN {enabled} BEGIN
            INSERT INTO sync_entities(id,local_id) VALUES(lower(hex(randomblob(16))),NEW.id);
        END""",
        f"""CREATE TRIGGER sync_question_update AFTER UPDATE ON questions WHEN {enabled} BEGIN
            UPDATE sync_entities SET revision=revision+1, dirty=1 WHERE local_id=NEW.id;
        END""",
        f"""CREATE TRIGGER sync_question_delete AFTER DELETE ON questions WHEN {enabled} BEGIN
            UPDATE sync_entities SET revision=revision+1, dirty=1, deleted=1, local_id=NULL WHERE local_id=OLD.id;
        END""",
    ]
    for table in ("review_state", "attachments"):
        for operation, row in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            body = ""
            if table == "attachments" and operation == "INSERT":
                body = "INSERT INTO sync_attachments(local_id,id) VALUES(NEW.id,lower(hex(randomblob(16))));"
            statements.append(f"""CREATE TRIGGER sync_{table}_{operation.lower()} AFTER {operation} ON {table}
                WHEN {enabled} BEGIN {body}
                UPDATE sync_entities SET revision=revision+1, dirty=1 WHERE local_id={row}.question_id;
                END""")
    for statement in statements:
        connection.execute(statement)
