package com.flandre.notebook;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.media.ExifInterface;
import android.net.Uri;
import android.os.*;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

public final class MainActivity extends Activity {
    private static final int PICK=10,CAMERA=11;
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    CloudApi api;
    Notebook book;
    NotebookScreens screens;
    PhotoQueue queue;
    LinearLayout page;
    PhoneUi ui;
    boolean busy=false;
    String location="home";
    long nextRegistrationCode=0;
    private String cameraName,cameraUid;
    private byte[] original;
    private String extension,sourceName;
    private CropView cropView;
    private EditText note;
    interface Job {Object run() throws Exception;}
    interface Done {void accept(Object result) throws Exception;}

    public void onCreate(Bundle saved){
        super.onCreate(saved);
        DeepSeekLogin.clear();
        ui=new PhoneUi(this);
        getWindow().setStatusBarColor(PhoneUi.BG);getWindow().setNavigationBarColor(Color.WHITE);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        if(Build.VERSION.SDK_INT>=33)getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,this::handleBack);
        if(saved!=null){cameraName=saved.getString("camera_name");cameraUid=saved.getString("camera_uid");}
        try {openWorkspace(getPreferences(0).getString("offline_uid","LOCAL"));screens=new NotebookScreens(this);home();restoreLogin();}catch(Exception e){screen("无法打开题库","请保留应用数据，不要卸载。可重新启动后再试。");}
    }
    void restoreLogin(){try{api=new CloudLoginStore(this).load(book.uid);}catch(IOException error){status(error.getMessage());}}
    protected void onSaveInstanceState(Bundle out){super.onSaveInstanceState(out);out.putString("camera_name",cameraName);out.putString("camera_uid",cameraUid);}
    int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    void screen(String title,String hint){
        ui.screen(title,hint);
    }
    TextView text(String value,int size,boolean bold){TextView t=ui.label(value,size,bold?PhoneUi.TEXT:PhoneUi.MUTED,bold);t.setLineSpacing(dp(3),1);t.setPadding(0,dp(8),0,dp(8));page.addView(t);return t;}
    EditText edit(String hint,boolean password){return ui.edit(hint,password);}
    Button button(String label,Runnable action){return ui.button(label,action);}
    Button primary(String label,Runnable action){return ui.primary(label,action);}
    void status(String s){ui.status(s);}
    void run(Job job,Done done){
        if(busy)return;busy=true;status("正在处理，请稍候……");
        executor.execute(()->{
            Object result=null;Exception error=null;try{result=job.run();}catch(Exception e){error=e;}
            final Object value=result;final Exception failure=error;
            runOnUiThread(()->{busy=false;if(isDestroyed()||isFinishing())return;try{if(failure!=null){status(failure instanceof IOException?failure.getMessage():"未能完成处理，已保存的任务会保留，请重试。");}else done.accept(value);}catch(Exception e){status("未能显示结果，已保存的任务会保留。");}});
        });
    }
    void loginPage(){
        screens.page("账号登录","登录你的学习空间，在手机和电脑继续学习。",screens::account);
        location="login";
        EditText username=edit("用户名",false),password=edit("密码",true);
        username.setText(getPreferences(0).getString("username",""));
        primary("登录",()->{
            String name=username.getText().toString().trim(),secret=password.getText().toString();password.setText("");
            if(name.isEmpty()||secret.isEmpty()){status("请填写用户名和密码。");return;}
            final String deviceId=cloudDevice();run(()->CloudApi.login(name,secret,deviceId),value->acceptAccount((CloudApi)value,name));
        });
        button("没有账号？注册新账号",this::registerPage);
        button("返回题库",this::home);
        text("密码不保存。系统加密保存登录状态，重启后仍可同步；退出账号会清除登录状态，本地题库保留。",13,false);
    }
    String cloudDevice(){String device=getPreferences(0).getString("device","");if(device.isEmpty()){device=CloudApi.id();getPreferences(0).edit().putString("device",device).apply();}return device;}
    void acceptAccount(CloudApi signed,String name) throws IOException {
        try{openWorkspace(signed.uid);}catch(Exception error){signed.close();throw new IOException("账号已认证，但题库未能打开。原本机题库保留，请重新登录。");}if(api!=null)api.close();api=signed;
        getPreferences(0).edit().putString("username",name).putString("offline_uid",api.uid).commit();
        api.store=new CloudLoginStore(this);home();try{api.store.save(api);}catch(IOException error){status(error.getMessage());}
    }
    void registerPage(){
        screens.page("注册账号","验证邮箱后，在手机和电脑使用同一用户名登录。",this::loginPage);location="registration";
        text("邮箱",14,true);EditText email=edit("接收验证码的邮箱",false);email.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS);email.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(254)});
        final CloudApi.EmailChallenge[] challenge={null};
        Button send=button("发送邮箱验证码",()->{
            long now=SystemClock.elapsedRealtime();if(now<nextRegistrationCode){status("请等待 "+((nextRegistrationCode-now+999)/1000)+" 秒后再发送。");return;}
            final String address;try{address=CloudApi.registrationFields(email.getText().toString(),null,null);}catch(IOException error){status(error.getMessage());return;}
            challenge[0]=null;nextRegistrationCode=now+60000;final String device=cloudDevice();
            run(()->CloudApi.sendRegistrationCode(address,device),value->{challenge[0]=(CloudApi.EmailChallenge)value;status("验证码已发送，请检查收件箱和垃圾邮件。修改邮箱后需重新发送。");});
        });
        // A monotonic cooldown also survives switching between login and registration pages.
        Handler timer=new Handler(Looper.getMainLooper());timer.postDelayed(new Runnable(){public void run(){if(isDestroyed()||!send.isAttachedToWindow())return;long remaining=nextRegistrationCode-SystemClock.elapsedRealtime();send.setText(remaining>0?((remaining+999)/1000)+" 秒后可重新发送":"发送邮箱验证码");timer.postDelayed(this,1000);}},100);
        text("邮箱验证码",14,true);EditText code=edit("邮件中的 6 位数字",false);code.setInputType(InputType.TYPE_CLASS_NUMBER);code.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(6)});code.setSaveEnabled(false);code.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        text("用户名",14,true);EditText username=edit("5～24 位字母、数字、_ 或 -",false);username.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(24)});
        text("密码",14,true);EditText password=edit("8～32 位，含字母和数字",true);
        text("确认密码",14,true);EditText confirm=edit("再次输入密码",true);
        primary("注册并进入题库",()->{
            String address=email.getText().toString().trim(),name=username.getText().toString().trim(),secret=password.getText().toString(),verification=code.getText().toString().trim();
            try{CloudApi.registrationFields(address,name,secret);if(!secret.equals(confirm.getText().toString()))throw new IOException("两次密码不一致。");if(challenge[0]==null)throw new IOException("请先发送邮箱验证码。");}catch(IOException error){status(error.getMessage());return;}
            password.setText("");confirm.setText("");code.setText("");CloudApi.EmailChallenge current=challenge[0];final String device=cloudDevice();run(()->current.signup(address,name,secret,verification,device),value->acceptAccount((CloudApi)value,name));
        });
        button("已有账号？返回登录",this::loginPage);
        text("密码和验证码不保存。系统加密保存登录状态。注册不会自动上传本机题库；登录后可选择导入和同步。",13,false);
    }
    void openWorkspace(String uid) throws Exception {
        PhotoQueue nextQueue=new PhotoQueue(new File(getFilesDir(),uid.equals("LOCAL")?"local":"accounts"),uid);Notebook next=new Notebook(nextQueue.root,uid);if(book!=null)book.close();queue=nextQueue;book=next;
    }
    void home(){location="home";screens.home();}
    void pick(){try{Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("image/*").addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,PICK);}catch(ActivityNotFoundException e){status("此设备没有图片选择器。");}}
    void camera(){
        cameraName=CloudApi.id()+".jpg";cameraUid=book.uid;
        Uri uri=Uri.parse("content://com.flandre.notebook.capture/"+cameraName);
        Intent i=new Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT,uri)
            .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);
        i.setClipData(ClipData.newRawUri("camera",uri));
        try{startActivityForResult(i,CAMERA);}catch(ActivityNotFoundException e){status("此设备没有可用的相机应用。");cameraName=null;cameraUid=null;}
    }
    protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);
        if(screens!=null&&screens.result(request,result,data))return;
        if(result!=RESULT_OK){if(request==CAMERA)cleanupCamera();return;}
        if(book==null){if(request==CAMERA)cleanupCamera();return;}
        if(request==PICK&&data!=null&&data.getData()!=null)loadPhoto(data.getData(),"相册题目");
        if(request==CAMERA&&cameraName!=null){
            if(!book.uid.equals(cameraUid)){cleanupCamera();status("拍照期间账号发生变化，请重新拍照。");return;}
            loadPhoto(Uri.parse("content://com.flandre.notebook.capture/"+cameraName),"拍照题目");
        }
    }
    void cleanupCamera(){if(cameraName!=null&&cameraName.matches("[a-f0-9]{32}\\.jpg"))new File(new File(getCacheDir(),"captures"),cameraName).delete();cameraName=null;cameraUid=null;}
    void clearPhoto(){original=null;if(cropView!=null){cropView.bitmap.recycle();cropView=null;}}
    void loadPhoto(Uri uri,String name){
        run(()->{
            byte[] bytes;try(InputStream in=getContentResolver().openInputStream(uri);ByteArrayOutputStream out=new ByteArrayOutputStream()){
                if(in==null)throw new IOException("无法读取这张照片。");byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){if(out.size()+n>CloudApi.MAX_IMAGE)throw new IOException("原图超过 20 MB，请先缩小图片。");out.write(b,0,n);}bytes=out.toByteArray();
            }
            BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(bytes,0,bytes.length,bounds);
            if(bounds.outWidth<=0||bounds.outHeight<=0||!Arrays.asList("image/jpeg","image/png","image/webp").contains(bounds.outMimeType))throw new IOException("请选择 PNG、JPG 或 WEBP 图片。");
            int sample=1;while(Math.max(bounds.outWidth,bounds.outHeight)/sample>2048)sample*=2;
            BitmapFactory.Options options=new BitmapFactory.Options();options.inSampleSize=sample;Bitmap bitmap=BitmapFactory.decodeByteArray(bytes,0,bytes.length,options);
            if(bitmap==null)throw new IOException("照片无法解码。");
            int orientation=1;try{ExifInterface exif=new ExifInterface(new ByteArrayInputStream(bytes));orientation=exif.getAttributeInt(ExifInterface.TAG_ORIENTATION,1);}catch(IOException ignored){}
            Matrix matrix=new Matrix();
            switch(orientation){case 2:matrix.setScale(-1,1);break;case 3:matrix.setRotate(180);break;case 4:matrix.setScale(1,-1);break;case 5:matrix.setRotate(90);matrix.postScale(-1,1);break;case 6:matrix.setRotate(90);break;case 7:matrix.setRotate(270);matrix.postScale(-1,1);break;case 8:matrix.setRotate(270);break;}
            if(!matrix.isIdentity()){Bitmap rotated=Bitmap.createBitmap(bitmap,0,0,bitmap.getWidth(),bitmap.getHeight(),matrix,true);if(rotated!=bitmap){bitmap.recycle();bitmap=rotated;}}
            return new Object[]{bytes,bitmap,bounds.outMimeType.equals("image/png")?"png":bounds.outMimeType.equals("image/webp")?"webp":"jpg"};
        },value->{
            cleanupCamera();clearPhoto();Object[] values=(Object[])value;original=(byte[])values[0];extension=(String)values[2];sourceName=name+"-"+new java.text.SimpleDateFormat("MMdd-HHmmss",Locale.CHINA).format(new Date());
            location="photo";
            screen("框选题目","在图片上拖动框选题目区域。原始照片会完整保留；手机可以识题、核对并直接收录。");
            cropView=new CropView(this,(Bitmap)values[1]);page.addView(cropView,new LinearLayout.LayoutParams(-1,dp(360)));
            button("恢复整张图片",()->cropView.reset());note=edit("备注（可选，如数学卷第 4 题）",false);note.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(1000)});
            primary("在手机识题并整理",()->{
                try {byte[] crop=cropView.cropped(),bytes=original;String comment=note.getText().toString(),photoName=sourceName,ext=extension;Notebook owner=book;
                    run(()->screens.photoDraft(owner,bytes,ext,crop,photoName,comment),r->{clearPhoto();screens.draftPage((String)r);});
                }catch(Exception e){status("无法保存照片草稿，请重试。");}
            });
            button("发送给电脑整理（可选）",()->{
                if(api==null){status("发送给电脑需先登录账号；现在可以选择在手机识题并整理。");return;}
                try {byte[] crop=cropView.cropped(),bytes=original;String comment=note.getText().toString();PhotoQueue owner=queue;
                    run(()->owner.save(bytes,extension,crop,sourceName,comment),r->{clearPhoto();queuePage();status("已保存在此账号的手机队列，联网后点击上传。");});
                }catch(Exception e){status("无法保存裁剪图，请重试。");}
            });
            button("返回",()->{clearPhoto();home();});
        });
    }
    void queuePage(){
        location="queue";
        screen("发送给电脑的照片","当前空间："+screens.workspaceName()+"\n照片队列保留；也可在手机独立识题整理。");
        button("上传全部待传图片",()->{
            if(api==null){status("发送照片需登录同一账号。手机本地识题和学习无需登录。");return;}CloudApi client=api;PhotoQueue owner=queue;run(()->owner.uploadAll(client),result->{queuePage();status("本轮已上传 "+result+" 张；可在电脑“手机待整理”中接收。");});
        });
        button("刷新电脑处理状态",()->{if(api==null){status("请先登录后刷新云端状态。");return;}CloudApi client=api;run(()->pullInbox(client),r->{queuePage();status("已更新电脑处理状态。");});});
        button("返回拍题",this::home);
        JSONObject states=new JSONObject();try{File f=new File(queue.root,"inbox-status.json");if(f.exists())states=new JSONObject(new String(CloudApi.read(f,2*1024*1024),StandardCharsets.UTF_8));}catch(Exception ignored){}
        int count=0;for(File dir:queue.tasks()){
            try {JSONObject task=queue.load(dir);String state=task.optBoolean("uploaded")?states.optString(task.getString("id"),"pending"):"local";
                String label=state.equals("local")?"待上传":state.equals("processed")?"电脑已收录":state.equals("dismissed")?"已略过":"已上传 · 待电脑整理";
                text(task.getJSONObject("payload").getString("source_name")+"\n"+label,16,true);count++;
            }catch(Exception e){text("有一项任务无法读取，请保留应用数据。",14,false);}
        }
        if(count==0)text("还没有照片。先拍下或选择一道错题。",16,false);
    }
    Object pullInbox(CloudApi client) throws Exception {
        JSONObject states=new JSONObject();long cursor=0;
        for(int page=0;page<100;page++){
            JSONObject result=client.rpc("flandre_inbox_pull",new JSONObject().put("p_after",cursor).put("p_limit",50));JSONArray rows=result.getJSONArray("records");
            if(rows.length()>50)throw new IOException("分页响应无效。");
            for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if(!client.uid.equals(row.optString("user_id"))||row.getLong("seq")<=cursor)throw new IOException("记录不属于当前账号或顺序无效。");cursor=row.getLong("seq");states.put(row.getString("id").replace("-",""),row.getString("status"));}
            if(result.getLong("cursor")!=cursor)throw new IOException("分页进度无效。");
            if(rows.length()<50){PhotoQueue.atomic(new File(queue.root,"inbox-status.json"),states.toString().getBytes(StandardCharsets.UTF_8));return states;}
        }throw new IOException("任务较多，本轮尚未更新完整状态。");
    }
    void questionPage(){screens.library("","","");}
    void handleBack(){
        if(busy){status("正在处理，请稍候。已保存的任务会保留。");return;}
        if(location.equals("home")){finish();return;}
        if(!location.equals("photo")){screens.back();return;}
        if(location.equals("photo")){new AlertDialog.Builder(this).setTitle("照片还未保存")
            .setMessage("返回拍题页会舍弃本次选择，已保存的队列不受影响。")
            .setNegativeButton("继续编辑",null).setPositiveButton("返回",(dialog,which)->{clearPhoto();home();}).show();return;}
        clearPhoto();home();
    }
    public void onBackPressed(){handleBack();}
    protected void onDestroy(){super.onDestroy();if(screens!=null)screens.close();CloudApi session=api;Notebook current=book;executor.execute(()->{if(session!=null)session.close();if(current!=null)current.close();});executor.shutdown();}
}
