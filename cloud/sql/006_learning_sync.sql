-- Learning sync v1. Execute after 004 as environment administrator.
BEGIN;
CREATE TABLE public.flandre_learning_accounts(user_id varchar(64) PRIMARY KEY,next_seq bigint NOT NULL DEFAULT 0);
CREATE TABLE public.flandre_learning_records(
  user_id varchar(64) NOT NULL,id uuid NOT NULL,kind text NOT NULL CHECK(kind IN ('word','attempt')),
  version bigint NOT NULL CHECK(version>0),seq bigint NOT NULL,deleted boolean NOT NULL DEFAULT false,
  payload jsonb NOT NULL,updated_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(user_id,id),UNIQUE(user_id,seq));
CREATE TABLE public.flandre_learning_operations(
  user_id varchar(64) NOT NULL,operation_id uuid NOT NULL,request jsonb NOT NULL,result jsonb NOT NULL,
  PRIMARY KEY(user_id,operation_id));
ALTER TABLE public.flandre_learning_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flandre_learning_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flandre_learning_operations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.flandre_learning_accounts,public.flandre_learning_records,public.flandre_learning_operations FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.flandre_learning_records TO authenticated;
CREATE POLICY flandre_learning_own ON public.flandre_learning_records FOR SELECT TO authenticated USING(user_id=(SELECT auth.uid()));

