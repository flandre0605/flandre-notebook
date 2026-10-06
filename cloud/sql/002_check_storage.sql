-- Read-only: inspect PG storage before deploying the dedicated test bucket.
SELECT n.nspname AS schema_name, c.relname AS table_name,
       c.relrowsecurity AS rls_enabled
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'storage' AND c.relname IN ('buckets', 'objects');

SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'storage'
  AND table_name IN ('buckets', 'objects')
ORDER BY table_name, ordinal_position;

SELECT tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_catalog.pg_policies
WHERE schemaname = 'storage' AND tablename IN ('buckets', 'objects');

SELECT id, name, public, file_size_limit, allowed_mime_types
FROM storage.buckets WHERE id = 'flandre-image-probe';
