-- Synthetic RPC and RLS checks. All writes are rolled back, including on failure.
BEGIN;
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.role','authenticated',true),
       set_config('request.jwt.claim.sub','LEARNING_CHECK_006_A',true);
DO $$
DECLARE
  word_id uuid:=gen_random_uuid(); attempt_id uuid:=gen_random_uuid(); op uuid:=gen_random_uuid();
  p jsonb:='{"word":"synthetic","meaning":"检查","phonetic":"","example":"","book":"","mastery":"unknown","review_count":0,"streak":0,"due_at":null,"last_reviewed_at":null}';
  history jsonb:='{"question_cloud_id":"","question_stem":"检查题干","question_subject":"英语","answered_at":"2026-10-11 10:00:00","user_answer":"A","result":"correct","mastery":"mastered","duration_seconds":3,"mistake_reason":""}';
  first jsonb; reply jsonb;
BEGIN
  IF jsonb_array_length(public.flandre_learning_pull()->'records')<>0 THEN RAISE EXCEPTION 'test account not empty'; END IF;
  first:=public.flandre_learning_push(word_id,op,'word',0,false,p);
  IF first->>'status'<>'applied' OR first#>>'{record,version}'<>'1' THEN RAISE EXCEPTION 'word push failed'; END IF;
  IF public.flandre_learning_push(word_id,op,'word',0,false,p)<>first THEN RAISE EXCEPTION 'retry changed result'; END IF;
  reply:=public.flandre_learning_push(word_id,gen_random_uuid(),'word',0,false,p);
  IF reply->>'status'<>'conflict' THEN RAISE EXCEPTION 'optimistic conflict missing'; END IF;
  BEGIN
    PERFORM public.flandre_learning_push(gen_random_uuid(),gen_random_uuid(),'word',0,false,jsonb_set(p,'{review_count}','true'));
    RAISE EXCEPTION 'boolean count accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  BEGIN
    INSERT INTO public.flandre_learning_records VALUES('LEARNING_CHECK_006_A',gen_random_uuid(),'word',1,99,false,p,now());
    RAISE EXCEPTION 'direct write accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  PERFORM set_config('request.jwt.claim.sub','LEARNING_CHECK_006_B',true);
  IF jsonb_array_length(public.flandre_learning_pull()->'records')<>0 OR EXISTS(SELECT 1 FROM public.flandre_learning_records) THEN RAISE EXCEPTION 'cross-account data visible'; END IF;
  PERFORM set_config('request.jwt.claim.sub','LEARNING_CHECK_006_A',true);
  first:=public.flandre_learning_push(attempt_id,gen_random_uuid(),'attempt',0,false,history);
  reply:=public.flandre_learning_push(attempt_id,gen_random_uuid(),'attempt',1,false,history);
  IF first->>'status'<>'applied' OR reply->>'status'<>'conflict' THEN RAISE EXCEPTION 'history immutability failed'; END IF;
  reply:=public.flandre_learning_push(word_id,gen_random_uuid(),'word',1,true,'{}');
  IF reply#>>'{record,deleted}'<>'true' OR reply#>>'{record,version}'<>'2' THEN RAISE EXCEPTION 'word deletion failed'; END IF;
  reply:=public.flandre_learning_pull(0,5);
  IF jsonb_array_length(reply->'records')<>2 OR (reply->>'cursor')::bigint<>3 THEN RAISE EXCEPTION 'pull ordering failed'; END IF;
  PERFORM set_config('request.jwt.claim.role','anon',true);
  BEGIN
    PERFORM public.flandre_learning_pull(); RAISE EXCEPTION 'anonymous caller accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
ROLLBACK;
SELECT 'PASS: retry, conflict, validation, RLS, immutable history, deletion, cursor, authentication; all synthetic writes rolled back' AS result;
