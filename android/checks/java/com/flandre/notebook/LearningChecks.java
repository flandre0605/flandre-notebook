package com.flandre.notebook;

import org.json.*;
import java.io.*;
import java.util.*;

/** Synthetic learning round trips and failure cases on Android's real SQLite. */
final class LearningChecks {
    final NativeChecks checks;
    LearningChecks(NativeChecks c){checks=c;}
    void check(boolean value,String label){checks.check(value,label);}
    interface Call{void run() throws Exception;}
    void rejects(Call call,String label) throws Exception{boolean failed=false;try{call.run();}catch(Exception error){failed=true;}check(failed,label);}
    void run() throws Exception {
        File root=new File(checks.getTargetContext().getFilesDir(),"learning-check-"+CloudApi.id());
        Notebook a=new Notebook(new File(root,"a"),"USER_A"),b=new Notebook(new File(root,"b"),"USER_A"),foreign=new Notebook(new File(root,"foreign"),"USER_B");
        NotebookChecks.Server server=new NotebookChecks.Server();CloudApi api=new CloudApi("USER_A","test","memory-only",7200,server);
        try{
            exchange(root);
            String question=a.save(null,new JSONObject().put("stem","历史快照").put("subject","数学"),null);
            a.practice(question,"答案",true,"mastered",7);a.word(null,"hello","你好","","Hello world");String word=a.words().getJSONObject(0).getString("id");a.reviewWord(word,"mastered",7);
            NotebookSync.synchronize(a,api);NotebookSync.synchronize(b,api);
            check(b.words().length()==1&&b.words().getJSONObject(0).getInt("review_count")==1&&b.words().getJSONObject(0).getInt("streak")==1,"word progress crosses Android workspaces");
            check(b.history(question).length()==1&&b.history(question).getJSONObject(0).getString("answer").equals("答案"),"answer history crosses workspaces");
            NotebookSync.synchronize(a,api);NotebookSync.synchronize(b,api);check(b.statistics().getInt("total")==1,"repeated pulls do not duplicate learning statistics");
            a.word(word,"hello","本机修改","","");b.word(word,"hello","另一设备修改","","");NotebookSync.synchronize(b,api);NotebookSync.synchronize(a,api);
            check(a.words().getJSONObject(0).getString("meaning").equals("本机修改")&&LearningSync.conflicts(a).length()==1,"concurrent words preserve local content and conflict");
            LearningSync.resolve(a,word,false);NotebookSync.synchronize(a,api);check(a.words().getJSONObject(0).getString("meaning").equals("另一设备修改"),"explicit cloud choice resolves word conflict");
            a.word(null,"offline","离线","","");server.lostLearning=true;final Notebook beforeRestart=a;rejects(()->NotebookSync.synchronize(beforeRestart,api),"lost learning acknowledgment preserves queue");JSONObject frozen=LearningSync.prepare(a);a.close();a=new Notebook(new File(root,"a"),"USER_A");check(CloudApi.same(frozen,LearningSync.prepare(a)),"restart preserves frozen learning request ID");NotebookSync.synchronize(a,api);NotebookSync.synchronize(b,api);check(b.words().length()==2,"retry creates one word");
            a.deleteWord(word);a.delete(question);NotebookSync.synchronize(a,api);NotebookSync.synchronize(b,api);check(b.words().length()==1&&b.statistics().getInt("total")==1,"word deletion sync keeps completed history");check(b.history(question).getJSONObject(0).getString("question_stem").equals("历史快照"),"deleted question history retains stem snapshot");
            JSONObject record=server.learning.values().iterator().next();rejects(()->LearningSync.record(foreign,record),"foreign account learning row refused");
            JSONObject bad=Notebook.copy(server.learning.values().stream().filter(r->r.optString("kind").equals("word")&&!r.optBoolean("deleted")).findFirst().get().getJSONObject("payload"));bad.put("review_count",true);rejects(()->LearningSync.validate("word",bad),"boolean review count refused");
            ByteArrayOutputStream archive=new ByteArrayOutputStream();NotebookBackup.export(a,archive);Notebook restored=new Notebook(new File(root,"restored"),"USER_A");try{NotebookBackup.restore(restored,new ByteArrayInputStream(archive.toByteArray()));check(restored.words().length()==a.words().length()&&restored.statistics().getInt("total")==1,"ZIP restores learning contents and history");check(LearningSync.pending(restored)==0,"ZIP restores synced learning identities without reupload");}finally{restored.close();}
        }finally{a.close();b.close();foreign.close();api.close();}
    }
    void exchange(File root) throws Exception {
        JSONArray rows;try(InputStream in=checks.getContext().getAssets().open("learning_exchange.json")){rows=new JSONArray(new String(NotebookBackup.read(in,131072),java.nio.charset.StandardCharsets.UTF_8));}
        TimeZone original=TimeZone.getDefault();TimeZone.setDefault(TimeZone.getTimeZone("Asia/Shanghai"));
        Notebook local=new Notebook(new File(root,"exchange"),"USER_A");
        try{List<JSONObject> records=new ArrayList<>();for(int i=0;i<rows.length();i++)records.add(LearningSync.record(local,rows.getJSONObject(i)));LearningSync.apply(local,records,2);
            for(JSONObject r:records)check(CloudApi.same(LearningSync.content(local,LearningSync.entity(local,r.getString("id"))),r.getJSONObject("payload")),"shared desktop/phone fields round trip including UTC");
            check(local.words().getJSONObject(0).getString("due_at").equals("2026-10-12 10:00:00"),"UTC due time converted to phone local time");
            check(local.history("cccccccccccccccccccccccccccccccc").getJSONObject(0).getString("time").equals("2026-10-11 10:00:00"),"UTC history converted to phone local time");
        }finally{local.close();TimeZone.setDefault(original);}
    }
    void ui(MainActivity main) throws Exception {
        NotebookChecks.Server server=new NotebookChecks.Server();CloudApi api=new CloudApi("USER_A","test","memory-only",7200,server);
        checks.runOnMainSync(()->{try{main.acceptAccount(api,"test");main.book.close();main.book=new Notebook(new File(main.getCacheDir(),"auto-learning-"+CloudApi.id()),"USER_A");main.book.word(null,"auto-opening","启动","","");}catch(Exception e){throw new AssertionError(e);}});
        waitIdle(main);check(server.learning.size()==1&&LearningSync.pending(main.book)==0,"account opening automatically uploads words");
        checks.runOnMainSync(()->{try{main.book.word(null,"auto-closing","关闭","","");main.automaticSync(true);}catch(Exception e){throw new AssertionError(e);}});
        waitIdle(main);check(server.learning.size()==2&&LearningSync.pending(main.book)==0,"background lifecycle automatically uploads words");
        final CloudApi offline=new CloudApi("USER_A","test","memory-only",7200,(p,m,b,t,k,d,l)->{throw new IOException("synthetic offline");});
        checks.runOnMainSync(()->{try{main.api=offline;main.book.word(null,"auto-offline","离线","","");main.automaticSync(true);}catch(Exception e){throw new AssertionError(e);}});
        waitIdle(main);check(LearningSync.pending(main.book)==1&&main.book.state("sync_error","").contains("offline"),"offline lifecycle preserves pending words and failure status");
        checks.runOnMainSync(()->{main.api=api;main.automaticSync(false);});waitIdle(main);check(server.learning.size()==3&&LearningSync.pending(main.book)==0,"foreground retry uploads one offline word");
        checks.runOnMainSync(()->{try{new CloudLoginStore(main).clear(main.book.uid);main.api=null;api.close();offline.close();main.getPreferences(0).edit().remove("offline_uid").commit();main.openWorkspace("LOCAL");main.home();}catch(Exception e){throw new AssertionError(e);}});
    }
    void waitIdle(MainActivity main) throws Exception {for(int i=0;i<200;i++){final boolean[] idle={false};checks.runOnMainSync(()->idle[0]=!main.autoSyncQueued&&!main.busy);if(idle[0])return;Thread.sleep(50);}throw new AssertionError("automatic sync timeout");}
}
