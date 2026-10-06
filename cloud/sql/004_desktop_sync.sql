-- Desktop sync v1. Execute once as the environment administrator.
-- Preserves both probe resources. Does not import or upload the local library.
BEGIN;
CREATE TABLE public.flandre_sync_accounts (
  user_id varchar(64) PRIMARY KEY,
  next_seq bigint NOT NULL DEFAULT 0
);
CREATE TABLE public.flandre_questions (
  id uuid PRIMARY KEY,
  user_id varchar(64) NOT NULL,
  version bigint NOT NULL CHECK (version > 0),
  seq bigint NOT NULL,
  deleted boolean NOT NULL DEFAULT false,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id, seq)
);
CREATE INDEX flandre_questions_changes ON public.flandre_questions(user_id, seq);
CREATE TABLE public.flandre_sync_operations (
  user_id varchar(64) NOT NULL,
  operation_id uuid NOT NULL,
  request jsonb NOT NULL,
  result jsonb NOT NULL,
  PRIMARY KEY(user_id, operation_id)
);
ALTER TABLE public.flandre_sync_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flandre_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flandre_sync_operations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.flandre_sync_accounts, public.flandre_questions,
  public.flandre_sync_operations FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.flandre_questions TO authenticated;
CREATE POLICY flandre_questions_own ON public.flandre_questions FOR SELECT TO authenticated
  USING(user_id = (SELECT auth.uid()));

INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
VALUES('flandre-question-images','flandre-question-images',false,20971520,
       ARRAY['image/png','image/jpeg','image/webp']);
CREATE POLICY flandre_question_bucket_update ON storage.buckets AS RESTRICTIVE FOR UPDATE TO PUBLIC
USING(id <> 'flandre-question-images') WITH CHECK(id <> 'flandre-question-images');
CREATE POLICY flandre_question_bucket_delete ON storage.buckets AS RESTRICTIVE FOR DELETE TO PUBLIC
USING(id <> 'flandre-question-images');
CREATE POLICY flandre_question_images_guard ON storage.objects
AS RESTRICTIVE FOR ALL TO PUBLIC
USING(bucket_id <> 'flandre-question-images' OR
  (auth.role() = 'authenticated' AND owner_id = (SELECT auth.uid())
   AND split_part(name,'/',1) = (SELECT auth.uid())))
WITH CHECK(bucket_id <> 'flandre-question-images' OR
  (auth.role() = 'authenticated' AND owner_id = (SELECT auth.uid())
   AND split_part(name,'/',1) = (SELECT auth.uid())));
CREATE POLICY flandre_question_images_read ON storage.objects FOR SELECT TO authenticated
USING(bucket_id = 'flandre-question-images' AND owner_id = (SELECT auth.uid())
  AND split_part(name,'/',1) = (SELECT auth.uid()));
CREATE POLICY flandre_question_images_insert ON storage.objects FOR INSERT TO authenticated
WITH CHECK(bucket_id = 'flandre-question-images' AND owner_id = (SELECT auth.uid())
  AND split_part(name,'/',1) = (SELECT auth.uid()));
-- Immutable object paths: an uploaded snapshot cannot be changed or deleted by
-- another device while metadata references it. No client UPDATE/DELETE policy.
CREATE POLICY flandre_question_images_immutable ON storage.objects
AS RESTRICTIVE FOR UPDATE TO PUBLIC
USING(bucket_id <> 'flandre-question-images')
WITH CHECK(bucket_id <> 'flandre-question-images');
CREATE POLICY flandre_question_images_retain ON storage.objects
AS RESTRICTIVE FOR DELETE TO PUBLIC
USING(bucket_id <> 'flandre-question-images');

