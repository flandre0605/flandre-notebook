-- Mobile photo inbox v1. Execute once AFTER 004_desktop_sync.sql.
-- Adds resources; leaves existing questions and both probe resources intact.
BEGIN;
CREATE TABLE public.flandre_mobile_inbox (
  id uuid PRIMARY KEY,
  user_id varchar(64) NOT NULL,
  seq bigint NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processed','dismissed')),
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id,seq)
);
ALTER TABLE public.flandre_mobile_inbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.flandre_mobile_inbox FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.flandre_mobile_inbox TO authenticated;
CREATE POLICY flandre_inbox_own ON public.flandre_mobile_inbox FOR SELECT TO authenticated
USING(user_id = (SELECT auth.uid()));
INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
VALUES('flandre-inbox-images','flandre-inbox-images',false,20971520,
       ARRAY['image/png','image/jpeg','image/webp']);
CREATE POLICY flandre_inbox_bucket_update ON storage.buckets AS RESTRICTIVE FOR UPDATE TO PUBLIC
USING(id <> 'flandre-inbox-images') WITH CHECK(id <> 'flandre-inbox-images');
CREATE POLICY flandre_inbox_bucket_delete ON storage.buckets AS RESTRICTIVE FOR DELETE TO PUBLIC
USING(id <> 'flandre-inbox-images');
CREATE POLICY flandre_inbox_images_guard ON storage.objects AS RESTRICTIVE FOR ALL TO PUBLIC
USING(bucket_id <> 'flandre-inbox-images' OR
  (auth.role()='authenticated' AND owner_id=(SELECT auth.uid()) AND split_part(name,'/',1)=(SELECT auth.uid())))
WITH CHECK(bucket_id <> 'flandre-inbox-images' OR
  (auth.role()='authenticated' AND owner_id=(SELECT auth.uid()) AND split_part(name,'/',1)=(SELECT auth.uid())));
CREATE POLICY flandre_inbox_images_read ON storage.objects FOR SELECT TO authenticated
USING(bucket_id='flandre-inbox-images' AND owner_id=(SELECT auth.uid()) AND split_part(name,'/',1)=(SELECT auth.uid()));
CREATE POLICY flandre_inbox_images_insert ON storage.objects FOR INSERT TO authenticated
WITH CHECK(bucket_id='flandre-inbox-images' AND owner_id=(SELECT auth.uid()) AND split_part(name,'/',1)=(SELECT auth.uid()));
CREATE POLICY flandre_inbox_images_immutable ON storage.objects AS RESTRICTIVE FOR UPDATE TO PUBLIC
USING(bucket_id <> 'flandre-inbox-images') WITH CHECK(bucket_id <> 'flandre-inbox-images');
CREATE POLICY flandre_inbox_images_retain ON storage.objects AS RESTRICTIVE FOR DELETE TO PUBLIC
USING(bucket_id <> 'flandre-inbox-images');

CREATE FUNCTION public.flandre_inbox_submit(p_id uuid,p_payload jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
  caller text := auth.uid();
  existing public.flandre_mobile_inbox%ROWTYPE;
  image jsonb;
  change_number bigint;
BEGIN
  IF auth.role() IS DISTINCT FROM 'authenticated' OR caller IS NULL OR caller='' THEN
    RAISE EXCEPTION 'FLANDRE_AUTH_REQUIRED' USING ERRCODE='42501';
  END IF;
  IF p_id IS NULL OR p_payload IS NULL OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
     OR octet_length(p_payload::text)>16384
     OR jsonb_typeof(p_payload->'source_name') IS DISTINCT FROM 'string'
     OR length(p_payload->>'source_name') NOT BETWEEN 1 AND 200
     OR jsonb_typeof(p_payload->'note') IS DISTINCT FROM 'string'
     OR length(p_payload->>'note')>1000
     OR jsonb_typeof(p_payload->'images') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'FLANDRE_INVALID_INBOX' USING ERRCODE='22023';
  END IF;
  IF jsonb_array_length(p_payload->'images') NOT BETWEEN 1 AND 2 THEN
    RAISE EXCEPTION 'FLANDRE_INVALID_IMAGES' USING ERRCODE='22023';
  END IF;
  IF (SELECT count(*) FROM jsonb_array_elements(p_payload->'images') a WHERE a->>'role'='original')<>1
     OR (SELECT count(DISTINCT a->>'role') FROM jsonb_array_elements(p_payload->'images') a)
        <>jsonb_array_length(p_payload->'images')
     OR (SELECT count(DISTINCT a->>'id') FROM jsonb_array_elements(p_payload->'images') a)
        <>jsonb_array_length(p_payload->'images') THEN
    RAISE EXCEPTION 'FLANDRE_INVALID_IMAGES' USING ERRCODE='22023';
  END IF;
  FOR image IN SELECT value FROM jsonb_array_elements(p_payload->'images') LOOP
    IF jsonb_typeof(image) IS DISTINCT FROM 'object'
       OR jsonb_typeof(image->'id') IS DISTINCT FROM 'string'
       OR (image->>'id') !~ '^[0-9a-f]{32}$'
       OR jsonb_typeof(image->'sha256') IS DISTINCT FROM 'string'
       OR (image->>'sha256') !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(image->'size') IS DISTINCT FROM 'number'
       OR (image->>'size') !~ '^[0-9]{1,8}$'
       OR (image->>'size')::bigint NOT BETWEEN 1 AND 20971520
       OR jsonb_typeof(image->'role') IS DISTINCT FROM 'string'
       OR (image->>'role') NOT IN ('original','crop')
       OR jsonb_typeof(image->'mime_type') IS DISTINCT FROM 'string'
       OR (image->>'mime_type') NOT IN ('image/png','image/jpeg','image/webp')
       OR jsonb_typeof(image->'key') IS DISTINCT FROM 'string' THEN
      RAISE EXCEPTION 'FLANDRE_INVALID_IMAGE' USING ERRCODE='22023';
    END IF;
    IF (image->>'key') NOT IN (
       caller||'/'||replace(p_id::text,'-','')||'/'||(image->>'id')||'/'||(image->>'sha256')||
       CASE image->>'mime_type' WHEN 'image/png' THEN '.png' WHEN 'image/webp' THEN '.webp' ELSE '.jpg' END,
       caller||'/'||replace(p_id::text,'-','')||'/'||(image->>'id')||'/'||(image->>'sha256')||'.jpeg')
       OR ((image->>'key') LIKE '%.jpeg' AND (image->>'mime_type')<>'image/jpeg') THEN
      RAISE EXCEPTION 'FLANDRE_INVALID_PATH' USING ERRCODE='22023';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM storage.objects WHERE bucket_id='flandre-inbox-images'
      AND name=image->>'key' AND owner_id=caller) THEN
      RAISE EXCEPTION 'FLANDRE_IMAGE_NOT_UPLOADED' USING ERRCODE='22023';
    END IF;
  END LOOP;
  INSERT INTO public.flandre_sync_accounts(user_id) VALUES(caller) ON CONFLICT DO NOTHING;
  PERFORM 1 FROM public.flandre_sync_accounts WHERE user_id=caller FOR UPDATE;
  SELECT * INTO existing FROM public.flandre_mobile_inbox WHERE id=p_id;
  IF FOUND THEN
    IF existing.user_id IS DISTINCT FROM caller THEN
      RAISE EXCEPTION 'FLANDRE_FORBIDDEN' USING ERRCODE='42501';
    END IF;
    IF existing.payload IS DISTINCT FROM p_payload THEN
      RAISE EXCEPTION 'FLANDRE_OPERATION_MISMATCH' USING ERRCODE='22023';
    END IF;
    RETURN jsonb_build_object('record',to_jsonb(existing));
  END IF;
  UPDATE public.flandre_sync_accounts SET next_seq=next_seq+1 WHERE user_id=caller RETURNING next_seq INTO change_number;
  INSERT INTO public.flandre_mobile_inbox(id,user_id,seq,payload) VALUES(p_id,caller,change_number,p_payload)
    ON CONFLICT(id) DO NOTHING RETURNING * INTO existing;
  IF NOT FOUND THEN
    -- Another account may have raced for the global UUID; never disclose it.
    RAISE EXCEPTION 'FLANDRE_FORBIDDEN' USING ERRCODE='42501';
  END IF;
  RETURN jsonb_build_object('record',to_jsonb(existing));
