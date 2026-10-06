-- CloudBase PostgreSQL connection check only; not the production sync schema.
-- Execute once in the console SQL editor. Existing tables are not overwritten.
-- Run 000_check_environment.sql first; console preflight and PG docs may differ.
BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc AS p
        JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'auth' AND p.proname = 'uid' AND p.pronargs = 0
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'authenticated'
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'anon'
    ) THEN
        RAISE EXCEPTION 'Environment identity helpers/roles differ from the documented PG mode. Run 000_check_environment.sql; no probe table was created.';
    END IF;
END;
$$;

CREATE TABLE public.flandre_connection_probe (
    id uuid PRIMARY KEY,
    user_id varchar(64) NOT NULL DEFAULT auth.uid(),
    note varchar(2000) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.flandre_connection_probe ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.flandre_connection_probe FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT, INSERT, DELETE ON public.flandre_connection_probe TO authenticated;
GRANT UPDATE (note) ON public.flandre_connection_probe TO authenticated;

CREATE POLICY flandre_probe_own_rows ON public.flandre_connection_probe
    FOR ALL TO authenticated
    USING (user_id = (SELECT auth.uid()))
    WITH CHECK (user_id = (SELECT auth.uid()));

COMMIT;
