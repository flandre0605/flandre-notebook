package com.flandre.notebook;

import org.json.*;
import java.io.*;
import java.util.*;

final class NotebookSync {
    static void materialize(Notebook local,CloudApi api,JSONObject row) throws Exception {
        if(row.getBoolean("deleted"))return;JSONArray images=row.getJSONObject("payload").getJSONArray("attachments");
        for(int i=0;i<images.length();i++){JSONObject image=images.getJSONObject(i);File f=local.file(image);
            byte[] bytes=f.isFile()?CloudApi.read(f,CloudApi.MAX_IMAGE):api.downloadQuestion(row.getString("id"),image);local.storeImage(image,bytes);
        }
    }
    static String synchronize(Notebook local,CloudApi api) throws Exception {
        return synchronize(local,api,true);
    }
    static String synchronize(Notebook local,CloudApi api,boolean pull) throws Exception {
        if(!local.uid.equals(api.uid))throw new IOException("题库与当前登录账号不同。");int uploaded=0,downloaded=0;
        for(int n=0;n<200;n++){
            JSONObject pending=local.prepare();if(pending==null)break;JSONObject p=pending.getJSONObject("payload");JSONArray images=p.optJSONArray("attachments");
            if(images!=null)for(int i=0;i<images.length();i++){JSONObject a=images.getJSONObject(i);api.uploadQuestion(pending.getString("entity_id"),a,local.file(a));}
            JSONObject result=api.rpc("flandre_sync_push",new JSONObject().put("p_id",pending.getString("entity_id")).put("p_operation_id",pending.getString("operation_id")).put("p_base_version",pending.getLong("base_version")).put("p_deleted",pending.getInt("deleted")==1).put("p_payload",p));
            if(result.optString("status").equals("conflict")){JSONObject r=result.optJSONObject("record");if(r!=null){r=local.validateRecord(r);if(!r.getString("id").equals(pending.getString("entity_id")))throw new IOException("冲突响应对应其他题目。");materialize(local,api,r);}local.conflict(pending.getString("entity_id"),r);continue;}
            if(!result.optString("status").equals("applied"))throw new IOException("云端未确认操作，保留原任务编号重试。");local.ack(pending,result.getJSONObject("record"));uploaded++;
        }
        if(!pull)return finish(local,api,uploaded,0,false);
        for(int n=0;n<100;n++){
            long cursor=Long.parseLong(local.state("cursor","0"));JSONObject result=api.rpc("flandre_sync_pull",new JSONObject().put("p_after",cursor).put("p_limit",10));JSONArray rows=result.getJSONArray("records");
            if(rows.length()>10||!(result.opt("cursor") instanceof Integer||result.opt("cursor") instanceof Long))throw new IOException("同步分页无效。");List<JSONObject> prepared=new ArrayList<>();
            for(int i=0;i<rows.length();i++){JSONObject r=local.validateRecord(rows.getJSONObject(i));if(r.getLong("seq")<=cursor)throw new IOException("同步顺序无效。");cursor=r.getLong("seq");materialize(local,api,r);prepared.add(r);}
            if(result.getLong("cursor")!=cursor)throw new IOException("同步游标无效。");local.apply(prepared,cursor);downloaded+=rows.length();if(rows.length()<10)return finish(local,api,uploaded,downloaded,true);
        }throw new IOException("本轮已接收 1000 项变化，请再次同步。");
    }
    static int pending(Notebook b){synchronized(b){try(android.database.Cursor c=b.db.rawQuery("SELECT count(*) FROM entries WHERE dirty=1 AND conflict IS NULL",null)){c.moveToFirst();return c.getInt(0)+LearningSync.pending(b);}}}
    static String finish(Notebook b,CloudApi api,int uploaded,int downloaded,boolean pull) throws Exception {
        int[] learning=LearningSync.synchronize(b,api,pull);b.putState("last_sync",Notebook.now());b.putState("sync_error","");
        return "题目、原图、单词与作答历史：发送 "+(uploaded+learning[0])+" 项，接收 "+(downloaded+learning[1])+" 项。剩余待传 "+pending(b)+" 项；冲突请在账号与同步中处理。";
    }
}