END $$;

CREATE FUNCTION public.flandre_inbox_pull(p_after bigint DEFAULT 0,p_limit integer DEFAULT 50)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE caller text := auth.uid(); rows jsonb; cursor_value bigint;
BEGIN
  IF auth.role() IS DISTINCT FROM 'authenticated' OR caller IS NULL OR caller='' THEN
    RAISE EXCEPTION 'FLANDRE_AUTH_REQUIRED' USING ERRCODE='42501';
  END IF;
  IF p_after IS NULL OR p_after<0 OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 THEN
    RAISE EXCEPTION 'FLANDRE_INVALID_PAGE' USING ERRCODE='22023';
  END IF;
  SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.seq),'[]'::jsonb),coalesce(max(q.seq),p_after)
    INTO rows,cursor_value FROM (SELECT * FROM public.flandre_mobile_inbox
      WHERE user_id=caller AND seq>p_after ORDER BY seq LIMIT p_limit) q;
  RETURN jsonb_build_object('records',rows,'cursor',cursor_value);
END $$;

CREATE FUNCTION public.flandre_inbox_finish(p_id uuid,p_status text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE caller text := auth.uid(); existing public.flandre_mobile_inbox%ROWTYPE; change_number bigint;
BEGIN
  IF auth.role() IS DISTINCT FROM 'authenticated' OR caller IS NULL OR caller='' THEN
    RAISE EXCEPTION 'FLANDRE_AUTH_REQUIRED' USING ERRCODE='42501';
  END IF;
  IF p_id IS NULL OR p_status IS NULL OR p_status NOT IN ('processed','dismissed') THEN
    RAISE EXCEPTION 'FLANDRE_INVALID_STATUS' USING ERRCODE='22023';
  END IF;
  PERFORM 1 FROM public.flandre_sync_accounts WHERE user_id=caller FOR UPDATE;
  SELECT * INTO existing FROM public.flandre_mobile_inbox WHERE id=p_id AND user_id=caller;
  IF NOT FOUND THEN RAISE EXCEPTION 'FLANDRE_FORBIDDEN' USING ERRCODE='42501'; END IF;
  IF existing.status='pending' THEN
    UPDATE public.flandre_sync_accounts SET next_seq=next_seq+1 WHERE user_id=caller RETURNING next_seq INTO change_number;
    UPDATE public.flandre_mobile_inbox SET status=p_status,seq=change_number,updated_at=now()
      WHERE id=p_id AND user_id=caller RETURNING * INTO existing;
  END IF;
  RETURN jsonb_build_object('record',to_jsonb(existing));
END $$;
REVOKE ALL ON FUNCTION public.flandre_inbox_submit(uuid,jsonb),public.flandre_inbox_pull(bigint,integer),
 public.flandre_inbox_finish(uuid,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.flandre_inbox_submit(uuid,jsonb),public.flandre_inbox_pull(bigint,integer),
 public.flandre_inbox_finish(uuid,text) TO authenticated;
COMMIT;
