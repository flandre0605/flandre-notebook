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
    int passed=0;String restartMode="";
    void check(boolean value,String label){if(!value)throw new AssertionError(label);passed++;}
    public void onCreate(Bundle args){super.onCreate(args);restartMode=args==null?"":args.getString("session_restart","");start();}
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
            if(!restartMode.isEmpty()){restartSession();result.putString("stream","PASS: Android process restart "+restartMode+" ("+passed+" checks)\n");finish(Activity.RESULT_OK,result);return;}
            registration();sessions();
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
            libraryFormulaCards((MainActivity)activity);
            registrationUi((MainActivity)activity);sessionUi((MainActivity)activity);
            emptyProductUi((MainActivity)activity);
            notebookChecks.ui(activity);
            result.putString("stream","PASS: "+passed+" Android independent notebook, sync, backup, recognition, formulas, learning and legacy queue assertions\n");
            finish(Activity.RESULT_OK,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error.toString()+"\n");finish(Activity.RESULT_CANCELED,result);}
        finally{if(activity!=null){final Activity current=activity;runOnMainSync(current::finish);}}
    }
    void restartSession() throws Exception {
        MainActivity main=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        runOnMainSync(()->{try{
            if(restartMode.equals("write")){
                CloudApi api=new CloudApi("RESTART_CHECK","restart","ACCESS_RESTART",7200,(p,m,b,t,k,d,l)->{throw new IOException("no network");});api.refresh="REFRESH_RESTART";api.device="device";main.acceptAccount(api,"restart");
                check(main.api.uid.equals("RESTART_CHECK"),"authenticated account saved before process stop");
            }else{
                check(main.api!=null&&main.api.uid.equals("RESTART_CHECK")&&main.book.uid.equals(main.api.uid)&&main.api.refresh.equals("REFRESH_RESTART"),"new process restores login into correct account without network");
                main.screens.account();new NotebookChecks(this).click(main.ui.root,"退出账号，回到本机空间");check(main.api==null&&new CloudLoginStore(main).load("RESTART_CHECK")==null,"explicit logout after process restart clears secure login");
            }
            main.finish();
        }catch(Exception e){throw new AssertionError(e);}});
    }
    void sessions() throws Exception {
        Context context=getTargetContext();android.content.SharedPreferences prefs=context.getSharedPreferences("cloud-login",0);Map<String,?> original=new HashMap<>(prefs.getAll());
        CloudLoginStore store=new CloudLoginStore(context);final int[] refreshes={0},calls={0},status={200};final String[] mode={"ok"};
        CloudApi.Transport transport=(path,method,body,mime,token,device,limit)->{
            try{
                if(path.equals("/auth/v1/token")){
                    refreshes[0]++;JSONObject args=new JSONObject(new String(body,StandardCharsets.UTF_8));
                    check(args.getString("grant_type").equals("refresh_token")&&args.getString("refresh_token").startsWith("REFRESH_")&&device.equals("device")&&token==null,"refresh uses ordinary device-bound protocol");
                    if(mode[0].equals("offline"))throw new IOException("offline");
                    if(mode[0].equals("revoked"))return new CloudApi.Reply(400,"{\"error\":\"invalid_grant\"}".getBytes(StandardCharsets.UTF_8));
                    return new CloudApi.Reply(200,new JSONObject().put("sub",mode[0].equals("foreign")?"OTHER_USER":"SESSION_CHECK").put("token_type","Bearer").put("access_token","ACCESS_NEW").put("refresh_token","REFRESH_NEW").put("expires_in",7200).toString().getBytes(StandardCharsets.UTF_8));
                }
                calls[0]++;return new CloudApi.Reply(status[0]==401&&token.equals("ACCESS_NEW")?200:status[0],new byte[0]);
            }catch(JSONException e){throw new IOException("synthetic JSON");}
        };
        try {
            CloudApi api=new CloudApi("SESSION_CHECK","test","ACCESS_OLD",7200,transport);api.refresh="REFRESH_OLD";api.device="device";api.store=store;store.save(api);
            check(!prefs.getString("session","").contains("REFRESH_OLD")&&!prefs.getString("session","").contains("ACCESS_OLD"),"only encrypted refresh saved");
            api.close();CloudApi restored=store.load("SESSION_CHECK");check(restored!=null&&restored.refresh.equals("REFRESH_OLD")&&restored.device.equals("device"),"process memory loss restores secure login");check(store.load("OTHER_USER")==null,"saved login cannot attach to another workspace");restored.close();
            api=new CloudApi("SESSION_CHECK","test","ACCESS_OLD",0,transport);api.refresh="REFRESH_OLD";api.device="device";api.store=store;
            check(api.bearer().equals("ACCESS_NEW")&&refreshes[0]==1,"expired access automatically refreshes");api.bearer();check(refreshes[0]==1,"valid access does not refresh repeatedly");check(store.load("SESSION_CHECK").refresh.equals("REFRESH_NEW"),"rotated refresh persists before next restart");
            api.logout();check(store.load("SESSION_CHECK")==null,"explicit logout clears saved session");
            api=new CloudApi("SESSION_CHECK","test","ACCESS_OLD",7200,transport);api.refresh="REFRESH_OLD";api.device="device";api.store=store;status[0]=401;
            check(api.authenticated("/test","POST",new byte[]{1},"application/json",100).code==200&&calls[0]==2&&refreshes[0]==2,"401 renews and retries once");
            status[0]=403;int before=refreshes[0];check(api.authenticated("/test","GET",null,"application/json",100).code==403&&refreshes[0]==before&&calls[0]==3,"403 permission denial never refreshes or retries");
            api.expires=0;mode[0]="offline";boolean failed=false;try{api.bearer();}catch(IOException e){failed=true;}check(failed&&api.refresh.equals("REFRESH_NEW")&&store.load("SESSION_CHECK")!=null,"network outage preserves secure login");
            mode[0]="revoked";failed=false;try{api.bearer();}catch(IOException e){failed=true;}check(failed&&api.refresh.isEmpty()&&store.load("SESSION_CHECK")==null,"revocation clears login without notebook deletion");
            api=new CloudApi("SESSION_CHECK","test","ACCESS_OLD",0,transport);api.refresh="REFRESH_OLD";api.device="device";api.store=store;store.save(api);mode[0]="foreign";failed=false;try{api.bearer();}catch(IOException e){failed=true;}check(failed&&api.refresh.isEmpty()&&store.load("SESSION_CHECK")==null,"renewal identity mismatch cannot switch accounts");
            api=new CloudApi("SESSION_CHECK","test","ACCESS_OLD",7200,transport);api.refresh="REFRESH_OLD";api.device="device";store.save(api);String sealed=prefs.getString("session","");prefs.edit().putString("uid","OTHER_USER").commit();failed=false;try{store.load("OTHER_USER");}catch(IOException e){failed=true;}check(failed,"ciphertext is cryptographically bound to the original account");
        } finally {android.content.SharedPreferences.Editor editor=prefs.edit().clear();for(Map.Entry<String,?> item:original.entrySet())editor.putString(item.getKey(),(String)item.getValue());editor.commit();}
    }
    void sessionUi(MainActivity main) throws Exception {
        runOnMainSync(()->{try{
            CloudApi api=new CloudApi("UI_SESSION","test","ACCESS",7200,(p,m,b,t,k,d,l)->{throw new IOException("no network");});api.refresh="REFRESH_UI";api.device="device";main.acceptAccount(api,"test");api.close();main.api=null;main.restoreLogin();
            check(main.api!=null&&main.api.uid.equals(main.book.uid)&&main.api.refresh.equals("REFRESH_UI"),"activity startup restores login into the same offline account");
            main.screens.account();check(findText(main.getWindow().getDecorView(),"登录状态已安全保存，同步时自动续期；断网仍可学习。"),"remembered login is visible in account page");new NotebookChecks(this).click(main.ui.root,"退出账号，回到本机空间");
            check(main.api==null&&main.book.uid.equals("LOCAL")&&new CloudLoginStore(main).load("UI_SESSION")==null,"account exit clears saved login and returns to local notebook");
        }catch(Exception error){throw new AssertionError(error);}});
    }
    void registration() throws Exception {
        List<String> paths=new ArrayList<>();List<JSONObject> bodies=new ArrayList<>();Deque<JSONObject> replies=new ArrayDeque<>();
        replies.add(new JSONObject().put("verification_id","email-bound").put("expires_in",600));replies.add(new JSONObject().put("verification_token","verified-email").put("expires_in",600));replies.add(new JSONObject().put("sub","NEW_USER").put("token_type","Bearer").put("access_token","memory-only").put("refresh_token","discarded").put("expires_in",7200));
        CloudApi.Transport transport=(path,method,body,mime,token,device,limit)->{try{check(method.equals("POST")&&token==null&&device.equals("device")&&limit==128*1024,"registration uses ordinary fixed-host requests without admin credential");paths.add(path);bodies.add(new JSONObject(new String(body,StandardCharsets.UTF_8)));return new CloudApi.Reply(200,replies.remove().toString().getBytes(StandardCharsets.UTF_8));}catch(JSONException e){throw new AssertionError(e);}};
        CloudApi.EmailChallenge challenge=CloudApi.sendRegistrationCode(" test@example.com ","device",transport);
        boolean failed=false;try{challenge.signup("other@example.com","new_user","Password123!","123456","device");}catch(IOException e){failed=true;}check(failed&&paths.size()==1,"verification is bound to the exact email");
        failed=false;try{challenge.signup(challenge.email,"new_user","Password123!","abc123","device");}catch(IOException e){failed=true;}check(failed&&paths.size()==1,"invalid verification code cannot reach network");
        CloudApi session=challenge.signup(challenge.email,"new_user","Password123!","123456","device");check(session.uid.equals("NEW_USER")&&session.username.equals("new_user")&&session.bearer().equals("memory-only"),"registered account reuses normal sync session");session.close();
        check(paths.equals(Arrays.asList("/auth/v1/verification","/auth/v1/verification/verify","/auth/v1/signup"))&&bodies.get(0).getString("target").equals("ANY")&&bodies.get(1).getString("verification_id").equals("email-bound")&&bodies.get(2).getString("verification_token").equals("verified-email")&&bodies.get(2).getString("username").equals("new_user"),"send verify signup protocol preserves verified identity");
        failed=false;try{challenge.signup(challenge.email,"new_user","Password123!","123456","device");}catch(IOException e){failed=true;}check(failed&&paths.size()==3,"consumed verification cannot repeat signup");
        for(String[] invalid:new String[][]{{"bad-email","new_user","Password123!"},{"test@example.com","ab","Password123!"},{"test@example.com","new_user","password"}}){failed=false;try{CloudApi.registrationFields(invalid[0],invalid[1],invalid[2]);}catch(IOException e){failed=true;}check(failed,"registration validates untrusted fields");}
        for(String error:new String[]{"rate_limit_exceeded","captcha_required","unimplemented","username_exists","invalid_verification_code"}){JSONObject response=new JSONObject().put("error",error).put("error_description","SECRET_PASSWORD");failed=false;try{CloudApi.sendRegistrationCode("test@example.com","device",(p,m,b,type,t,d,l)->new CloudApi.Reply(400,response.toString().getBytes(StandardCharsets.UTF_8)));}catch(IOException e){failed=!e.getMessage().contains("SECRET");}check(failed,"registration error stays safe: "+error);}
        CloudApi.EmailChallenge expired=new CloudApi.EmailChallenge("test@example.com",new JSONObject().put("verification_id","expired").put("expires_in",1),transport);Thread.sleep(1100);failed=false;try{expired.signup(expired.email,"new_user","Password123!","123456","device");}catch(IOException e){failed=true;}check(failed&&paths.size()==3,"expired verification never reaches network");
    }
    void registrationUi(MainActivity main) throws Exception {
        NotebookChecks buttons=new NotebookChecks(this);runOnMainSync(()->{
            main.loginPage();buttons.click(main.ui.root,"没有账号？注册新账号");check(main.location.equals("registration")&&findText(main.ui.root,"邮箱验证码"),"phone login exposes email registration");List<EditText> fields=new ArrayList<>();findEditors(main.ui.root,fields);check(fields.size()==5&&!fields.get(1).isSaveEnabled()&&!fields.get(3).isSaveEnabled()&&!fields.get(4).isSaveEnabled(),"registration secrets are excluded from Android view restoration");fields.get(0).setText("test@example.com");fields.get(2).setText("new_user");fields.get(3).setText("Password123!");fields.get(4).setText("different");buttons.click(main.ui.root,"注册并进入题库");check(!main.busy&&main.ui.message.getText().toString().contains("不一致"),"registration refuses mismatched passwords before network");main.nextRegistrationCode=android.os.SystemClock.elapsedRealtime()+60000;buttons.click(main.ui.root,"发送邮箱验证码");check(!main.busy&&main.ui.message.getText().toString().contains("请等待"),"phone verification cooldown prevents duplicate sends");main.busy=true;buttons.click(main.ui.root,"已有账号？返回登录");check(main.location.equals("registration"),"registration stays put during an account request");main.busy=false;main.registerPage();
        });screenshot("registration");runOnMainSync(()->{main.nextRegistrationCode=0;main.ui.back.performClick();check(main.location.equals("login"),"registration back returns to sign-in");main.ui.back.performClick();check(findText(main.ui.root,"账号与同步"),"sign-in back returns to account controls");});
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
    void emptyProductUi(MainActivity main) throws Exception {
        runOnMainSync(()->{try{
            main.api=null;main.openWorkspace("LOCAL");main.home();
            check(!main.isFinishing()&&main.ui.root.isAttachedToWindow(),"product screenshots capture the live application");
            check(main.book.entries("","","").isEmpty()&&main.book.words().length()==0&&main.book.drafts().length()==0&&main.book.statistics().getInt("today")==0,"fresh product workspace contains no seeded study data");
            check(!findText(main.ui.root,"继续整理草稿")&&!findText(main.ui.root,"继续上次练习"),"empty home never fabricates pending tasks");
        }catch(Exception e){throw new AssertionError(e);}});screenshot("product-home-empty");
        runOnMainSync(()->{main.screens.library("","","");check(findText(main.ui.root,"还没有收录题目")&&main.screens.formulas.isEmpty(),"empty library offers own content without demo cards");});screenshot("product-library-empty");
        runOnMainSync(()->{main.screens.mine();check(!findText(main.ui.root,"部署")&&!findText(main.ui.root,"示例词"),"account surface has no deployment or sample entry");});screenshot("product-mine-empty");
        runOnMainSync(()->main.screens.settings());screenshot("product-settings-empty");
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
    void libraryFormulaCards(MainActivity main) throws Exception {
        final FormulaView[] preview=new FormulaView[1];final View[] hit=new View[1];String stem="4、计算极限 $\\lim_{x\\to a+0}\\frac{\\sqrt{x}-\\sqrt{a}+\\sqrt{x-a}}{\\sqrt{x^2-a^2}}\\quad(a\\ge0)$";
        runOnMainSync(()->{try{main.openWorkspace("CARDS_"+CloudApi.id());String id=main.book.save(null,new JSONObject().put("stem",stem).put("subject","数学").put("is_wrong",1),null);main.book.practice(id,"",false,"unknown",1);main.screens.library("","","");check(main.screens.formulas.size()==1,"library routes formula stems to shared offline renderer");preview[0]=main.screens.formulas.get(0);hit[0]=preview[0];check(findText(main.ui.root,"错题")&&findText(main.ui.root,"数学")&&findText(main.ui.root,"未掌握"),"question metadata appears as separate readable badges");main.ui.scroll.post(()->main.ui.scroll.smoothScrollTo(0,main.dp(320)));}catch(Exception e){throw new AssertionError(e);}});
        boolean rendered=false;for(int i=0;i<80&&!rendered;i++){java.util.concurrent.CountDownLatch latch=new java.util.concurrent.CountDownLatch(1);final String[] result=new String[1];runOnMainSync(()->preview[0].evaluateJavascript("document.documentElement.dataset.ready==='1' && !!document.querySelector('.katex .mfrac') && !!document.querySelector('.katex .sqrt') && document.querySelector('.katex-html').scrollWidth <= document.getElementById('content').clientWidth+2",v->{result[0]=v;latch.countDown();}));if(!latch.await(2,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("card formula callback timeout");rendered="true".equals(result[0]);if(!rendered)Thread.sleep(100);}check(rendered,"reported limit previews with real fractions and radicals fitting the card width");Thread.sleep(450);screenshot("library-formula");
        runOnMainSync(()->{check(preview[0].getHeight()>main.dp(48)&&preview[0].getHeight()<=main.dp(240)&&((View)preview[0].getParent()).getHeight()<=preview[0].getHeight()+main.dp(150),"formula card height is bounded and footer remains outside preview");main.busy=true;hit[0].performClick();check(main.ui.selected.equals("library"),"formula hit area observes busy navigation guard");main.busy=false;hit[0].performClick();check(findText(main.ui.root,"题目详情")&&preview[0].disposed,"tapping the rendered formula opens details and destroys the old preview");});
        final FormulaView[] old=new FormulaView[1];runOnMainSync(()->{try{for(int i=0;i<13;i++)main.book.save(null,new JSONObject().put("stem",stem+"\n测试 "+i).put("subject","数学"),null);main.screens.library("","","");check(main.screens.formulas.size()==NotebookScreens.LIBRARY_PAGE_SIZE,"formula list caps live renderers per page");old[0]=main.screens.formulas.get(0);new NotebookChecks(this).click(main.ui.root,"下一页");check(main.screens.libraryOffset==NotebookScreens.LIBRARY_PAGE_SIZE&&main.screens.formulas.size()==2&&old[0].disposed,"next page shows remaining cards and disposes old renderers");main.screens.home();check(main.screens.formulas.isEmpty(),"leaving library releases all card renderers");}catch(Exception e){throw new AssertionError(e);}});
    }
    void findEditors(View v,List<EditText> result){if(v instanceof EditText)result.add((EditText)v);if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)findEditors(g.getChildAt(i),result);}}
}
