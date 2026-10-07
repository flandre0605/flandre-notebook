package com.flandre.notebook;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.os.Bundle;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Runs inside an isolated emulator. Synthetic images only; no cloud calls. */
public final class NativeChecks extends Instrumentation {
    int passed=0;
    void check(boolean value,String label){if(!value)throw new AssertionError(label);passed++;}
    public void onCreate(Bundle args){super.onCreate(args);start();}
    byte[] image(Bitmap.CompressFormat format) throws Exception {Bitmap b=Bitmap.createBitmap(120,80,Bitmap.Config.ARGB_8888);b.eraseColor(Color.WHITE);ByteArrayOutputStream out=new ByteArrayOutputStream();b.compress(format,94,out);b.recycle();return out.toByteArray();}
    static final class Server implements CloudApi.Transport {
        final Map<String,byte[]> images=new HashMap<>();
        final Map<String,JSONObject> rows=new HashMap<>();
        boolean lostReply=true,corrupt=false,foreign=false;
        int calls=0;
        public CloudApi.Reply send(String path,String method,byte[] body,String mime,String token,String device,int limit) throws IOException {
            calls++;
            try {
                if(path.startsWith("/v1/storages/object/")){
                    if(method.equals("POST")){int status=images.containsKey(path)?409:200;images.putIfAbsent(path,body);return new CloudApi.Reply(status,new byte[0]);}
                    return new CloudApi.Reply(200,corrupt?new byte[]{1}:images.get(path));
                }
                JSONObject args=new JSONObject(new String(body,StandardCharsets.UTF_8));String id=args.getString("p_id");
                JSONObject row=rows.get(id);
                if(row==null){row=new JSONObject().put("id",id).put("user_id","USER_A").put("status","pending").put("payload",args.getJSONObject("p_payload"));rows.put(id,row);}
                if(lostReply){lostReply=false;throw new IOException("Synthetic lost reply after commit");}
                JSONObject copy=new JSONObject(row.toString());if(foreign)copy.put("user_id","USER_B");
                return new CloudApi.Reply(200,new JSONObject().put("record",copy).toString().getBytes(StandardCharsets.UTF_8));
            }catch(JSONException e){throw new IOException("Synthetic invalid JSON");}
        }
    }
    public void onStart(){
        Bundle result=new Bundle();Activity activity=null;
        try {
            NotebookChecks notebookChecks=new NotebookChecks(this);notebookChecks.run();
            File base=new File(getTargetContext().getFilesDir(),"checks-"+CloudApi.id());
            PhotoQueue queue=new PhotoQueue(base,"USER_A");byte[] png=image(Bitmap.CompressFormat.PNG),jpg=image(Bitmap.CompressFormat.JPEG);
            JSONObject task=queue.save(png,"png",jpg,"Synthetic question","Keep original");
            check(queue.tasks().size()==1,"saved queue");
            check(CloudApi.same(task,new PhotoQueue(base,"USER_A").load(queue.tasks().get(0))),"restart preserves immutable task ID and payload");
            check(new PhotoQueue(base,"USER_B").tasks().isEmpty(),"account directory isolation");
            Server server=new Server();CloudApi api=new CloudApi("USER_A","test","memory-only",7200,server);
            boolean failed=false;try{queue.uploadAll(api);}catch(IOException e){failed=true;}
            check(failed&&!queue.load(queue.tasks().get(0)).getBoolean("uploaded"),"lost cloud reply keeps pending operation");
            check(server.rows.size()==1&&server.images.size()==2,"server committed original and crop once");
            check(queue.uploadAll(api)==1,"retry same receipt succeeds");
            check(server.rows.size()==1&&queue.load(queue.tasks().get(0)).getBoolean("uploaded"),"retry creates no duplicate");
            check(queue.uploadAll(api)==0,"acknowledged task is not resent");
            JSONObject second=queue.save(png,"png",jpg,"Corrupt download","Task retained");server.corrupt=true;
            failed=false;try{queue.uploadAll(api);}catch(IOException e){failed=true;}
            check(failed&&!queue.load(queue.item(second.getString("id"))).getBoolean("uploaded"),"corrupt image never submits metadata");
            check(server.rows.size()==1,"image failure did not submit second receipt");
            server.corrupt=false;server.foreign=true;failed=false;try{queue.uploadAll(api);}catch(IOException e){failed=true;}
            check(failed&&!queue.load(queue.item(second.getString("id"))).getBoolean("uploaded"),"foreign acknowledgement rejected");
            server.foreign=false;check(queue.uploadAll(api)==1,"retry after invalid acknowledgement");
            int calls=server.calls;api.close();failed=false;try{api.rpc("flandre_inbox_pull",new JSONObject());}catch(IOException e){failed=true;}
            check(failed&&server.calls==calls,"closed account does not issue requests");
            api=new CloudApi("USER_A","test","memory-only",7200,server);
            JSONObject spoof=new JSONObject(task.getJSONObject("payload").getJSONArray("images").getJSONObject(0).toString());spoof.put("key","USER_B/foreign.png");
            failed=false;try{api.objectPath(spoof,task.getString("id"));}catch(IOException e){failed=true;}check(failed,"foreign image path rejected");
            JSONObject ordered=new JSONObject().put("a",1).put("b",2),reversed=new JSONObject().put("b",2).put("a",1);
            check(CloudApi.same(ordered,reversed),"JSON comparison ignores server key ordering");
            Intent launch=new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity=startActivitySync(launch);final Activity current=activity;
            runOnMainSync(()->{
                MainActivity main=(MainActivity)current;check(findText(main.getWindow().getDecorView(),"Flandre 错题本"),"independent home rendered without login");main.loginPage();View root=current.getWindow().getDecorView();check(findText(root,"账号登录"),"login page rendered");
                List<EditText> editors=new ArrayList<>();findEditors(root,editors);check(editors.size()==2&&!editors.get(1).isSaveEnabled(),"password does not enter view-state cache");
                Bitmap bitmap=Bitmap.createBitmap(100,60,Bitmap.Config.ARGB_8888);bitmap.eraseColor(Color.WHITE);
                CropView crop=new CropView(current,bitmap);crop.layout(0,0,200,120);Bitmap canvas=Bitmap.createBitmap(200,120,Bitmap.Config.ARGB_8888);crop.draw(new Canvas(canvas));
                crop.onTouchEvent(MotionEvent.obtain(0,0,MotionEvent.ACTION_DOWN,20,20,0));crop.onTouchEvent(MotionEvent.obtain(0,10,MotionEvent.ACTION_UP,160,100,0));
                try{byte[] clipped=crop.cropped();Bitmap decoded=BitmapFactory.decodeByteArray(clipped,0,clipped.length);check(decoded.getWidth()==70&&decoded.getHeight()==40,"crop coordinates and JPEG readable");decoded.recycle();}catch(Exception e){throw new AssertionError(e);}
                bitmap.recycle();canvas.recycle();
            });
            DeepSeekChecks deepSeekChecks=new DeepSeekChecks(this);deepSeekChecks.run();deepSeekChecks.ui(activity);
            phoneUi((MainActivity)activity);
            learningPolish((MainActivity)activity);
            notebookChecks.ui(activity);
            result.putString("stream","PASS: "+passed+" Android independent notebook, sync, backup, recognition, formulas, learning and legacy queue assertions\n");
            finish(Activity.RESULT_OK,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error.toString()+"\n");finish(Activity.RESULT_CANCELED,result);}
        finally{if(activity!=null){final Activity current=activity;runOnMainSync(current::finish);}}
    }
    void screenshot(String name) throws Exception {
        waitForIdleSync();Thread.sleep(250);
        Bitmap picture=getUiAutomation().takeScreenshot();if(picture==null)throw new AssertionError("No UI screenshot");
        File directory=new File(getTargetContext().getExternalFilesDir(null),"ui-preview");directory.mkdirs();
        try(FileOutputStream out=new FileOutputStream(new File(directory,name+".png"))){picture.compress(Bitmap.CompressFormat.PNG,100,out);}finally{picture.recycle();}
    }
    void phoneUi(MainActivity main) throws Exception {
        runOnMainSync(()->{try{
            main.openWorkspace("DESIGN_"+CloudApi.id());
            main.book.save(null,new JSONObject().put("stem","已知函数在区间上连续，如何判断它的单调性？").put("subject","数学").put("is_wrong",1).put("options",new JSONObject()),null);
            main.book.save(null,new JSONObject().put("stem","阅读短文，概括作者表达的主要观点，并结合原文说明理由。").put("subject","语文").put("is_wrong",0).put("options",new JSONObject()),null);
            main.home();check(main.ui.notice.getVisibility()==View.GONE,"blank status does not reserve page space");
            main.busy=true;main.ui.nav.getChildAt(1).performClick();check(main.ui.selected.equals("home"),"tab navigation blocks workspace changes during a task");main.busy=false;
        }catch(Exception e){throw new AssertionError(e);}});
        String[] keys={"home","library","capture","learn","mine"};
        for(int i=0;i<keys.length;i++){final int index=i;runOnMainSync(()->main.ui.nav.getChildAt(index).performClick());waitForIdleSync();
            runOnMainSync(()->{check(main.ui.selected.equals(keys[index])&&main.ui.nav.getChildCount()==5&&main.ui.nav.getChildAt(index).isSelected()&&main.ui.nav.getChildAt(index).getHeight()>=main.dp(48),"native bottom navigation selects "+keys[index]+" with accessible touch target");});screenshot(keys[i]);}
        runOnMainSync(()->{main.screens.library("","","");List<EditText> edits=new ArrayList<>();findEditors(main.ui.root,edits);EditText search=edits.get(0);search.requestFocus();((android.view.inputmethod.InputMethodManager)main.getSystemService(Context.INPUT_METHOD_SERVICE)).showSoftInput(search,android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);});
        boolean keyboard=false;for(int i=0;i<30&&!keyboard;i++){final boolean[] showing={false};runOnMainSync(()->showing[0]=main.ui.ime);keyboard=showing[0];if(!keyboard)Thread.sleep(100);}
        check(keyboard,"search can open native keyboard");runOnMainSync(()->check(main.ui.nav.getVisibility()==View.GONE,"keyboard hides bottom tabs and preserves content space"));screenshot("keyboard");
        runOnMainSync(()->((android.view.inputmethod.InputMethodManager)main.getSystemService(Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(main.ui.root.getWindowToken(),0));
        boolean hidden=false;for(int i=0;i<30&&!hidden;i++){final boolean[] showing={true};runOnMainSync(()->showing[0]=main.ui.ime);hidden=!showing[0];if(!hidden)Thread.sleep(100);}
        check(hidden,"keyboard dismiss restores native content insets");runOnMainSync(()->check(main.ui.nav.getVisibility()==View.VISIBLE,"tabs return after keyboard dismiss"));
        runOnMainSync(()->main.ui.bar.getChildAt(main.ui.bar.getChildCount()-1).performClick());waitForIdleSync();screenshot("library-menu");
        android.view.accessibility.AccessibilityNodeInfo popup=getUiAutomation().getRootInActiveWindow();List<android.view.accessibility.AccessibilityNodeInfo> print=popup.findAccessibilityNodeInfosByText("打印／保存 PDF");check(!print.isEmpty()&&popup.findAccessibilityNodeInfosByText("导出 JSON").size()>0&&popup.findAccessibilityNodeInfosByText("导出 CSV").size()>0,"library toolbar exposes native export and print menu");android.view.accessibility.AccessibilityNodeInfo target=print.get(0);while(!target.isClickable()&&target.getParent()!=null)target=target.getParent();target.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK);waitForIdleSync();
        runOnMainSync(()->{check(findText(main.ui.root,"打印题目"),"print menu opens existing formula preview");main.ui.back.performClick();});
        runOnMainSync(()->{main.screens.settings();check(main.ui.nav.getVisibility()==View.GONE&&main.ui.back.getVisibility()==View.VISIBLE,"settings uses back navigation instead of root tabs");main.ui.back.performClick();check(main.ui.selected.equals("mine"),"settings back returns to mine");});
        runOnMainSync(()->{try{main.screens.newDraft(null);List<EditText> edits=new ArrayList<>();findEditors(main.ui.root,edits);edits.get(0).setText("较长的题干会自动换行；输入时保存为草稿。");main.ui.back.performClick();check(main.book.drafts().length()==1&&main.book.draft(main.book.drafts().getJSONObject(0).getString("id")).getJSONArray("questions").getJSONObject(0).getString("stem").contains("自动换行"),"toolbar back preserves autosaved editor text");}catch(Exception e){throw new AssertionError(e);}});
        runOnMainSync(()->{String words="{\"words\":[{\"word\":\"limit\",\"meaning\":\"n. 极限；界限\",\"phonetic\":\"/ˈlɪmɪt/\",\"example\":\"There is no limit to learning. 学习没有止境。\"}]}";main.book.putState("word_ai_result",words);main.screens.wordReview(words);});screenshot("word-review");
        runOnMainSync(main::home);
    }
    boolean findText(View v,String text){if(v instanceof TextView&&((TextView)v).getText().toString().equals(text))return true;if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)if(findText(g.getChildAt(i),text))return true;}return false;}
    void learningPolish(MainActivity main) throws Exception {
        NotebookChecks buttons=new NotebookChecks(this);String[] questionId=new String[1];
        runOnMainSync(()->{try{
            main.openWorkspace("POLISH_"+CloudApi.id());main.book.putState("daily_goal","15");check(main.screens.goal()==15,"daily goal is workspace scoped and saved");
            JSONObject choice=new JSONObject().put("stem","计算 $\\frac{1}{2}+\\frac{1}{2}$ 的结果。请选择正确选项。\n思考：分母相同的分数应该如何相加？").put("subject","数学").put("question_type","单选题").put("difficulty","简单").put("answer","A").put("explanation","同分母相加，分子相加：$\\frac{1+1}{2}=1$。").put("options",new JSONObject().put("A","1").put("B","2"));
            String first=main.book.save(null,choice,null),second=main.book.save(null,Notebook.copy(choice).put("question_type","解答题").put("difficulty","困难").put("source","周末试卷"),null);questionId[0]=first;String token=CloudApi.id();main.book.practiceOnce(first,"A",true,true,"mastered",7,token,null);main.book.practiceOnce(first,"A",false,false,"unknown",1,token,null);check(main.book.history(first).length()==1&&main.book.entry(first).getJSONObject("payload").getJSONObject("question").getInt("is_wrong")==1&&main.book.statistics().getInt("correct")==1,"correctness and wrong flag are independent and repeated attempt is idempotent");
            main.screens.library("","","");main.screens.kind="单选题";main.screens.difficulty="简单";check(main.screens.libraryRows().size()==1&&main.screens.libraryRows().get(0).getString("id").equals(first),"type and difficulty filters compose");main.screens.library("周末试卷","数学","");check(main.screens.libraryRows().size()==1,"library source search remains available");main.screens.library("","","");main.screens.sort="due";check(main.screens.libraryRows().get(0).getString("id").equals(first),"due sorting puts reviewed question ahead of unscheduled question");main.screens.kind="单选题";main.screens.libraryPage();check(findText(main.ui.root,"更多筛选 · 已应用"),"advanced filter state is visible");
            main.book.putState("practice_order","random");main.screens.startPractice(main.book.entries("","",""));JSONObject session=new JSONObject(main.book.state("practice",""));Set<String> ids=new HashSet<>();for(int i=0;i<session.getJSONArray("ids").length();i++)ids.add(session.getJSONArray("ids").getString(i));check(ids.size()==2&&ids.contains(first)&&ids.contains(second),"random practice freezes every matching question exactly once");List<EditText> answer=new ArrayList<>();findEditors(main.ui.root,answer);answer.get(0).setText("A");buttons.click(main.ui.root,"提交并查看答案");List<CompoundButton> toggles=new ArrayList<>();findToggles(main.ui.root,toggles);check(toggles.size()==2&&toggles.get(0).isChecked(),"choice evaluation shows automatic correct result");toggles.get(0).setChecked(false);toggles.get(1).setChecked(true);main.screens.practiceMenu();main.screens.practicePage();toggles.clear();findToggles(main.ui.root,toggles);check(!toggles.get(0).isChecked()&&toggles.get(1).isChecked(),"manual evaluation and wrong flag survive leaving practice");buttons.click(main.ui.root,"不确定 · 记录并继续");JSONObject next=new JSONObject(main.book.state("practice",""));check(next.getInt("index")==1&&!next.has("correct")&&!next.has("wrong"),"next question clears previous evaluation checkpoint");
            main.book.putState("practice_order","ordered");main.screens.startPractice(Collections.singletonList(main.book.entry(first)));
        }catch(Exception e){throw new AssertionError(e);}});Thread.sleep(500);screenshot("practice");
        runOnMainSync(()->main.screens.detail(questionId[0]));Thread.sleep(500);screenshot("reader");
        runOnMainSync(()->{try{for(int i=0;i<205;i++)main.book.word(null,"term"+i,"词义 "+i,"/tɜːm/","An example for term "+i);main.screens.wordSearch="term204";main.screens.wordFilter="due";check(main.screens.filteredWords().length()==1,"word search and due filter reach words beyond former 200 limit");main.screens.startWords(false);check(new JSONObject(main.book.state("word_session","")).getJSONArray("ids").length()==1&&!buttons.has(main.ui.root,"已掌握 · 下一词"),"word study uses filtered range and requires reveal before review");buttons.click(main.ui.root,"翻开释义");}catch(Exception e){throw new AssertionError(e);}});screenshot("word-card");
        runOnMainSync(()->{try{buttons.click(main.ui.root,"已掌握 · 下一词");check(main.book.state("word_session","missing").isEmpty()&&main.screens.filteredWords().length()==0,"completed word review leaves due range and clears session");main.screens.wordSearch="";main.screens.wordFilter="";main.screens.wordOffset=200;main.screens.wordList();check(buttons.has(main.ui.root,"上一页单词")&&!buttons.has(main.ui.root,"下一页单词"),"word pagination exposes the final page beyond 200 entries");main.screens.statistics();}catch(Exception e){throw new AssertionError(e);}});screenshot("statistics");
    }
    void findToggles(View v,List<CompoundButton> result){if(v instanceof CompoundButton)result.add((CompoundButton)v);if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)findToggles(g.getChildAt(i),result);}}
    void findEditors(View v,List<EditText> result){if(v instanceof EditText)result.add((EditText)v);if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)findEditors(g.getChildAt(i),result);}}
}