CREATE FUNCTION public.flandre_sync_push(
  p_id uuid, p_operation_id uuid, p_base_version bigint,
  p_deleted boolean, p_payload jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
AS $$
DECLARE
  caller text := auth.uid();
  existing public.flandre_questions%ROWTYPE;
  previous public.flandre_sync_operations%ROWTYPE;
  request_body jsonb;
  response_body jsonb;
  next_change bigint;
  attachment jsonb;
  field text;
  option_item record;
  option_count integer;
BEGIN
  -- Required even if the gateway ignores GRANT EXECUTE. Fail closed on NULL.
  IF auth.role() IS DISTINCT FROM 'authenticated' OR caller IS NULL OR caller = '' THEN
    RAISE EXCEPTION 'FLANDRE_AUTH_REQUIRED' USING ERRCODE = '42501';
  END IF;
  IF p_id IS NULL OR p_operation_id IS NULL OR p_base_version IS NULL
     OR p_base_version < 0 OR p_deleted IS NULL OR p_payload IS NULL
     OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
     OR octet_length(p_payload::text) > 1048576 THEN
    RAISE EXCEPTION 'FLANDRE_INVALID_REQUEST' USING ERRCODE = '22023';
  END IF;
  request_body := jsonb_build_object('id',p_id,'base_version',p_base_version,
                                   'deleted',p_deleted,'payload',p_payload);
  -- This row lock is held to commit. Per-account sequence values therefore
  -- cannot be allocated by a transaction which commits after a later cursor.
  INSERT INTO public.flandre_sync_accounts(user_id) VALUES(caller) ON CONFLICT DO NOTHING;
  PERFORM 1 FROM public.flandre_sync_accounts WHERE user_id=caller FOR UPDATE;
  SELECT * INTO previous FROM public.flandre_sync_operations
    WHERE user_id=caller AND operation_id=p_operation_id;
  IF FOUND THEN
    IF previous.request IS DISTINCT FROM request_body THEN
      RAISE EXCEPTION 'FLANDRE_OPERATION_MISMATCH' USING ERRCODE = '22023';
    END IF;
    RETURN previous.result;
  END IF;
  SELECT * INTO existing FROM public.flandre_questions WHERE id=p_id;
  IF FOUND AND existing.user_id IS DISTINCT FROM caller THEN
    RAISE EXCEPTION 'FLANDRE_FORBIDDEN' USING ERRCODE = '42501';
  END IF;
  IF (existing.id IS NULL AND p_base_version <> 0)
     OR (existing.id IS NOT NULL AND existing.version <> p_base_version)
     OR (existing.deleted AND NOT p_deleted) THEN
    response_body := jsonb_build_object('status','conflict','record',
      CASE WHEN existing.id IS NULL THEN NULL ELSE to_jsonb(existing) END);
  ELSE
    IF NOT p_deleted THEN
      IF jsonb_typeof(p_payload->'question') IS DISTINCT FROM 'object'
         OR jsonb_typeof(p_payload->'attachments') IS DISTINCT FROM 'array'
         OR jsonb_array_length(p_payload->'attachments') > 50 THEN
        RAISE EXCEPTION 'FLANDRE_INVALID_PAYLOAD' USING ERRCODE = '22023';
      END IF;
      FOREACH field IN ARRAY ARRAY['stem','subject','question_type','answer','explanation',
        'tags','knowledge_points','difficulty','source','grade','notes'] LOOP
        IF jsonb_typeof(p_payload->'question'->field) IS DISTINCT FROM 'string'
           OR length(p_payload->'question'->>field) > 20000 THEN
          RAISE EXCEPTION 'FLANDRE_INVALID_QUESTION' USING ERRCODE = '22023';
        END IF;
      END LOOP;
      IF length(btrim(p_payload->'question'->>'stem')) = 0
         OR jsonb_typeof(p_payload->'question'->'options') IS DISTINCT FROM 'object'
         OR jsonb_typeof(p_payload->'question'->'is_wrong') IS DISTINCT FROM 'number'
         OR (p_payload->'question'->>'is_wrong') NOT IN ('0','1') THEN
        RAISE EXCEPTION 'FLANDRE_INVALID_QUESTION' USING ERRCODE = '22023';
      END IF;
      IF btrim(p_payload->'question'->>'difficulty') NOT IN ('','简单','中等','困难')
         OR length(p_payload->'question'->>'grade') > 100
         OR (p_payload->'question'->>'grade') ~ E'[\n\r]' THEN
        RAISE EXCEPTION 'FLANDRE_INVALID_QUESTION' USING ERRCODE = '22023';
      END IF;
      SELECT count(*) INTO option_count FROM jsonb_each(p_payload->'question'->'options');
      IF option_count = 1 OR option_count > 12 THEN
        RAISE EXCEPTION 'FLANDRE_INVALID_OPTIONS' USING ERRCODE = '22023';
      END IF;
      FOR option_item IN SELECT * FROM jsonb_each(p_payload->'question'->'options') LOOP
        IF option_item.key !~ '^[A-Z]$'
           OR jsonb_typeof(option_item.value) IS DISTINCT FROM 'string'
           OR length(option_item.value #>> '{}') > 20000
           OR length(btrim(option_item.value #>> '{}')) = 0 THEN
          RAISE EXCEPTION 'FLANDRE_INVALID_OPTIONS' USING ERRCODE = '22023';
        END IF;
      END LOOP;
      IF jsonb_typeof(p_payload->'review') IS DISTINCT FROM 'null' THEN
        IF jsonb_typeof(p_payload->'review') IS DISTINCT FROM 'object'
           OR coalesce(p_payload->'review'->>'mastery','') NOT IN ('mastered','unsure','unknown')
           OR coalesce(p_payload->'review'->>'due_at','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
           OR coalesce(p_payload->'review'->>'last_reviewed_at','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
           OR jsonb_typeof(p_payload->'review'->'review_count') IS DISTINCT FROM 'number'
           OR coalesce(p_payload->'review'->>'review_count','') !~ '^[1-9][0-9]{0,8}$' THEN
          RAISE EXCEPTION 'FLANDRE_INVALID_REVIEW' USING ERRCODE = '22023';
        END IF;
        PERFORM (p_payload->'review'->>'due_at')::timestamp,
                (p_payload->'review'->>'last_reviewed_at')::timestamp;
      END IF;
      IF (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(p_payload->'attachments'))
         <> jsonb_array_length(p_payload->'attachments') THEN
        RAISE EXCEPTION 'FLANDRE_DUPLICATE_ATTACHMENT' USING ERRCODE = '22023';
      END IF;
      FOR attachment IN SELECT value FROM jsonb_array_elements(p_payload->'attachments') LOOP
        FOREACH field IN ARRAY ARRAY['id','key','sha256','mime_type','original_name'] LOOP
          IF jsonb_typeof(attachment->field) IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'FLANDRE_INVALID_ATTACHMENT' USING ERRCODE = '22023';
          END IF;
        END LOOP;
        IF jsonb_typeof(attachment) IS DISTINCT FROM 'object'
           OR jsonb_typeof(attachment->'size') IS DISTINCT FROM 'number'
           OR (attachment->>'id') !~ '^[a-f0-9]{32}$'
           OR (attachment->>'sha256') !~ '^[a-f0-9]{64}$'
           OR attachment->>'mime_type' NOT IN ('image/png','image/jpeg','image/webp')
           OR length(attachment->>'original_name') > 260
           OR (attachment->>'size') !~ '^[0-9]{1,8}$'
           OR (attachment->>'size')::bigint NOT BETWEEN 1 AND 20971520
           OR split_part(attachment->>'key','/',1) IS DISTINCT FROM caller
           OR split_part(attachment->>'key','/',2) IS DISTINCT FROM replace(p_id::text,'-','')
           OR split_part(attachment->>'key','/',3) IS DISTINCT FROM (attachment->>'id')
           OR split_part(attachment->>'key','/',4) !~ ('^' || (attachment->>'sha256') || '\.(png|jpg|jpeg|webp)$')
           OR array_length(string_to_array(attachment->>'key','/'),1) <> 4
           OR NOT EXISTS (SELECT 1 FROM storage.objects o
              WHERE o.bucket_id='flandre-question-images' AND o.name=attachment->>'key'
                AND o.owner_id=caller) THEN
          RAISE EXCEPTION 'FLANDRE_INVALID_ATTACHMENT' USING ERRCODE = '22023';
        END IF;
      END LOOP;
    END IF;
    UPDATE public.flandre_sync_accounts SET next_seq=next_seq+1
      WHERE user_id=caller RETURNING next_seq INTO next_change;
    INSERT INTO public.flandre_questions(id,user_id,version,seq,deleted,payload)
      VALUES(p_id,caller,p_base_version+1,next_change,p_deleted,
             CASE WHEN p_deleted THEN '{}'::jsonb ELSE p_payload END)
      ON CONFLICT(id) DO UPDATE SET version=EXCLUDED.version,seq=EXCLUDED.seq,
        deleted=EXCLUDED.deleted,payload=EXCLUDED.payload,updated_at=now()
      WHERE public.flandre_questions.user_id=caller
        AND public.flandre_questions.version=p_base_version
      RETURNING * INTO existing;
    IF NOT FOUND THEN
      -- A different account may have inserted this UUID after the ownership
      -- check. Never update that account's row through the definer function.
      RAISE EXCEPTION 'FLANDRE_FORBIDDEN' USING ERRCODE = '42501';
    END IF;
    response_body := jsonb_build_object('status','applied','record',to_jsonb(existing));
  END IF;
  INSERT INTO public.flandre_sync_operations(user_id,operation_id,request,result)
    VALUES(caller,p_operation_id,request_body,response_body);
  RETURN response_body;
END $$;

CREATE FUNCTION public.flandre_sync_pull(p_after bigint DEFAULT 0, p_limit integer DEFAULT 50)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
AS $$
DECLARE caller text := auth.uid(); result jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'authenticated' OR caller IS NULL OR caller = '' THEN
    RAISE EXCEPTION 'FLANDRE_AUTH_REQUIRED' USING ERRCODE = '42501';
  END IF;
  IF p_after IS NULL OR p_after < 0 OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 THEN
    RAISE EXCEPTION 'FLANDRE_INVALID_CURSOR' USING ERRCODE = '22023';
  END IF;
  SELECT coalesce(jsonb_agg(to_jsonb(changed) ORDER BY changed.seq),'[]'::jsonb) INTO result
    FROM (SELECT * FROM public.flandre_questions WHERE user_id=caller AND seq>p_after
          ORDER BY seq LIMIT p_limit) changed;
  RETURN jsonb_build_object('records',result,'cursor',
    CASE WHEN jsonb_array_length(result)=0 THEN p_after
         ELSE (result->(jsonb_array_length(result)-1)->>'seq')::bigint END);
END $$;
REVOKE ALL ON FUNCTION public.flandre_sync_push(uuid,uuid,bigint,boolean,jsonb),
  public.flandre_sync_pull(bigint,integer) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.flandre_sync_push(uuid,uuid,bigint,boolean,jsonb),
  public.flandre_sync_pull(bigint,integer) TO authenticated;
COMMIT;
