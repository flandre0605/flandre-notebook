package com.flandre.notebook;

import android.util.AtomicFile;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

final class PhotoQueue {
    final File root;
    final String uid;
    PhotoQueue(File base,String user) throws IOException {
        if(!user.matches("[A-Za-z0-9_-]{1,64}"))throw new IOException("账号编号无效。");
        uid=user;root=new File(base,user);if(!root.isDirectory()&&!root.mkdirs())throw new IOException("无法建立账号目录。");
    }
    static void atomic(File file,byte[] bytes) throws IOException {
        AtomicFile atomic=new AtomicFile(file);FileOutputStream out=null;
        try{out=atomic.startWrite();out.write(bytes);atomic.finishWrite(out);}catch(IOException e){if(out!=null)atomic.failWrite(out);throw e;}
    }
    File item(String id) throws IOException {if(!id.matches("[a-f0-9]{32}"))throw new IOException("任务编号无效。");return new File(root,id);}
    JSONObject load(File dir) throws Exception {
        AtomicFile file=new AtomicFile(new File(dir,"task.json"));byte[] data;
        try(InputStream in=file.openRead();ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[4096];int n;while((n=in.read(b))!=-1){if(out.size()+n>32768)throw new IOException("任务格式过大。");out.write(b,0,n);}data=out.toByteArray();}
        JSONObject task=new JSONObject(new String(data,StandardCharsets.UTF_8));
        if(!uid.equals(task.optString("user_id"))||!dir.getName().equals(task.optString("id")))throw new IOException("任务不属于当前账号。");
        return task;
    }
    List<File> tasks() {
        File[] dirs=root.listFiles(f->f.isDirectory()&&f.getName().matches("[a-f0-9]{32}")&&(new File(f,"task.json").isFile()||new File(f,"task.json.bak").isFile()));
        List<File> rows=new ArrayList<>();if(dirs!=null)rows.addAll(Arrays.asList(dirs));rows.sort(Comparator.comparingLong(File::lastModified));return rows;
    }
    JSONObject save(byte[] original,String extension,byte[] crop,String name,String note) throws Exception {
        if(original.length==0||original.length>CloudApi.MAX_IMAGE||crop.length==0||crop.length>CloudApi.MAX_IMAGE)throw new IOException("图片须小于 20 MB。");
        if(!Arrays.asList("png","jpg","jpeg","webp").contains(extension))throw new IOException("图片格式无效。");
        String id=CloudApi.id();File dir=item(id);if(!dir.mkdirs())throw new IOException("无法保存图片。");
        JSONArray images=new JSONArray();
        images.put(image(dir,id,original,extension,"original"));images.put(image(dir,id,crop,"jpg","crop"));
        JSONObject payload=new JSONObject().put("source_name",name).put("note",note).put("images",images);
        JSONObject task=new JSONObject().put("id",id).put("user_id",uid).put("payload",payload).put("uploaded",false);
        atomic(new File(dir,"task.json"),task.toString().getBytes(StandardCharsets.UTF_8));return task;
    }
    JSONObject image(File dir,String receipt,byte[] bytes,String extension,String role) throws Exception {
        String aid=CloudApi.id(),hash=CloudApi.sha(bytes);atomic(new File(dir,aid+"."+extension),bytes);
        return new JSONObject().put("id",aid).put("sha256",hash).put("size",bytes.length).put("role",role)
          .put("mime_type",extension.equals("png")?"image/png":extension.equals("webp")?"image/webp":"image/jpeg")
          .put("key",uid+"/"+receipt+"/"+aid+"/"+hash+"."+extension);
    }
    int uploadAll(CloudApi api) throws Exception {
        if(!uid.equals(api.uid))throw new IOException("任务与登录账号不同。");int count=0;
        for(File dir:tasks()){
            JSONObject task=load(dir);if(task.optBoolean("uploaded"))continue;
            JSONObject payload=task.getJSONObject("payload");JSONArray images=payload.getJSONArray("images");
            for(int i=0;i<images.length();i++){
                JSONObject image=images.getJSONObject(i);String key=image.getString("key");api.objectPath(image,task.getString("id"));
                File file=new File(dir,image.getString("id")+key.substring(key.lastIndexOf('.')));
                if(!file.getCanonicalFile().getParentFile().equals(dir.getCanonicalFile()))throw new IOException("图片路径无效。");
                api.upload(task.getString("id"),image,file);
            }
            JSONObject row=api.rpc("flandre_inbox_submit",new JSONObject().put("p_id",task.getString("id")).put("p_payload",payload)).getJSONObject("record");
            if(!uid.equals(row.optString("user_id"))||!task.getString("id").equals(row.optString("id").replace("-",""))||
               !CloudApi.same(payload,row.opt("payload"))||!Arrays.asList("pending","processed","dismissed").contains(row.optString("status")))throw new IOException("云端未确认此任务，保留原编号重试。");
            task.put("uploaded",true);atomic(new File(dir,"task.json"),task.toString().getBytes(StandardCharsets.UTF_8));count++;
        }
        return count;
    }
}