CREATE FUNCTION public.flandre_learning_push(p_id uuid,p_operation_id uuid,p_kind text,p_base_version bigint,p_deleted boolean,p_payload jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
  caller text:=auth.uid(); existing public.flandre_learning_records%ROWTYPE;
  previous public.flandre_learning_operations%ROWTYPE; request_body jsonb; response_body jsonb;
  next_change bigint; field text; fields text[]; max_length integer; date_value timestamp;
BEGIN
  IF auth.role() IS DISTINCT FROM 'authenticated' OR caller IS NULL OR caller='' THEN
    RAISE EXCEPTION 'FLANDRE_AUTH_REQUIRED' USING ERRCODE='42501';
  END IF;
  IF p_id IS NULL OR p_operation_id IS NULL OR p_kind IS NULL OR p_kind NOT IN ('word','attempt')
     OR p_base_version IS NULL OR p_base_version<0 OR p_deleted IS NULL
     OR p_payload IS NULL OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
     OR octet_length(p_payload::text)>131072 OR (p_kind='attempt' AND p_deleted) THEN
    RAISE EXCEPTION 'FLANDRE_INVALID_LEARNING_REQUEST' USING ERRCODE='22023';
  END IF;
  request_body:=jsonb_build_object('id',p_id,'kind',p_kind,'base_version',p_base_version,'deleted',p_deleted,'payload',p_payload);
  INSERT INTO public.flandre_learning_accounts(user_id) VALUES(caller) ON CONFLICT DO NOTHING;
  PERFORM 1 FROM public.flandre_learning_accounts WHERE user_id=caller FOR UPDATE;
  SELECT * INTO previous FROM public.flandre_learning_operations WHERE user_id=caller AND operation_id=p_operation_id;
  IF FOUND THEN
    IF previous.request IS DISTINCT FROM request_body THEN RAISE EXCEPTION 'FLANDRE_OPERATION_MISMATCH' USING ERRCODE='22023'; END IF;
    RETURN previous.result;
  END IF;
  IF p_deleted THEN
    IF p_payload<>'{}'::jsonb THEN RAISE EXCEPTION 'FLANDRE_INVALID_TOMBSTONE' USING ERRCODE='22023'; END IF;
  ELSE
    fields:=CASE WHEN p_kind='word' THEN ARRAY['word','meaning','phonetic','example','book','mastery','review_count','streak','due_at','last_reviewed_at']
      ELSE ARRAY['question_cloud_id','question_stem','question_subject','answered_at','user_answer','result','mastery','duration_seconds','mistake_reason'] END;
    IF (SELECT count(*) FROM jsonb_object_keys(p_payload))<>cardinality(fields) OR NOT p_payload ?& fields THEN
      RAISE EXCEPTION 'FLANDRE_INVALID_LEARNING_FIELDS' USING ERRCODE='22023';
    END IF;
    FOREACH field IN ARRAY fields LOOP
      IF field IN ('review_count','streak','duration_seconds') THEN
        IF jsonb_typeof(p_payload->field) IS DISTINCT FROM 'number' OR (p_payload->>field) !~ '^[0-9]+$'
          OR (p_payload->>field)::numeric>2147483647 THEN RAISE EXCEPTION 'FLANDRE_INVALID_LEARNING_NUMBER' USING ERRCODE='22023'; END IF;
      ELSIF field IN ('due_at','last_reviewed_at','answered_at') THEN
        IF p_kind='word' AND jsonb_typeof(p_payload->field)='null' THEN CONTINUE; END IF;
        IF jsonb_typeof(p_payload->field) IS DISTINCT FROM 'string' OR (p_payload->>field) !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$' THEN
          RAISE EXCEPTION 'FLANDRE_INVALID_LEARNING_DATE' USING ERRCODE='22023'; END IF;
        date_value:=(p_payload->>field)::timestamp;
        IF to_char(date_value,'YYYY-MM-DD HH24:MI:SS')<>(p_payload->>field) THEN RAISE EXCEPTION 'FLANDRE_INVALID_LEARNING_DATE' USING ERRCODE='22023'; END IF;
      ELSE
        max_length:=CASE WHEN field IN ('word','phonetic') THEN 300 WHEN field IN ('meaning','example') THEN 4000 WHEN field='book' THEN 100 ELSE 20000 END;
        IF jsonb_typeof(p_payload->field) IS DISTINCT FROM 'string' OR length(p_payload->>field)>max_length THEN
          RAISE EXCEPTION 'FLANDRE_INVALID_LEARNING_TEXT' USING ERRCODE='22023'; END IF;
      END IF;
    END LOOP;
    IF (p_payload->>'mastery') NOT IN ('unknown','unsure','mastered')
      OR (p_kind='word' AND btrim(p_payload->>'word')='')
      OR (p_kind='attempt' AND ((p_payload->>'result') NOT IN ('correct','incorrect','skipped')
        OR (p_payload->>'question_cloud_id') !~ '^$|^[a-f0-9]{32}$')) THEN
      RAISE EXCEPTION 'FLANDRE_INVALID_LEARNING_VALUE' USING ERRCODE='22023';
    END IF;
  END IF;
  SELECT * INTO existing FROM public.flandre_learning_records WHERE user_id=caller AND id=p_id;
  IF (existing.id IS NULL AND p_base_version<>0) OR (existing.id IS NOT NULL AND
      (existing.version<>p_base_version OR existing.kind<>p_kind OR p_kind='attempt')) THEN
    response_body:=jsonb_build_object('status','conflict','record',CASE WHEN existing.id IS NULL THEN NULL ELSE to_jsonb(existing) END);
  ELSE
    UPDATE public.flandre_learning_accounts SET next_seq=next_seq+1 WHERE user_id=caller RETURNING next_seq INTO next_change;
    INSERT INTO public.flandre_learning_records(user_id,id,kind,version,seq,deleted,payload)
      VALUES(caller,p_id,p_kind,p_base_version+1,next_change,p_deleted,p_payload)
      ON CONFLICT(user_id,id) DO UPDATE SET version=EXCLUDED.version,seq=EXCLUDED.seq,deleted=EXCLUDED.deleted,payload=EXCLUDED.payload,updated_at=now()
      WHERE public.flandre_learning_records.version=p_base_version RETURNING * INTO existing;
    IF NOT FOUND THEN RAISE EXCEPTION 'FLANDRE_VERSION_CHANGED' USING ERRCODE='40001'; END IF;
    response_body:=jsonb_build_object('status','applied','record',to_jsonb(existing));
  END IF;
  INSERT INTO public.flandre_learning_operations VALUES(caller,p_operation_id,request_body,response_body);
  RETURN response_body;
END $$;

CREATE FUNCTION public.flandre_learning_pull(p_after bigint DEFAULT 0,p_limit integer DEFAULT 5)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE caller text:=auth.uid(); result jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'authenticated' OR caller IS NULL OR caller='' THEN RAISE EXCEPTION 'FLANDRE_AUTH_REQUIRED' USING ERRCODE='42501'; END IF;
  IF p_after IS NULL OR p_after<0 OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 5 THEN RAISE EXCEPTION 'FLANDRE_INVALID_CURSOR' USING ERRCODE='22023'; END IF;
  SELECT coalesce(jsonb_agg(to_jsonb(changed) ORDER BY changed.seq),'[]'::jsonb) INTO result
    FROM (SELECT * FROM public.flandre_learning_records WHERE user_id=caller AND seq>p_after ORDER BY seq LIMIT p_limit) changed;
  RETURN jsonb_build_object('records',result,'cursor',CASE WHEN jsonb_array_length(result)=0 THEN p_after ELSE (result->(jsonb_array_length(result)-1)->>'seq')::bigint END);
END $$;
REVOKE ALL ON FUNCTION public.flandre_learning_push(uuid,uuid,text,bigint,boolean,jsonb),public.flandre_learning_pull(bigint,integer) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.flandre_learning_push(uuid,uuid,text,bigint,boolean,jsonb),public.flandre_learning_pull(bigint,integer) TO authenticated;
COMMIT;
