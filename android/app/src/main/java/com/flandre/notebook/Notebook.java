package com.flandre.notebook;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.graphics.BitmapFactory;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.*;

/** Local learning data. Business mutations and durable sync markers share a transaction. */
final class Notebook implements Closeable {
    static final String[] FIELDS={"stem","subject","question_type","answer","explanation","tags","knowledge_points","difficulty","source","grade","notes"};
    final File root;
    final String uid;
    final SQLiteDatabase db;
    Notebook(File folder,String user) throws Exception {
        if(!user.matches("[A-Za-z0-9_-]{1,64}"))throw new IOException("账号编号无效。");
        root=folder;uid=user;if(!root.isDirectory()&&!root.mkdirs())throw new IOException("无法打开本机题库。");
        db=SQLiteDatabase.openOrCreateDatabase(new File(root,"notebook.db"),null);
        db.beginTransaction();try{
            db.execSQL("CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,base_version INTEGER NOT NULL,dirty INTEGER NOT NULL,deleted INTEGER NOT NULL,payload TEXT NOT NULL,conflict TEXT)");
            db.execSQL("CREATE TABLE IF NOT EXISTS outbox(operation_id TEXT PRIMARY KEY,entity_id TEXT UNIQUE,revision INTEGER,base_version INTEGER,deleted INTEGER,payload TEXT)");
            db.execSQL("CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,payload TEXT NOT NULL)");
            db.execSQL("CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,question_id TEXT,time TEXT,answer TEXT,correct INTEGER,mastery TEXT)");
            db.execSQL("CREATE TABLE IF NOT EXISTS words(id TEXT PRIMARY KEY,word TEXT,meaning TEXT,phonetic TEXT,example TEXT,mastery TEXT,due_at TEXT)");
            db.execSQL("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT)");
            db.execSQL("CREATE TABLE IF NOT EXISTS imports(source_id TEXT PRIMARY KEY,target_id TEXT)");
            String bound=state("owner",user);if(!bound.equals(user))throw new IOException("题库属于其他账号。");
            putState("owner",user);db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    public synchronized void close(){db.close();}
    static String id(String s) throws IOException {String t=s.replace("-","");if(!t.matches("[a-f0-9]{32}"))throw new IOException("题目编号无效。");return t;}
    static String now(){return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.ROOT).format(new Date());}
    static String due(int days){Calendar c=Calendar.getInstance();c.add(Calendar.DATE,days);return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.ROOT).format(c.getTime());}
    static JSONObject copy(JSONObject value) throws JSONException {return new JSONObject(value.toString());}
    static JSONObject question(JSONObject input) throws Exception {
        JSONObject q=new JSONObject();for(String k:FIELDS){Object v=input.opt(k);if(v==null)v="";if(!(v instanceof String)||((String)v).length()>20000)throw new IOException("题目字段过长或无效："+k);q.put(k,((String)v).trim());}
        if(q.getString("stem").isEmpty())throw new IOException("请填写题干。");
        if(!Arrays.asList("","简单","中等","困难").contains(q.getString("difficulty")))throw new IOException("难度请选择简单、中等、困难，或留空。");
        if(q.getString("grade").length()>100||q.getString("grade").contains("\n")||q.getString("grade").contains("\r"))throw new IOException("年级须为不超过 100 字的单行文本。");
        Object wrong=input.opt("is_wrong");boolean numeric=wrong instanceof Integer||wrong instanceof Long;int flag=(Boolean.TRUE.equals(wrong)||(numeric&&((Number)wrong).longValue()==1))?1:0;
        if(wrong!=null&&!(wrong instanceof Boolean)&&!(numeric&&(((Number)wrong).longValue()==0||((Number)wrong).longValue()==1)))throw new IOException("错题标记无效。");
        q.put("is_wrong",flag);JSONObject options=input.optJSONObject("options");if(options==null){if(input.has("options"))throw new IOException("选项应为标号与内容组成的对象。");options=new JSONObject();}
        if(options.length()==1||options.length()>12)throw new IOException("选择题至少两个选项，最多十二个。");
        JSONObject sorted=new JSONObject();List<String> keys=new ArrayList<>();Iterator<String> iterator=options.keys();while(iterator.hasNext())keys.add(iterator.next());Collections.sort(keys);
        for(String k:keys){Object v=options.get(k);if(!k.matches("[A-Z]")||!(v instanceof String)||((String)v).trim().isEmpty()||((String)v).length()>20000)throw new IOException("选项标号为 A～Z，内容不能为空。");sorted.put(k,((String)v).trim());}
        q.put("options",sorted);return q;
    }
    static void imageInfo(JSONObject a,String uid,String qid) throws Exception {
        String aid=id(a.getString("id")),hash=a.getString("sha256"),key=a.getString("key"),mime=a.getString("mime_type");
        String ext=key.substring(key.lastIndexOf('.')+1);String expected=ext.equals("png")?"image/png":ext.equals("webp")?"image/webp":"image/jpeg";
        Object size=a.get("size");if(!aid.equals(a.getString("id"))||!hash.matches("[a-f0-9]{64}")||!Arrays.asList("png","jpg","jpeg","webp").contains(ext)||
          !key.equals(uid+"/"+qid+"/"+aid+"/"+hash+"."+ext)||!expected.equals(mime)||!(size instanceof Integer||size instanceof Long)||a.getLong("size")<1||a.getLong("size")>CloudApi.MAX_IMAGE||
          !(a.opt("original_name") instanceof String)||a.getString("original_name").length()>260)throw new IOException("图片归属、路径或校验信息无效。");
    }
    static JSONObject payload(JSONObject p,String uid,String qid) throws Exception {
        if(p.toString().getBytes(StandardCharsets.UTF_8).length>1024*1024)throw new IOException("单题内容超过 1 MB。");
        JSONObject result=copy(p).put("question",question(p.getJSONObject("question")));
        Object review=p.opt("review");if(review!=null&&review!=JSONObject.NULL){
            if(!(review instanceof JSONObject))throw new IOException("复习信息无效。");JSONObject r=(JSONObject)review;
            if(!Arrays.asList("mastered","unsure","unknown").contains(r.optString("mastery"))||!(r.opt("review_count") instanceof Integer||r.opt("review_count") instanceof Long)||r.getLong("review_count")<1)throw new IOException("复习状态无效。");
            SimpleDateFormat f=new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.ROOT);f.setLenient(false);
            for(String k:new String[]{"due_at","last_reviewed_at"}){String s=r.getString(k);if(!s.matches("\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}"))throw new IOException("复习日期无效。");f.parse(s);}
        }else result.put("review",JSONObject.NULL);
        JSONArray images=p.getJSONArray("attachments");if(images.length()>50)throw new IOException("单题附件超过 50 张。");Set<String> ids=new HashSet<>();
        for(int i=0;i<images.length();i++){JSONObject a=images.getJSONObject(i);imageInfo(a,uid,qid);if(!ids.add(a.getString("id")))throw new IOException("附件编号重复。");}
        return result;
    }
    synchronized String state(String key,String fallback){try(Cursor c=db.rawQuery("SELECT value FROM state WHERE key=?",new String[]{key})){return c.moveToFirst()?c.getString(0):fallback;}}
    synchronized void putState(String key,String value){db.execSQL("INSERT OR REPLACE INTO state VALUES(?,?)",new Object[]{key,value});}
    synchronized JSONObject entry(String key) throws Exception {try(Cursor c=db.rawQuery("SELECT * FROM entries WHERE id=?",new String[]{id(key)})){return c.moveToFirst()?row(c):null;}}
    static JSONObject row(Cursor c) throws JSONException {JSONObject r=new JSONObject();for(int i=0;i<c.getColumnCount();i++){String k=c.getColumnName(i);if(c.isNull(i))r.put(k,JSONObject.NULL);else if(c.getType(i)==Cursor.FIELD_TYPE_INTEGER)r.put(k,c.getLong(i));else if(k.equals("payload")||k.equals("conflict"))r.put(k,new JSONObject(c.getString(i)));else r.put(k,c.getString(i));}return r;}
    synchronized List<JSONObject> entries(String query,String subject,String filter) throws Exception {
        List<JSONObject> list=new ArrayList<>();String needle=query.toLowerCase(Locale.ROOT);
        try(Cursor c=db.rawQuery("SELECT * FROM entries WHERE deleted=0 ORDER BY rowid DESC",null)){while(c.moveToNext()){
            JSONObject e=row(c),p=e.getJSONObject("payload"),q=p.getJSONObject("question"),r=p.optJSONObject("review");
            if(!subject.isEmpty()&&!subject.equals(q.optString("subject")))continue;
            if(filter.equals("wrong")&&q.optInt("is_wrong")==0)continue;
            if(filter.equals("due")&&(r==null||r.optString("due_at").compareTo(now())>0))continue;
            if(filter.equals("conflict")&&e.isNull("conflict"))continue;
            if(Arrays.asList("mastered","unsure","unknown").contains(filter)&&(r==null||!filter.equals(r.optString("mastery"))))continue;
            if(!needle.isEmpty()){StringBuilder all=new StringBuilder();for(String k:FIELDS)all.append(q.optString(k)).append('\n');all.append(q.optJSONObject("options"));if(!all.toString().toLowerCase(Locale.ROOT).contains(needle))continue;}
            list.add(e);
        }}return list;
    }
    synchronized String save(String key,JSONObject q,JSONArray images) throws Exception {
        String id=key==null?CloudApi.id():id(key);JSONObject old=entry(id);if(old!=null&&old.getInt("deleted")!=0)throw new IOException("题目已删除，请另存副本。");
        JSONObject p=old==null?new JSONObject().put("review",JSONObject.NULL).put("attachments",new JSONArray()):old.getJSONObject("payload");
        p.put("question",question(q));if(images!=null)p.put("attachments",images);p=payload(p,uid,id);
        db.beginTransaction();try{mutate(id,p,false);db.setTransactionSuccessful();}finally{db.endTransaction();}return id;
    }
    void mutate(String id,JSONObject p,boolean deleted) throws Exception {
        if(entry(id)==null)db.execSQL("INSERT INTO entries(id,revision,base_version,dirty,deleted,payload) VALUES(?,1,0,1,?,?)",new Object[]{id,deleted?1:0,p.toString()});
        else db.execSQL("UPDATE entries SET revision=revision+1,dirty=1,deleted=?,payload=? WHERE id=?",new Object[]{deleted?1:0,p.toString(),id});
    }
    synchronized void delete(String key) throws Exception {JSONObject e=entry(key);if(e==null)throw new IOException("题目不存在。");db.beginTransaction();try{mutate(id(key),e.getJSONObject("payload"),true);db.setTransactionSuccessful();}finally{db.endTransaction();}}
    synchronized void practice(String key,String answer,boolean correct,String mastery,int days) throws Exception {
        practiceOnce(key,answer,correct,mastery,days,CloudApi.id(),null);
    }
    synchronized void practiceOnce(String key,String answer,boolean correct,String mastery,int days,String attemptId,JSONObject next) throws Exception {
        practiceOnce(key,answer,correct,!correct,mastery,days,attemptId,next);
    }
    synchronized void practiceOnce(String key,String answer,boolean correct,boolean markWrong,String mastery,int days,String attemptId,JSONObject next) throws Exception {
        if(!Arrays.asList("mastered","unsure","unknown").contains(mastery)||days<0||days>365||answer.length()>20000)throw new IOException("练习记录无效。");
        db.beginTransaction();try{try(Cursor c=db.rawQuery("SELECT question_id FROM attempts WHERE id=?",new String[]{id(attemptId)})){if(c.moveToFirst()){if(!id(key).equals(c.getString(0)))throw new IOException("练习编号不属于此题。");if(next!=null)putState("practice",next.toString());db.setTransactionSuccessful();return;}}
            JSONObject e=entry(key);if(e==null||e.getInt("deleted")!=0)throw new IOException("题目已删除，未记录练习。");JSONObject p=e.getJSONObject("payload"),previous=p.optJSONObject("review");
            JSONObject r=new JSONObject().put("mastery",mastery).put("due_at",due(days)).put("last_reviewed_at",now()).put("review_count",previous==null?1:previous.getLong("review_count")+1);
            p.put("review",r);p.getJSONObject("question").put("is_wrong",markWrong?1:0);
            db.execSQL("INSERT INTO attempts VALUES(?,?,?,?,?,?)",new Object[]{id(attemptId),id(key),now(),answer,correct?1:0,mastery});mutate(id(key),p,false);if(next!=null)putState("practice",next.toString());db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    synchronized JSONArray history(String key) throws Exception {JSONArray a=new JSONArray();try(Cursor c=db.rawQuery("SELECT * FROM attempts WHERE question_id=? ORDER BY time DESC,rowid DESC LIMIT 100",new String[]{id(key)})){while(c.moveToNext())a.put(row(c));}return a;}
    synchronized JSONObject statistics() throws Exception {
        JSONObject stats=new JSONObject();for(String k:new String[]{"total","correct","today"}){String sql=k.equals("total")?"SELECT COUNT(*) FROM attempts":k.equals("correct")?"SELECT COUNT(*) FROM attempts WHERE correct=1":"SELECT COUNT(*) FROM attempts WHERE time>=?";
            try(Cursor c=db.rawQuery(sql,k.equals("today")?new String[]{now().substring(0,10)+" 00:00:00"}:null)){c.moveToFirst();stats.put(k,c.getInt(0));}}
        JSONArray days=new JSONArray();try(Cursor c=db.rawQuery("SELECT substr(time,1,10) AS day,count(*) AS count FROM attempts GROUP BY day ORDER BY day DESC LIMIT 90",null)){while(c.moveToNext())days.put(row(c));}stats.put("days",days);return stats;
    }
    synchronized void draft(String id,JSONObject value){db.execSQL("INSERT OR REPLACE INTO drafts VALUES(?,?)",new Object[]{id,value.toString()});}
    synchronized JSONObject draft(String id) throws Exception {try(Cursor c=db.rawQuery("SELECT payload FROM drafts WHERE id=?",new String[]{id})){return c.moveToFirst()?new JSONObject(c.getString(0)):null;}}
    synchronized JSONArray drafts() throws Exception {JSONArray a=new JSONArray();try(Cursor c=db.rawQuery("SELECT * FROM drafts ORDER BY rowid DESC",null)){while(c.moveToNext())a.put(row(c));}return a;}
    synchronized void discardDraft(String id){db.delete("drafts","id=?",new String[]{id});}
    synchronized List<String> confirmDraft(String key) throws Exception {
        db.beginTransaction();try{JSONObject d=draft(key);if(d==null)throw new IOException("草稿已收录或不存在。");JSONArray qs=d.getJSONArray("questions"),images=d.optJSONArray("images");if(qs.length()<1||qs.length()>50)throw new IOException("草稿题目数量无效。");List<String> ids=new ArrayList<>();
            for(int i=0;i<qs.length();i++){String qid=CloudApi.id();JSONArray imgs=remapImages(images,qid);save(qid,qs.getJSONObject(i),imgs);ids.add(qid);}
            discardDraft(key);db.setTransactionSuccessful();return ids;
        }finally{db.endTransaction();}
    }
    JSONArray remapImages(JSONArray images,String qid) throws Exception {
        JSONArray result=new JSONArray();if(images!=null)for(int i=0;i<images.length();i++){JSONObject a=copy(images.getJSONObject(i));String ext=a.getString("key").substring(a.getString("key").lastIndexOf('.'));String aid=CloudApi.id();a.put("id",aid).put("key",uid+"/"+qid+"/"+aid+"/"+a.getString("sha256")+ext);file(a);result.put(a);}return result;
    }
    File file(JSONObject image) throws Exception {
        String key=image.getString("key"),hash=image.getString("sha256"),ext=key.substring(key.lastIndexOf('.'));
        if(!hash.matches("[a-f0-9]{64}")||!Arrays.asList(".png",".jpg",".jpeg",".webp").contains(ext))throw new IOException("图片路径无效。");
        File f=new File(new File(root,"images"),hash+ext);if(!f.getCanonicalFile().getParentFile().equals(new File(root,"images").getCanonicalFile()))throw new IOException("图片目录无效。");return f;
    }
    JSONObject addImage(byte[] content,String ext,String name,String qid) throws Exception {
        if(!Arrays.asList("png","jpg","jpeg","webp").contains(ext)||content.length<1||content.length>CloudApi.MAX_IMAGE)throw new IOException("图片格式或大小无效。");
        String hash=CloudApi.sha(content),aid=CloudApi.id();JSONObject a=new JSONObject().put("id",aid).put("sha256",hash).put("size",content.length).put("mime_type",ext.equals("png")?"image/png":ext.equals("webp")?"image/webp":"image/jpeg").put("original_name",name).put("key",uid+"/"+id(qid)+"/"+aid+"/"+hash+"."+ext);storeImage(a,content);return a;
    }
    void storeImage(JSONObject a,byte[] bytes) throws Exception {
        if(bytes.length!=a.getLong("size")||!CloudApi.sha(bytes).equals(a.getString("sha256")))throw new IOException("图片校验失败，未推进同步。");
        BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(bytes,0,bytes.length,bounds);
        if(bounds.outWidth<1||bounds.outHeight<1||!a.getString("mime_type").equals(bounds.outMimeType))throw new IOException("图片无法读取或格式不符。");
        File f=file(a);if(!f.getParentFile().isDirectory()&&!f.getParentFile().mkdirs())throw new IOException("无法保存图片。");
        if(f.isFile()){if(!CloudApi.sha(CloudApi.read(f,CloudApi.MAX_IMAGE)).equals(a.getString("sha256")))throw new IOException("已保存图片损坏，请先恢复备份。");}else PhotoQueue.atomic(f,bytes);
    }
    synchronized JSONObject prepare() throws Exception {
        db.beginTransaction();try{
            try(Cursor c=db.rawQuery("SELECT o.* FROM outbox o JOIN entries e ON e.id=o.entity_id WHERE e.conflict IS NULL ORDER BY o.rowid LIMIT 1",null)){if(c.moveToFirst()){JSONObject r=row(c);db.setTransactionSuccessful();return r;}}
            try(Cursor c=db.rawQuery("SELECT * FROM entries WHERE dirty=1 AND conflict IS NULL ORDER BY rowid LIMIT 1",null)){if(!c.moveToFirst()){db.setTransactionSuccessful();return null;}JSONObject e=row(c);String op=CloudApi.id();JSONObject p=e.getInt("deleted")==1?new JSONObject():payload(e.getJSONObject("payload"),uid,e.getString("id"));
                db.execSQL("INSERT INTO outbox VALUES(?,?,?,?,?,?)",new Object[]{op,e.getString("id"),e.getLong("revision"),e.getLong("base_version"),e.getInt("deleted"),p.toString()});
                JSONObject r=new JSONObject().put("operation_id",op).put("entity_id",e.getString("id")).put("revision",e.getLong("revision")).put("base_version",e.getLong("base_version")).put("deleted",e.getInt("deleted")).put("payload",p);db.setTransactionSuccessful();return r;
            }
        }finally{db.endTransaction();}
    }
    JSONObject validateRecord(JSONObject row) throws Exception {
        JSONObject r=copy(row);String qid=id(r.getString("id"));
        if(!uid.equals(r.optString("user_id"))||!(r.opt("version") instanceof Integer||r.opt("version") instanceof Long)||r.getLong("version")<1||!(r.opt("seq") instanceof Integer||r.opt("seq") instanceof Long)||r.getLong("seq")<1||!(r.opt("deleted") instanceof Boolean))throw new IOException("云端账号、版本或记录无效。");
        r.put("id",qid);if(!r.getBoolean("deleted"))r.put("payload",payload(r.getJSONObject("payload"),uid,qid));return r;
    }
    synchronized void ack(JSONObject pending,JSONObject record) throws Exception {
        JSONObject r=validateRecord(record);
        if(!r.getString("id").equals(pending.getString("entity_id"))||r.getLong("version")!=pending.getLong("base_version")+1||r.getBoolean("deleted")!=(pending.getInt("deleted")==1)||(!r.getBoolean("deleted")&&!CloudApi.same(r.get("payload"),pending.get("payload"))))throw new IOException("同步确认与本轮内容不同，保留任务重试。");
        db.beginTransaction();try{try(Cursor c=db.rawQuery("SELECT * FROM outbox WHERE operation_id=?",new String[]{pending.getString("operation_id")})){if(!c.moveToFirst()||!CloudApi.same(row(c),pending))throw new IOException("同步任务已发生变化。");}
            db.execSQL("UPDATE entries SET base_version=?,dirty=CASE WHEN revision=? THEN 0 ELSE 1 END WHERE id=?",new Object[]{r.getLong("version"),pending.getLong("revision"),pending.getString("entity_id")});db.delete("outbox","operation_id=?",new String[]{pending.getString("operation_id")});db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    synchronized void conflict(String id,JSONObject r) throws Exception {if(r!=null)r=validateRecord(r);if(r!=null&&!r.getString("id").equals(id))throw new IOException("冲突对应其他题目。");db.execSQL("UPDATE entries SET conflict=? WHERE id=?",new Object[]{r==null?"{}":r.toString(),id});}
    synchronized void apply(List<JSONObject> rows,long cursor) throws Exception {db.beginTransaction();try{for(JSONObject r:rows)applyOne(r,false);putState("cursor",Long.toString(cursor));db.setTransactionSuccessful();}finally{db.endTransaction();}}
    void applyOne(JSONObject r,boolean force) throws Exception {
        String id=r.getString("id");JSONObject e=entry(id);if(!force&&e!=null&&e.getLong("base_version")>=r.getLong("version"))return;
        if(!force&&e!=null&&(e.getInt("dirty")==1||!e.isNull("conflict"))){conflict(id,r);return;}
        JSONObject p=r.getBoolean("deleted")?(e==null?new JSONObject():e.getJSONObject("payload")):r.getJSONObject("payload");
        db.execSQL("INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?,?,NULL)",new Object[]{id,e==null?1:e.getLong("revision")+1,r.getLong("version"),0,r.getBoolean("deleted")?1:0,p.toString()});
    }
    synchronized void resolve(String id,boolean keepLocal) throws Exception {
        db.beginTransaction();try{JSONObject e=entry(id);if(e==null||e.isNull("conflict"))throw new IOException("冲突已变化。");JSONObject r=e.getJSONObject("conflict");
            JSONObject backup=new JSONObject().put("questions",new JSONArray().put(e.getJSONObject("payload").optJSONObject("question"))).put("images",e.getJSONObject("payload").optJSONArray("attachments")).put("label","同步前的本机副本");draft(CloudApi.id(),backup);
            db.delete("outbox","entity_id=?",new String[]{id});
            if(keepLocal){if(r.length()==0||r.optBoolean("deleted")){if(e.getInt("deleted")==0){String fresh=CloudApi.id();JSONObject p=e.getJSONObject("payload");save(fresh,p.getJSONObject("question"),remapImages(p.getJSONArray("attachments"),fresh));}if(r.length()!=0)applyOne(r,true);else db.delete("entries","id=?",new String[]{id});}
                else db.execSQL("UPDATE entries SET base_version=?,revision=revision+1,dirty=1,conflict=NULL WHERE id=?",new Object[]{r.getLong("version"),id});
            }else{if(r.length()==0)db.delete("entries","id=?",new String[]{id});else applyOne(r,true);}
            db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    synchronized void word(String id,String word,String meaning,String phonetic,String example) throws Exception {
        if(word.trim().isEmpty()||word.length()>300||meaning.length()>2000||phonetic.length()>300||example.length()>4000)throw new IOException("单词为空或文本过长。");
        if(id==null){try(Cursor c=db.rawQuery("SELECT id FROM words WHERE lower(word)=lower(?)",new String[]{word.trim()})){if(c.moveToFirst())id=c.getString(0);}}
        if(id==null)id=CloudApi.id();db.beginTransaction();try{db.execSQL("INSERT OR IGNORE INTO words VALUES(?,?,?,?,?,'unknown',?)",new Object[]{id,word.trim(),meaning,phonetic,example,now()});db.execSQL("UPDATE words SET word=?,meaning=?,phonetic=?,example=? WHERE id=?",new Object[]{word.trim(),meaning,phonetic,example,id});db.setTransactionSuccessful();}finally{db.endTransaction();}
    }
    synchronized JSONArray words() throws Exception {JSONArray a=new JSONArray();try(Cursor c=db.rawQuery("SELECT * FROM words ORDER BY due_at,rowid",null)){while(c.moveToNext())a.put(row(c));}return a;}
    synchronized void reviewWord(String id,String mastery,int days){db.execSQL("UPDATE words SET mastery=?,due_at=? WHERE id=?",new Object[]{mastery,due(days),id});}
    synchronized void deleteWord(String id){db.delete("words","id=?",new String[]{id});}
}
