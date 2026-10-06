-- Read-only inspection: no tables, roles or privileges are changed.
SELECT
    current_user AS sql_role,
    EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc AS p
        JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'auth' AND p.proname = 'uid' AND p.pronargs = 0
    ) AS has_uid_helper,
    COALESCE((
        SELECT string_agg(rolname, ', ' ORDER BY rolname)
        FROM pg_catalog.pg_roles
        WHERE rolname LIKE 'auth%' OR rolname LIKE 'anon%'
    ), '(none)') AS login_roles,
    EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'flandre_connection_probe'
    ) AS probe_table_exists;
