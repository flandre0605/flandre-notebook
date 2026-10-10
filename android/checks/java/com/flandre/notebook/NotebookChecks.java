package com.flandre.notebook;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.zip.*;

/** Synthetic local and mocked RPC checks. No user account credentials or real model requests. */
final class NotebookChecks {
    final NativeChecks checks;
    Notebook book;
    NotebookChecks(NativeChecks c){checks=c;}
    void check(boolean value,String label){checks.check(value,label);}
    interface Call {void run() throws Exception;}
    void reject(Call call,String label) throws Exception {boolean rejected=false;try{call.run();}catch(Exception expected){rejected=true;}check(rejected,label);}
    JSONObject q(String stem) throws Exception {return new JSONObject().put("stem",stem).put("subject","数学").put("notes","原笔记").put("is_wrong",1).put("options",new JSONObject());}
    static final class Server implements CloudApi.Transport {
        final Map<String,byte[]> images=new HashMap<>();final Map<String,JSONObject> rows=new LinkedHashMap<>(),operations=new HashMap<>();long seq=0;boolean lost=false,foreign=false,badPage=false;
        JSONObject change(String id,JSONObject p,boolean deleted) throws Exception {JSONObject old=rows.get(id);JSONObject row=new JSONObject().put("id",id).put("user_id","USER_A").put("version",old==null?1:old.getLong("version")+1).put("seq",++seq).put("deleted",deleted).put("payload",deleted?new JSONObject():Notebook.copy(p));rows.put(id,row);return row;}
        public CloudApi.Reply send(String path,String method,byte[] body,String mime,String token,String device,int limit) throws IOException {
            try{
                if(path.startsWith("/v1/storages/object/")){if(method.equals("POST")){boolean exists=images.containsKey(path);images.putIfAbsent(path,body);return new CloudApi.Reply(exists?409:200,new byte[0]);}byte[] image=images.get(path);return new CloudApi.Reply(image==null?404:200,image==null?new byte[0]:image);}
                JSONObject request=new JSONObject(new String(body,StandardCharsets.UTF_8)),response;
                if(path.endsWith("flandre_sync_push")){
                    String id=request.getString("p_id"),op=request.getString("p_operation_id");response=operations.get(op);
                    if(response==null){JSONObject old=rows.get(id);if((old==null&&request.getLong("p_base_version")!=0)||(old!=null&&old.getLong("version")!=request.getLong("p_base_version"))||(old!=null&&old.getBoolean("deleted")&&!request.getBoolean("p_deleted")))response=new JSONObject().put("status","conflict").put("record",old==null?JSONObject.NULL:Notebook.copy(old));
                        else response=new JSONObject().put("status","applied").put("record",change(id,request.getJSONObject("p_payload"),request.getBoolean("p_deleted")));operations.put(op,Notebook.copy(response));}
                    if(lost){lost=false;throw new IOException("Synthetic lost reply after server commit");}response=Notebook.copy(response);if(foreign&&response.optJSONObject("record")!=null)response.getJSONObject("record").put("user_id","USER_B");
                }else if(path.endsWith("flandre_sync_pull")){
                    List<JSONObject> sorted=new ArrayList<>(rows.values());sorted.sort(Comparator.comparingLong(r->r.optLong("seq")));JSONArray page=new JSONArray();long cursor=request.getLong("p_after");for(JSONObject r:sorted)if(r.getLong("seq")>cursor&&page.length()<request.getInt("p_limit")){JSONObject row=Notebook.copy(r);if(badPage)row.put("user_id","USER_B");page.put(row);cursor=r.getLong("seq");}response=new JSONObject().put("records",page).put("cursor",cursor);
                }else throw new IOException("Unexpected test RPC");
                return new CloudApi.Reply(200,response.toString().getBytes(StandardCharsets.UTF_8));
            }catch(IOException e){throw e;}catch(Exception e){throw new IOException("Synthetic malformed response",e);}
        }
    }
    void run() throws Exception {
        File base=new File(checks.getTargetContext().getFilesDir(),"notebook-check-"+CloudApi.id());book=new Notebook(new File(base,"a"),"USER_A");
        try{
            String id=book.save(null,q("求极限 $\\lim_{x\\to0}x$"),null);check(book.entries("极限","数学","wrong").size()==1,"offline save/search/filter");
            reject(()->book.save(null,q(""),null),"empty stem refused");JSONObject bad=q("invalid").put("options",new JSONObject().put("A","only"));reject(()->book.save(null,bad,null),"single option refused");
            reject(()->book.save(null,q("bad").put("options","not object"),null),"invalid option type refused");
            String draft=CloudApi.id();book.draft(draft,new JSONObject().put("questions",new JSONArray().put(q("valid first")).put(q(""))).put("images",new JSONArray()));reject(()->book.confirmDraft(draft),"invalid batch refused atomically");check(book.entries("","","").size()==1&&book.draft(draft)!=null,"batch failure preserves all drafts and creates no partial question");
            book.draft(draft,new JSONObject().put("questions",new JSONArray().put(q("draft"))).put("images",new JSONArray()));book.confirmDraft(draft);reject(()->book.confirmDraft(draft),"confirmed draft cannot import twice");check(book.entries("","","").size()==2,"draft confirmed exactly once");
            String attempt=CloudApi.id();JSONObject next=new JSONObject().put("index",1);book.practiceOnce(id,"0",true,"mastered",7,attempt,next);book.practiceOnce(id,"0",true,"mastered",7,attempt,next);check(book.history(id).length()==1&&book.entry(id).getJSONObject("payload").getJSONObject("review").getLong("review_count")==1,"attempt and progress transaction prevents double submission");check(new JSONObject(book.state("practice","")).getInt("index")==1,"practice checkpoint persisted with attempt");check(book.entries("","","mastered").size()==1,"mastery filter");
            book.word(null,"limit","极限","","a limit");book.word(null,"LIMIT","界限","","updated");check(book.words().length()==1,"word import upserts case-insensitive duplicate");
            JSONObject image=book.addImage(checks.image(Bitmap.CompressFormat.PNG),"png","synthetic-original.png",id);book.save(id,q("求极限 $\\lim_{x\\to0}x$"),new JSONArray().put(image));
            Notebook guest=new Notebook(new File(base,"guest"),"LOCAL"),target=new Notebook(new File(base,"import-target"),"IMPORT_USER");try{String guestId=guest.save(null,q("本机空间题目"),null);JSONObject guestImage=guest.addImage(checks.image(Bitmap.CompressFormat.PNG),"png","original.png",guestId);guest.save(guestId,q("本机空间题目"),new JSONArray().put(guestImage));guest.practice(guestId,"0",true,"mastered",7);check(NotebookScreens.importLocal(target,guest)==1&&NotebookScreens.importLocal(target,guest)==0&&guest.entries("","","").size()==1,"guest import copies once and preserves local original");JSONObject copied=target.entries("","","").get(0);check(!copied.getString("id").equals(guestId)&&copied.getJSONObject("payload").getJSONObject("review").getString("mastery").equals("mastered")&&copied.getJSONObject("payload").getJSONArray("attachments").getJSONObject(0).getString("key").startsWith("IMPORT_USER/"),"guest import remaps owner and image identity with review intact");}finally{guest.close();target.close();}
            Server server=new Server();CloudApi api=new CloudApi("USER_A","test","test-only",7200,server);server.lost=true;
            final Notebook first=book;reject(()->NotebookSync.synchronize(first,api),"lost cloud response leaves durable outbox");JSONObject frozen=book.prepare();check(frozen!=null&&server.rows.size()==1,"server commit occurred once; frozen operation retained");
            JSONObject update=book.entry(id).getJSONObject("payload").getJSONObject("question").put("notes","后续本机修改");book.save(id,update,null);
            NotebookSync.synchronize(book,api);check(server.rows.get(id).getLong("version")==2&&book.entry(id).getInt("dirty")==0,"retry acknowledges old revision and uploads subsequent edit");check(server.images.size()==1,"immutable image retry creates one cloud object");
            book.close();book=new Notebook(new File(base,"a"),"USER_A");check(book.entries("","","").size()==2&&book.history(id).length()==1,"cold reopen retains independent learning data");
            JSONObject remote=Notebook.copy(server.rows.get(id).getJSONObject("payload"));remote.getJSONObject("question").put("notes","电脑修改");server.change(id,remote,false);book.save(id,book.entry(id).getJSONObject("payload").getJSONObject("question").put("notes","手机修改"),null);
            NotebookSync.synchronize(book,api);check(!book.entry(id).isNull("conflict")&&book.entry(id).getJSONObject("payload").getJSONObject("question").getString("notes").equals("手机修改"),"concurrent edits preserve local content and retain conflict");book.resolve(id,true);NotebookSync.synchronize(book,api);check(server.rows.get(id).getJSONObject("payload").getJSONObject("question").getString("notes").equals("手机修改")&&book.drafts().length()>0,"chosen local edit rebased; recovery draft retained");
            long before=Long.parseLong(book.state("cursor","0"));String newer=CloudApi.id();server.change(newer,new JSONObject().put("question",Notebook.question(q("foreign page"))).put("review",JSONObject.NULL).put("attachments",new JSONArray()),false);server.badPage=true;final Notebook reopened=book;reject(()->NotebookSync.synchronize(reopened,api),"foreign paged record rejected");check(Long.parseLong(book.state("cursor","0"))==before&&book.entry(newer)==null,"invalid page advances neither cursor nor local data");server.badPage=false;NotebookSync.synchronize(book,api);
            JSONObject changed=book.entry(id).getJSONObject("payload").getJSONObject("question").put("notes","pending spoof");book.save(id,changed,null);server.foreign=true;reject(()->NotebookSync.synchronize(reopened,api),"foreign push acknowledgement rejected");check(book.prepare()!=null,"invalid acknowledgement keeps operation");server.foreign=false;NotebookSync.synchronize(book,api);
            byte[] backup;try(ByteArrayOutputStream out=new ByteArrayOutputStream()){NotebookBackup.export(book,out);backup=out.toByteArray();}
            book.delete(id);NotebookBackup.restore(book,new ByteArrayInputStream(backup));check(book.entry(id).getInt("deleted")==0&&book.words().length()==1&&book.history(id).length()==1,"backup restores questions/images/practice/words");check(new File(book.root,"backups").listFiles().length>0,"restore keeps recovery snapshot");
            Notebook other=new Notebook(new File(base,"b"),"USER_B");try{reject(()->NotebookBackup.restore(other,new ByteArrayInputStream(backup)),"another account backup rejected");check(other.entries("","","").isEmpty(),"foreign backup never replaces account");}finally{other.close();}
            ByteArrayOutputStream badZip=new ByteArrayOutputStream();try(ZipOutputStream zip=new ZipOutputStream(badZip)){zip.putNextEntry(new ZipEntry("../outside.txt"));zip.write(1);zip.closeEntry();}reject(()->NotebookBackup.restore(reopened,new ByteArrayInputStream(badZip.toByteArray())),"traversal backup rejected");check(book.entry(id).getInt("deleted")==0,"malformed backup preserves active questions");
            JSONArray qs=AiClient.parse("```json\n{\"questions\":[{\"stem\":\"计算 $x^2$\",\"options\":{},\"answer\":\"0\",\"explanation\":\"说明\"}]}\n```");check(qs.length()==1&&qs.getJSONObject(0).getString("stem").contains("$x^2$"),"JSON recognition preserves formulas");
            qs=AiClient.parse("根据图片整理如下：\n\n**题目：**\n计算 $x^2$\n\n**解答：**\n代入。\n\n**综上所述：**\n$0$");check(qs.length()==1&&qs.getJSONObject(0).getString("answer").equals("$0$"),"complete single-question text recovery");reject(()->AiClient.parse("模型服务错误，请稍后重试"),"service error cannot become a question");reject(()->AiClient.parse("**题目：**\n$x$\n**解答：**\n解析\n**答案：**\n$0"),"truncated formula refused");
            reject(()->AiClient.endpoint("http://example.com/v1/chat/completions"),"model endpoint requires HTTPS");
            reject(()->AiClient.parse("{\"stem\":\"first\"} {\"stem\":\"second\"}"),"trailing JSON cannot silently discard another question");
            reject(()->AiClient.parse("```json\n{\"stem\":\"first\"}\n```\nsecond question"),"content after code fence refused");
            JSONObject fileQuestion=Notebook.question(q("含逗号,引号\"以及\n第二行").put("answer","$\\frac{1}{2}$"));String csv=QuestionFiles.export(new JSONArray().put(fileQuestion));check(CloudApi.same(fileQuestion,QuestionFiles.questions(csv).getJSONObject(0)),"CSV preserves quoted cells, newlines, Chinese and formulas");reject(()->QuestionFiles.questions("stem,answer\n\"unclosed,0"),"truncated CSV rejected");reject(()->QuestionFiles.questions("stem,题干\na,b"),"duplicate CSV question columns refused");
            portableFiles();
            String owner="CHECK_"+CloudApi.id();JSONObject profile=new JSONObject().put("url","https://example.com/v1/chat/completions").put("model","test").put("key","synthetic-secret-only");ModelProfile.write(checks.getTargetContext(),owner,profile);check(CloudApi.same(profile,ModelProfile.read(checks.getTargetContext(),owner)),"encrypted model profile roundtrip");check(!checks.getTargetContext().getSharedPreferences("models",0).getString(owner,"").contains("synthetic-secret"),"model key never stored as plaintext");checks.getTargetContext().getSharedPreferences("models",0).edit().remove(owner).commit();
            // Deletion conflict keeps an explicitly chosen phone copy under a NEW UUID.
            server.change(id,new JSONObject(),true);book.save(id,book.entry(id).getJSONObject("payload").getJSONObject("question").put("notes","keep after remote delete"),null);NotebookSync.synchronize(book,api);int count=book.entries("","","").size();book.resolve(id,true);check(book.entry(id).getInt("deleted")==1&&book.entries("","","").size()==count,"remote deletion not resurrected; local copy receives fresh identity");NotebookSync.synchronize(book,api);
        }finally{book.close();}
    }
    void portableFiles() throws Exception {
        JSONArray json,csv;
        try(InputStream in=checks.getContext().getAssets().open("portable_exchange.json")){json=QuestionFiles.questions(new String(NotebookBackup.read(in,QuestionFiles.MAX_BYTES),StandardCharsets.UTF_8));}
        try(InputStream in=checks.getContext().getAssets().open("portable_exchange.csv")){csv=QuestionFiles.questions(new String(NotebookBackup.read(in,QuestionFiles.MAX_BYTES),StandardCharsets.UTF_8));}
        check(CloudApi.same(json,csv),"desktop JSON and escaped CSV import identically on phone");
        check(json.getJSONObject(0).getString("stem").startsWith("-2")&&json.getJSONObject(0).getString("answer").equals("-1")&&json.getJSONObject(0).getString("notes").equals("'literal"),"negative values and literal quotes survive desktop-to-phone exchange");
        String exportedJson=QuestionFiles.json(json),exportedCsv=QuestionFiles.export(json);
        check(CloudApi.same(json,QuestionFiles.questions(exportedJson))&&CloudApi.same(json,QuestionFiles.questions(exportedCsv)),"phone JSON and CSV round trips preserve every field");
        JSONObject file=new JSONObject(exportedJson);check(file.getString("format").equals("flandre-questions")&&file.getInt("version")==1&&exportedCsv.contains("_flandre_escaped")&&exportedCsv.contains("\"'=1+1\""),"phone exports use desktop format and neutralize spreadsheet formulas");
        check(CloudApi.same(json,QuestionFiles.questions(new JSONObject().put("questions",json).toString())),"legacy phone JSON remains readable");
        reject(()->QuestionFiles.questions(new JSONObject().put("format","flandre-questions").put("version",2).put("questions",json).toString()),"unknown portable file version refused");
        JSONArray tooMany=new JSONArray();for(int i=0;i<=QuestionFiles.MAX_ROWS;i++)tooMany.put(json.getJSONObject(0));reject(()->QuestionFiles.json(tooMany),"phone export obeys desktop 5000-question limit");
        File folder=new File(checks.getTargetContext().getCacheDir(),"portable-exchange");if(!folder.isDirectory()&&!folder.mkdirs())throw new IOException("Cannot create synthetic exchange directory");
        PhotoQueue.atomic(new File(folder,"phone.json"),exportedJson.getBytes(StandardCharsets.UTF_8));PhotoQueue.atomic(new File(folder,"phone.csv"),exportedCsv.getBytes(StandardCharsets.UTF_8));
    }
    void ui(Activity activity) throws Exception {
        MainActivity main=(MainActivity)activity;final FormulaView[] formula=new FormulaView[1];
        checks.runOnMainSync(()->{try{
            main.openWorkspace("UI_"+CloudApi.id());main.home();main.screens.newDraft(null);List<EditText> edits=new ArrayList<>();checks.findEditors(main.getWindow().getDecorView(),edits);edits.get(0).setText("手机独立题目 $\\frac{1}{2}$");edits.get(3).setText("0.5");click(main.getWindow().getDecorView(),"确认收录全部草稿");check(main.book.entries("","","").size()==1,"native editor confirms local question without login");
            String photo=main.screens.photoDraft(main.book,checks.image(Bitmap.CompressFormat.PNG),"png",checks.image(Bitmap.CompressFormat.JPEG),"phone-photo","memo");check(main.book.draft(photo).getJSONArray("images").length()==2,"phone photo creates recoverable original and crop before model request");
            main.screens.startPractice(main.book.entries("","",""));click(main.getWindow().getDecorView(),"提交并查看答案");click(main.getWindow().getDecorView(),"已掌握 · 记录并继续");check(main.book.statistics().getInt("total")==1,"native practice records independently");
            main.book.word(null,"first","第一","","");main.book.word(null,"second","第二","","");main.screens.startWords(false);click(main.getWindow().getDecorView(),"翻开释义");check(new JSONObject(main.book.state("word_session","")).getBoolean("revealed"),"word reveal checkpoint persists");String first=new JSONObject(main.book.state("word_session","")).getJSONArray("ids").getString(0);click(main.getWindow().getDecorView(),"已掌握 · 下一词");JSONObject progress=new JSONObject(main.book.state("word_session",""));check(progress.getInt("index")==1&&!progress.getJSONArray("ids").getString(1).equals(first),"review reordering does not skip words");main.screens.wordList();main.screens.resumeWords();check(new JSONObject(main.book.state("word_session","")).getInt("index")==1,"word session resumes after navigation");
            main.book.putState("word_ai_result","{\"");main.screens.wordReview("{\"");check(checks.findText(main.ui.root,"单词补全未完成")&&!has(main.ui.root,"核对并保存")&&main.book.words().length()==2,"truncated word output retains diagnostic draft without a save-success screen");
            String wordRaw="{\"words\":[{\"word\":\"third\",\"meaning\":\"第三\",\"phonetic\":\"\",\"example\":\"the third word\"}]}";main.book.putState("word_ai_result",wordRaw);main.screens.wordReview(wordRaw);List<EditText> wordEdits=new ArrayList<>();checks.findEditors(main.ui.root,wordEdits);check(wordEdits.size()==4&&wordEdits.get(0).getText().toString().equals("third")&&wordEdits.get(1).getText().toString().equals("第三"),"word completion renders editable fields rather than a raw JSON box");wordEdits.get(1).setText("第三个");main.ui.back.performClick();main.screens.wordReview(main.book.state("word_ai_result",""));click(main.ui.root,"核对并保存");check(main.book.words().length()==3&&main.book.state("word_ai_result","missing").isEmpty(),"review edits survive navigation and confirmation commits words while clearing pending result");
            main.screens.page("Formula test","Synthetic only",main::home);formula[0]=main.screens.math("安全文本 <script>window.pwn=1</script> $\\frac{1}{2}$");
        }catch(Exception e){throw new AssertionError(e);}});
        boolean ready=false;for(int i=0;i<50&&!ready;i++){CountDownLatch latch=new CountDownLatch(1);final String[] value=new String[1];checks.runOnMainSync(()->formula[0].evaluateJavascript("document.documentElement.dataset.ready==='1' && !!document.querySelector('.katex') && !window.pwn",answer->{value[0]=answer;latch.countDown();}));if(!latch.await(2,TimeUnit.SECONDS))throw new AssertionError("formula callback timeout");ready="true".equals(value[0]);if(!ready)Thread.sleep(100);}
        check(ready,"offline KaTeX renders formula and escapes injected HTML");
        Thread.sleep(450);checks.runOnMainSync(()->{check(formula[0].getHeight()<main.dp(260),"short formula reader shrinks to its content instead of fixed blank space");StringBuilder longText=new StringBuilder();for(int i=0;i<25;i++)longText.append("长题目第 ").append(i+1).append(" 行：$x^2+1$\n");main.screens.page("Long formula test","",main::home);formula[0]=main.screens.math(longText.toString());});
        boolean expanded=false;for(int i=0;i<40&&!expanded;i++){final boolean[] large={false};checks.runOnMainSync(()->large[0]=formula[0].getHeight()>main.dp(260));expanded=large[0];if(!expanded)Thread.sleep(100);}check(expanded,"long formula reader expands within the outer page scroll");
        String previous=main.getPreferences(0).getString("offline_uid",null),workspace=main.book.uid;
        checks.runOnMainSync(()->{main.getPreferences(0).edit().putString("offline_uid",workspace).commit();main.finish();});
        Activity reopened=null;try{reopened=checks.startActivitySync(new Intent(checks.getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));MainActivity restored=(MainActivity)reopened;
            check(restored.api==null&&restored.book.uid.equals(workspace)&&restored.book.statistics().getInt("total")==1,"cold activity opens previous workspace offline with learning history");check(new JSONObject(restored.book.state("word_session","")).getInt("index")==1,"cold activity retains word study progress");
        }finally{if(reopened!=null){Activity close=reopened;checks.runOnMainSync(close::finish);}android.content.SharedPreferences.Editor editor=main.getPreferences(0).edit();if(previous==null)editor.remove("offline_uid");else editor.putString("offline_uid",previous);editor.commit();}
    }
    void click(View root,String title){if(root instanceof Button&&((Button)root).getText().toString().equals(title)){root.performClick();return;}if(root instanceof ViewGroup){ViewGroup g=(ViewGroup)root;for(int i=0;i<g.getChildCount();i++)if(has(g.getChildAt(i),title)){click(g.getChildAt(i),title);return;}}throw new AssertionError("Button not found: "+title);}
    boolean has(View v,String s){if(v instanceof Button&&((Button)v).getText().toString().equals(s))return true;if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)if(has(g.getChildAt(i),s))return true;}return false;}
}
