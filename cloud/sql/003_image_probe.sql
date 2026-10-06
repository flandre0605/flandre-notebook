-- Dedicated PG storage test bucket only. Execute once, after the read-only check.
-- Do not drop or overwrite an existing bucket. No changes to business data.
BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'auth' AND p.proname IN ('uid', 'role') AND p.pronargs = 0
    GROUP BY n.nspname HAVING count(DISTINCT p.proname) = 2
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'authenticated'
  ) OR (
    SELECT count(*) FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'storage' AND c.relname IN ('buckets', 'objects')
      AND c.relrowsecurity
  ) <> 2 THEN
    RAISE EXCEPTION 'PG storage/auth prerequisites missing; no bucket created';
  END IF;
END $$;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('flandre-image-probe', 'flandre-image-probe', false,
        1048576, ARRAY['image/png']);

-- Existing permissive policies combine with OR. This additional restrictive
-- policy guards only this bucket, including against accidental broad policies.
CREATE POLICY flandre_image_probe_guard ON storage.objects
AS RESTRICTIVE FOR ALL TO PUBLIC
USING (bucket_id <> 'flandre-image-probe' OR (
  auth.role() = 'authenticated' AND owner_id = (SELECT auth.uid())
  AND split_part(name, '/', 1) = (SELECT auth.uid())
))
WITH CHECK (bucket_id <> 'flandre-image-probe' OR (
  auth.role() = 'authenticated' AND owner_id = (SELECT auth.uid())
  AND split_part(name, '/', 1) = (SELECT auth.uid())
));

CREATE POLICY flandre_image_probe_own ON storage.objects
FOR ALL TO authenticated
USING (bucket_id = 'flandre-image-probe'
  AND owner_id = (SELECT auth.uid())
  AND split_part(name, '/', 1) = (SELECT auth.uid()))
WITH CHECK (bucket_id = 'flandre-image-probe'
  AND owner_id = (SELECT auth.uid())
  AND split_part(name, '/', 1) = (SELECT auth.uid()));
COMMIT;
