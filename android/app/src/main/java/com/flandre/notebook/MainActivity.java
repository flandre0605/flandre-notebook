package com.flandre.notebook;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
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
    private CloudApi api;
    private PhotoQueue queue;
    private LinearLayout page;
    private TextView message;
    private boolean busy=false;
    private String location="login";
    private String cameraName,cameraUid;
    private byte[] original;
    private String extension,sourceName;
    private CropView cropView;
    private EditText note;
    private final int accent=0xffae426f;
    interface Job {Object run() throws Exception;}
    interface Done {void accept(Object result) throws Exception;}

    public void onCreate(Bundle saved){
        super.onCreate(saved);
        getWindow().setStatusBarColor(0xfffcf4f8);getWindow().setNavigationBarColor(0xfffcf4f8);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        if(Build.VERSION.SDK_INT>=33)getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,this::handleBack);
        if(saved!=null){cameraName=saved.getString("camera_name");cameraUid=saved.getString("camera_uid");}
        loginPage();
    }
    protected void onSaveInstanceState(Bundle out){super.onSaveInstanceState(out);out.putString("camera_name",cameraName);out.putString("camera_uid",cameraUid);}
    int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    void screen(String title,String hint){
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setBackgroundColor(0xfffcf4f8);
        page=new LinearLayout(this);page.setOrientation(LinearLayout.VERTICAL);page.setPadding(dp(24),dp(18),dp(24),dp(24));scroll.addView(page);
        scroll.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;});
        setContentView(scroll);scroll.requestApplyInsets();text(title,27,true);text(hint,14,false);
        message=text("",14,false);message.setTextColor(accent);
    }
    TextView text(String value,int size,boolean bold){TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(0xff322b39);if(bold)t.setTypeface(null,Typeface.BOLD);t.setPadding(0,dp(9),0,dp(9));page.addView(t);return t;}
    EditText edit(String hint,boolean password){EditText e=new EditText(this);e.setHint(hint);e.setSingleLine(true);e.setTextSize(16);if(password){e.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);e.setSaveEnabled(false);e.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);}page.addView(e,new LinearLayout.LayoutParams(-1,dp(56)));return e;}
    Button button(String label,Runnable action){Button b=new Button(this);b.setText(label);b.setTextSize(15);b.setAllCaps(false);b.setTextColor(accent);GradientDrawable bg=new GradientDrawable();bg.setColor(Color.WHITE);bg.setCornerRadius(dp(14));bg.setStroke(dp(1),0xffe5c4d3);b.setBackground(bg);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(52));p.topMargin=dp(10);page.addView(b,p);b.setOnClickListener(v->{if(!busy)action.run();});return b;}
    void status(String s){message.setText(s);}
    void run(Job job,Done done){
        if(busy)return;busy=true;status("正在处理，请稍候……");
        executor.execute(()->{
            Object result=null;Exception error=null;try{result=job.run();}catch(Exception e){error=e;}
            final Object value=result;final Exception failure=error;
            runOnUiThread(()->{busy=false;if(isDestroyed()||isFinishing())return;try{if(failure!=null){status(failure instanceof IOException?failure.getMessage():"未能完成处理，已保存的任务会保留，请重试。");}else done.accept(value);}catch(Exception e){status("未能显示结果，已保存的任务会保留。");}});
        });
    }
    void loginPage(){
        location="login";
        screen("Flandre 拍题","纸上做题，手机拍照，电脑整理。\n使用和电脑端相同的账号登录。");
        EditText username=edit("用户名",false),password=edit("密码",true);
        username.setText(getPreferences(0).getString("username",""));
        button("登录",()->{
            String name=username.getText().toString().trim(),secret=password.getText().toString();password.setText("");
            if(name.isEmpty()||secret.isEmpty()){status("请填写用户名和密码。");return;}
            String device=getPreferences(0).getString("device","");if(device.isEmpty()){device=CloudApi.id();getPreferences(0).edit().putString("device",device).apply();}
            final String deviceId=device;run(()->CloudApi.login(name,secret,deviceId),value->{
                if(api!=null)api.close();api=(CloudApi)value;queue=new PhotoQueue(new File(getFilesDir(),"accounts"),api.uid);
                getPreferences(0).edit().putString("username",name).apply();home();
            });
        });
        text("密码和登录凭据只在本次运行中使用。退出后重新登录；已保存的图片按账号分别保留在手机。",13,false);
    }
    void home(){
        location="home";
        screen("拍下今天的错题","当前账号："+api.username+"\n选择照片后拖动框选题目，再保存到上传队列。");
        button("拍照",this::camera);button("从相册选图",this::pick);
        button("上传队列",this::queuePage);button("查看电脑整理的题目",this::questionPage);
        button("退出账号",()->{api.close();api=null;queue=null;clearPhoto();loginPage();});
        text("首次使用需在电脑端执行手机待整理部署脚本 005。上传后，电脑打开“手机待整理”接收。",13,false);
    }
    void pick(){try{Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("image/*").addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,PICK);}catch(ActivityNotFoundException e){status("此设备没有图片选择器。");}}
    void camera(){
        cameraName=CloudApi.id()+".jpg";cameraUid=api.uid;
        Uri uri=Uri.parse("content://com.flandre.notebook.capture/"+cameraName);
        Intent i=new Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT,uri)
            .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);
        i.setClipData(ClipData.newRawUri("camera",uri));
        try{startActivityForResult(i,CAMERA);}catch(ActivityNotFoundException e){status("此设备没有可用的相机应用。");cameraName=null;cameraUid=null;}
    }
    protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);
        if(result!=RESULT_OK){if(request==CAMERA)cleanupCamera();return;}
        if(api==null){if(request==CAMERA)cleanupCamera();status("请先重新登录，再选择照片。");return;}
        if(request==PICK&&data!=null&&data.getData()!=null)loadPhoto(data.getData(),"相册题目");
        if(request==CAMERA&&cameraName!=null){
            if(!api.uid.equals(cameraUid)){cleanupCamera();status("拍照期间账号发生变化，请重新拍照。");return;}
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
            screen("框选题目","在图片上拖动框选题目区域。原始照片会完整保留，裁剪图用于电脑识题。");
            cropView=new CropView(this,(Bitmap)values[1]);page.addView(cropView,new LinearLayout.LayoutParams(-1,dp(360)));
            button("恢复整张图片",()->cropView.reset());note=edit("备注（可选，如数学卷第 4 题）",false);note.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(1000)});
            button("保存到上传队列",()->{
                try {byte[] crop=cropView.cropped(),bytes=original;String comment=note.getText().toString();PhotoQueue owner=queue;
                    run(()->owner.save(bytes,extension,crop,sourceName,comment),r->{clearPhoto();queuePage();status("已保存在此账号的手机队列，联网后点击上传。");});
                }catch(Exception e){status("无法保存裁剪图，请重试。");}
            });
            button("返回",()->{clearPhoto();home();});
        });
    }
    void queuePage(){
        location="queue";
        screen("上传队列","当前账号："+api.username+"\n退出或断网不会清除已保存任务。上传成功后，电脑接收并核对收录。");
        button("上传全部待传图片",()->{
            CloudApi client=api;PhotoQueue owner=queue;run(()->owner.uploadAll(client),result->{queuePage();status("本轮已上传 "+result+" 张；可在电脑“手机待整理”中接收。");});
        });
        button("刷新电脑处理状态",()->{CloudApi client=api;run(()->pullInbox(client),r->{queuePage();status("已更新电脑处理状态。");});});
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
    void questionPage(){
        location="questions";
        screen("我的题目","电脑收录并同步后可在这里查看。答题记录和掌握状态仍在电脑端记录。");
        button("从云端更新题目",()->{CloudApi client=api;File file=new File(queue.root,"questions.json");run(()->pullQuestions(client,file),r->questionPage());});
        button("返回拍题",this::home);
        try {
            File file=new File(queue.root,"questions.json");if(!file.exists()){text("暂无本机缓存，点击更新获取题目。",16,false);return;}
            JSONArray rows=new JSONArray(new String(CloudApi.read(file,8*1024*1024),StandardCharsets.UTF_8));
            for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if(!row.optBoolean("deleted")){JSONObject q=row.getJSONObject("payload").getJSONObject("question");String stem=q.optString("stem");button(stem.length()>90?stem.substring(0,90)+"…":stem,()->questionDetail(q));}}
            if(rows.length()==0)text("云端暂无题目。",16,false);
        }catch(Exception e){status("本机题目缓存无法读取，请重新更新。");}
    }
    Object pullQuestions(CloudApi client,File file) throws Exception {
        JSONArray result=new JSONArray();long cursor=0;int bytes=0;
        for(int page=0;page<100;page++){
            JSONObject response=client.rpc("flandre_sync_pull",new JSONObject().put("p_after",cursor).put("p_limit",10));JSONArray rows=response.getJSONArray("records");
            if(rows.length()>10)throw new IOException("题目分页无效。");
            for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if(!client.uid.equals(row.optString("user_id"))||row.getLong("seq")<=cursor)throw new IOException("题目账号或顺序无效。");cursor=row.getLong("seq");bytes+=row.toString().getBytes(StandardCharsets.UTF_8).length;if(bytes>8*1024*1024)throw new IOException("题库较大，暂时无法缓存全部题目。");result.put(row);}
            if(response.getLong("cursor")!=cursor)throw new IOException("题目分页进度无效。");
            if(rows.length()<10){PhotoQueue.atomic(file,result.toString().getBytes(StandardCharsets.UTF_8));return result;}
        }throw new IOException("题库超过当前预览版缓存上限（1000 项），请在电脑查看。");
    }
    void questionDetail(JSONObject q){
        location="detail";
        screen("题目",q.optString("subject")+" · "+q.optString("source"));text(q.optString("stem"),19,true);
        JSONObject options=q.optJSONObject("options");if(options!=null){Iterator<String> keys=options.keys();while(keys.hasNext()){String k=keys.next();text(k+". "+options.optString(k),16,false);}}
        button("查看答案和解析",()->{new AlertDialog.Builder(this).setTitle("答案与解析").setMessage(q.optString("answer")+"\n\n"+q.optString("explanation")).setPositiveButton("关闭",null).show();});
        if(!q.optString("notes").isEmpty())text("我的笔记\n"+q.optString("notes"),16,false);
        button("返回题目列表",this::questionPage);
    }
    void handleBack(){
        if(busy){status("正在处理，请稍候。已保存的任务会保留。");return;}
        if(location.equals("home")||api==null){finish();return;}
        if(location.equals("detail")){questionPage();return;}
        if(location.equals("photo")){new AlertDialog.Builder(this).setTitle("照片还未保存")
            .setMessage("返回拍题页会舍弃本次选择，已保存的队列不受影响。")
            .setNegativeButton("继续编辑",null).setPositiveButton("返回",(dialog,which)->{clearPhoto();home();}).show();return;}
        clearPhoto();home();
    }
    public void onBackPressed(){handleBack();}
    protected void onDestroy(){super.onDestroy();if(api!=null)api.close();executor.shutdown();}
}
