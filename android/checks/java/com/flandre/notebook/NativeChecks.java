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
                View root=current.getWindow().getDecorView();check(findText(root,"Flandre 拍题"),"login page rendered");
                List<EditText> editors=new ArrayList<>();findEditors(root,editors);check(editors.size()==2&&!editors.get(1).isSaveEnabled(),"password does not enter view-state cache");
                Bitmap bitmap=Bitmap.createBitmap(100,60,Bitmap.Config.ARGB_8888);bitmap.eraseColor(Color.WHITE);
                CropView crop=new CropView(current,bitmap);crop.layout(0,0,200,120);Bitmap canvas=Bitmap.createBitmap(200,120,Bitmap.Config.ARGB_8888);crop.draw(new Canvas(canvas));
                crop.onTouchEvent(MotionEvent.obtain(0,0,MotionEvent.ACTION_DOWN,20,20,0));crop.onTouchEvent(MotionEvent.obtain(0,10,MotionEvent.ACTION_UP,160,100,0));
                try{byte[] clipped=crop.cropped();Bitmap decoded=BitmapFactory.decodeByteArray(clipped,0,clipped.length);check(decoded.getWidth()==70&&decoded.getHeight()==40,"crop coordinates and JPEG readable");decoded.recycle();}catch(Exception e){throw new AssertionError(e);}
                bitmap.recycle();canvas.recycle();
            });
            result.putString("stream","PASS: "+passed+" Android queue, retry, integrity, isolation, crop and login UI assertions\n");
            finish(Activity.RESULT_OK,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error.toString()+"\n");finish(Activity.RESULT_CANCELED,result);}
        finally{if(activity!=null){final Activity current=activity;runOnMainSync(current::finish);}}
    }
    boolean findText(View v,String text){if(v instanceof TextView&&((TextView)v).getText().toString().equals(text))return true;if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)if(findText(g.getChildAt(i),text))return true;}return false;}
    void findEditors(View v,List<EditText> result){if(v instanceof EditText)result.add((EditText)v);if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)findEditors(g.getChildAt(i),result);}}
}
