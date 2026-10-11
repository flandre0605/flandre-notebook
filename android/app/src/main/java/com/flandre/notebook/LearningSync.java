package com.flandre.notebook;

import android.content.ContentValues;
import android.database.Cursor;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.*;

/** Words and immutable history share stable IDs, transactional markers and frozen requests. */
final class LearningSync {
    static final String[] WORD={"word","meaning","phonetic","example","book","mastery","review_count","streak","due_at","last_reviewed_at"};
    static final String[] ATTEMPT={"question_cloud_id","question_stem","question_subject","answered_at","user_answer","result","mastery","duration_seconds","mistake_reason"};
    static void column(Notebook b,String table,String field,String definition){
        try(Cursor c=b.db.rawQuery("PRAGMA table_info("+table+")",null)){while(c.moveToNext())if(c.getString(1).equals(field))return;}
        b.db.execSQL("ALTER TABLE "+table+" ADD COLUMN "+field+" "+definition);
    }
    static void install(Notebook b) throws Exception {
        column(b,"words","book","TEXT NOT NULL DEFAULT ''");column(b,"words","review_count","INTEGER NOT NULL DEFAULT 0");column(b,"words","streak","INTEGER NOT NULL DEFAULT 0");column(b,"words","last_reviewed_at","TEXT");
        for(String f:new String[]{"question_stem","question_subject","result","mistake_reason"})column(b,"attempts",f,"TEXT NOT NULL DEFAULT ''");
        column(b,"attempts","duration_seconds","INTEGER NOT NULL DEFAULT 0");
        b.db.execSQL("CREATE TABLE IF NOT EXISTS learning_entities(id TEXT PRIMARY KEY,kind TEXT NOT NULL,local_id TEXT,revision INTEGER NOT NULL DEFAULT 1,base_version INTEGER NOT NULL DEFAULT 0,dirty INTEGER NOT NULL DEFAULT 1,deleted INTEGER NOT NULL DEFAULT 0,conflict TEXT,payload TEXT NOT NULL DEFAULT '{}')");
        b.db.execSQL("CREATE TABLE IF NOT EXISTS learning_outbox(operation_id TEXT PRIMARY KEY,entity_id TEXT UNIQUE NOT NULL,revision INTEGER NOT NULL,base_version INTEGER NOT NULL,kind TEXT NOT NULL,deleted INTEGER NOT NULL,payload TEXT NOT NULL)");
        if(!b.state("learning_schema","").equals("1")){
            b.db.execSQL("INSERT INTO learning_entities(id,kind,local_id) SELECT id,'word',id FROM words");
            b.db.execSQL("INSERT INTO learning_entities(id,kind,local_id) SELECT id,'attempt',id FROM attempts");
            try(Cursor c=b.db.rawQuery("SELECT id,question_id,correct FROM attempts",null)){while(c.moveToNext()){JSONObject e=b.entry(c.getString(1));JSONObject q=e==null?new JSONObject():e.getJSONObject("payload").optJSONObject("question");if(q==null)q=new JSONObject();b.db.execSQL("UPDATE attempts SET question_stem=?,question_subject=?,result=? WHERE id=?",new Object[]{q.optString("stem"),q.optString("subject"),c.getInt(2)==1?"correct":"incorrect",c.getString(0)});}}
            b.putState("learning_schema","1");b.putState("learning_cursor","0");b.putState("learning_applying","0");
        }
        for(String kind:new String[]{"word","attempt"}){String table=kind.equals("word")?"words":"attempts";
            b.db.execSQL("CREATE TRIGGER IF NOT EXISTS learning_"+kind+"_insert AFTER INSERT ON "+table+" WHEN (SELECT value FROM state WHERE key='learning_applying')='0' BEGIN INSERT INTO learning_entities(id,kind,local_id) VALUES(NEW.id,'"+kind+"',NEW.id); END");
        }
        b.db.execSQL("CREATE TRIGGER IF NOT EXISTS learning_word_update AFTER UPDATE ON words WHEN (SELECT value FROM state WHERE key='learning_applying')='0' BEGIN UPDATE learning_entities SET revision=revision+1,dirty=1,deleted=0 WHERE kind='word' AND local_id=NEW.id; END");
        b.db.execSQL("CREATE TRIGGER IF NOT EXISTS learning_word_delete AFTER DELETE ON words WHEN (SELECT value FROM state WHERE key='learning_applying')='0' BEGIN UPDATE learning_entities SET revision=revision+1,dirty=1,deleted=1,local_id=NULL WHERE kind='word' AND local_id=OLD.id; END");
    }
    static JSONObject validate(String kind,JSONObject p) throws Exception {
        String[] fields=kind.equals("word")?WORD:kind.equals("attempt")?ATTEMPT:null;
        if(fields==null||p==null||p.length()!=fields.length||p.toString().getBytes(StandardCharsets.UTF_8).length>131072)throw new IOException("学习记录格式或长度无效。");
        for(String f:fields){if(!p.has(f))throw new IOException("学习记录字段不完整。");Object v=p.get(f);
            if(Arrays.asList("review_count","streak","duration_seconds").contains(f)){if(!(v instanceof Integer||v instanceof Long)||((Number)v).longValue()<0||((Number)v).longValue()>2147483647L)throw new IOException("学习次数或用时无效。");}
            else if(Arrays.asList("due_at","last_reviewed_at","answered_at").contains(f)){if(kind.equals("word")&&v==JSONObject.NULL)continue;if(!(v instanceof String)||!((String)v).matches("\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}"))throw new IOException("学习记录日期无效。");SimpleDateFormat date=new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.ROOT);date.setLenient(false);date.parse((String)v);}
            else{int max=f.equals("word")||f.equals("phonetic")?300:f.equals("meaning")||f.equals("example")?4000:f.equals("book")?100:20000;if(!(v instanceof String)||((String)v).length()>max||((String)v).indexOf(0)>=0)throw new IOException("学习记录文本无效。");}
        }
        if(!Arrays.asList("unknown","unsure","mastered").contains(p.getString("mastery")))throw new IOException("掌握程度无效。");
        if(kind.equals("word")&&p.getString("word").trim().isEmpty())throw new IOException("单词不能为空。");
        if(kind.equals("attempt")&&(!Arrays.asList("correct","incorrect","skipped").contains(p.getString("result"))||!p.getString("question_cloud_id").matches("[a-f0-9]{32}|")))throw new IOException("作答记录无效。");
        return p;
    }
    static JSONObject record(Notebook b,JSONObject r) throws Exception {
        if(r==null||!r.optString("user_id").equals(b.uid))throw new IOException("学习记录不属于当前账号。");r=Notebook.copy(r).put("id",Notebook.id(r.getString("id")));
        for(String f:new String[]{"version","seq"})if(!(r.opt(f) instanceof Integer||r.opt(f) instanceof Long)||r.getLong(f)<1)throw new IOException("学习记录版本无效。");
        String kind=r.getString("kind");if(!Arrays.asList("word","attempt").contains(kind)||!(r.opt("deleted") instanceof Boolean)||kind.equals("attempt")&&r.getBoolean("deleted"))throw new IOException("学习记录类型无效。");
        JSONObject p=r.getJSONObject("payload");if(r.getBoolean("deleted")){if(p.length()!=0)throw new IOException("删除标记无效。");}else validate(kind,p);return r;
    }
    static JSONObject entity(Notebook b,String id) throws Exception {try(Cursor c=b.db.rawQuery("SELECT * FROM learning_entities WHERE id=?",new String[]{id})){return c.moveToFirst()?Notebook.row(c):null;}}
    static JSONObject content(Notebook b,JSONObject e) throws Exception {
        if(e.getInt("deleted")==1)return new JSONObject();String kind=e.getString("kind");JSONObject p;
        String sql=kind.equals("word")?"SELECT word,meaning,phonetic,example,book,mastery,review_count,streak,due_at,last_reviewed_at FROM words WHERE id=?":
            "SELECT question_id AS question_cloud_id,question_stem,question_subject,time AS answered_at,answer AS user_answer,result,mastery,duration_seconds,mistake_reason FROM attempts WHERE id=?";
        try(Cursor c=b.db.rawQuery(sql,new String[]{e.getString("local_id")})){if(!c.moveToFirst())throw new IOException("待传学习记录不存在。");p=Notebook.row(c);}
        for(String f:kind.equals("word")?new String[]{"due_at","last_reviewed_at"}:new String[]{"answered_at"})if(!p.isNull(f))p.put(f,date(p.getString(f),true));
        return validate(kind,p);
    }
    static String date(String value,boolean toUtc) throws Exception {SimpleDateFormat source=new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.ROOT),target=new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.ROOT);source.setLenient(false);target.setLenient(false);(toUtc?target:source).setTimeZone(TimeZone.getTimeZone("UTC"));return target.format(source.parse(value));}
    static JSONObject prepare(Notebook b) throws Exception {synchronized(b){b.db.beginTransaction();try{
        try(Cursor c=b.db.rawQuery("SELECT o.* FROM learning_outbox o JOIN learning_entities e ON e.id=o.entity_id WHERE e.conflict IS NULL ORDER BY o.rowid LIMIT 1",null)){if(c.moveToFirst()){JSONObject p=Notebook.row(c);b.db.setTransactionSuccessful();return p;}}
        try(Cursor c=b.db.rawQuery("SELECT * FROM learning_entities WHERE dirty=1 AND conflict IS NULL ORDER BY rowid LIMIT 1",null)){if(!c.moveToFirst()){b.db.setTransactionSuccessful();return null;}JSONObject e=Notebook.row(c),p=content(b,e);String op=CloudApi.id();b.db.execSQL("INSERT INTO learning_outbox VALUES(?,?,?,?,?,?,?)",new Object[]{op,e.getString("id"),e.getLong("revision"),e.getLong("base_version"),e.getString("kind"),e.getInt("deleted"),p.toString()});JSONObject out=new JSONObject().put("operation_id",op).put("entity_id",e.getString("id")).put("revision",e.getLong("revision")).put("base_version",e.getLong("base_version")).put("kind",e.getString("kind")).put("deleted",e.getInt("deleted")).put("payload",p);b.db.setTransactionSuccessful();return out;}
    }finally{b.db.endTransaction();}}}
    static int pending(Notebook b){synchronized(b){try(Cursor c=b.db.rawQuery("SELECT count(*) FROM learning_entities WHERE dirty=1 AND conflict IS NULL",null)){c.moveToFirst();return c.getInt(0);}}}
    static void conflict(Notebook b,String id,JSONObject r) throws Exception {if(r==null)throw new IOException("学习冲突缺少原始记录。");synchronized(b){b.db.execSQL("UPDATE learning_entities SET conflict=? WHERE id=?",new Object[]{r.toString(),id});}}
    static void applyOne(Notebook b,JSONObject r,boolean force) throws Exception {
        String id=r.getString("id"),kind=r.getString("kind");JSONObject e=entity(b,id),p=r.getJSONObject("payload");
        if(e!=null&&!e.getString("kind").equals(kind))throw new IOException("学习记录类型发生变化。");
        if(!force&&e!=null&&e.getLong("base_version")>=r.getLong("version"))return;
        if(!force&&e!=null&&(e.getInt("dirty")==1||!e.isNull("conflict"))){conflict(b,id,r);return;}
        String local=e==null||e.isNull("local_id")?null:e.getString("local_id");
        if(kind.equals("word")){
            if(r.getBoolean("deleted")){if(local!=null)b.db.delete("words","id=?",new String[]{local});local=null;}
            else{String duplicate=null;try(Cursor c=b.db.rawQuery("SELECT id FROM words WHERE lower(word)=lower(?)",new String[]{p.getString("word")})){if(c.moveToFirst())duplicate=c.getString(0);}
                if(duplicate!=null&&!duplicate.equals(local)&&!force){if(e==null)b.db.execSQL("INSERT INTO learning_entities(id,kind,local_id,conflict) VALUES(?,'word',?,?)",new Object[]{id,duplicate,r.toString()});else conflict(b,id,r);return;}
                if(duplicate!=null&&!duplicate.equals(local)){if(local!=null)throw new IOException("另一个词条使用相同单词，请先修改词条。");local=duplicate;}
                if(local==null)local=id;ContentValues values=values(p,WORD);for(String f:new String[]{"due_at","last_reviewed_at"})if(!p.isNull(f))values.put(f,date(p.getString(f),false));values.put("id",local);b.db.insertWithOnConflict("words",null,values,android.database.sqlite.SQLiteDatabase.CONFLICT_REPLACE);
            }
        }else if(local==null||force){boolean inserting=local==null;if(inserting)local=id;ContentValues v=new ContentValues();v.put("id",local);v.put("question_id",p.getString("question_cloud_id"));v.put("time",date(p.getString("answered_at"),false));v.put("answer",p.getString("user_answer"));v.put("correct",p.getString("result").equals("correct")?1:0);v.put("mastery",p.getString("mastery"));for(String f:new String[]{"question_stem","question_subject","result","mistake_reason"})v.put(f,p.getString(f));v.put("duration_seconds",p.getLong("duration_seconds"));if(inserting)b.db.insertOrThrow("attempts",null,v);else b.db.update("attempts",v,"id=?",new String[]{local});}
        else if(!CloudApi.same(e.getJSONObject("payload"),p))throw new IOException("已完成的历史不能改写。");
        b.db.execSQL("INSERT OR REPLACE INTO learning_entities(id,kind,local_id,revision,base_version,dirty,deleted,payload) VALUES(?,?,?,1,?,0,?,?)",new Object[]{id,kind,local,r.getLong("version"),r.getBoolean("deleted")?1:0,p.toString()});
    }
    static ContentValues values(JSONObject p,String[] fields) throws Exception {ContentValues v=new ContentValues();for(String f:fields){Object item=p.get(f);if(item==JSONObject.NULL)v.putNull(f);else if(item instanceof Number)v.put(f,((Number)item).longValue());else v.put(f,item.toString());}return v;}
    static void apply(Notebook b,List<JSONObject> rows,long cursor) throws Exception {synchronized(b){b.db.beginTransaction();try{b.putState("learning_applying","1");for(JSONObject r:rows)applyOne(b,r,false);b.putState("learning_cursor",Long.toString(cursor));b.putState("learning_applying","0");b.db.setTransactionSuccessful();}finally{b.db.endTransaction();}}}
    static JSONArray conflicts(Notebook b) throws Exception {synchronized(b){JSONArray rows=new JSONArray();try(Cursor c=b.db.rawQuery("SELECT * FROM learning_entities WHERE conflict IS NOT NULL",null)){while(c.moveToNext()){JSONObject e=Notebook.row(c);e.put("local_payload",content(b,e));rows.put(e);}}return rows;}}
    static void resolve(Notebook b,String id,boolean keep) throws Exception {synchronized(b){b.db.beginTransaction();try{
        JSONObject e=entity(b,id);if(e==null||e.isNull("conflict"))throw new IOException("冲突已变化。");JSONObject r=record(b,e.getJSONObject("conflict")),p=content(b,e);
        File folder=new File(b.root,"learning-conflicts");if(!folder.isDirectory()&&!folder.mkdirs())throw new IOException("无法保存冲突副本。");PhotoQueue.atomic(new File(folder,CloudApi.id()+".json"),new JSONObject().put("local",p).put("remote",r).toString().getBytes(StandardCharsets.UTF_8));
        b.db.delete("learning_outbox","entity_id=?",new String[]{id});b.db.execSQL("UPDATE learning_entities SET local_id=NULL,deleted=1,dirty=1,revision=revision+1,conflict=NULL WHERE kind='word' AND local_id=? AND id<>?",new Object[]{e.optString("local_id"),id});
        if(keep){if(!e.getString("kind").equals("word"))throw new IOException("历史不能改写，请采用云端原记录。");b.db.execSQL("UPDATE learning_entities SET base_version=?,revision=revision+1,dirty=1,conflict=NULL WHERE id=?",new Object[]{r.getLong("version"),id});}
        else{b.putState("learning_applying","1");applyOne(b,r,true);b.putState("learning_applying","0");}b.db.setTransactionSuccessful();
    }finally{b.db.endTransaction();}}}
    static int[] synchronize(Notebook b,CloudApi api,boolean pull) throws Exception {
        int uploaded=0,downloaded=0;for(int n=0;n<200;n++){JSONObject out=prepare(b);if(out==null)break;JSONObject p=out.getJSONObject("payload"),result=api.rpc("flandre_learning_push",new JSONObject().put("p_id",out.getString("entity_id")).put("p_operation_id",out.getString("operation_id")).put("p_kind",out.getString("kind")).put("p_base_version",out.getLong("base_version")).put("p_deleted",out.getInt("deleted")==1).put("p_payload",p));
            JSONObject r=result.optJSONObject("record");if(r!=null){r=record(b,r);if(!r.getString("id").equals(out.getString("entity_id"))||!r.getString("kind").equals(out.getString("kind")))throw new IOException("学习同步确认对应其他记录。");}
            if(result.optString("status").equals("conflict")){conflict(b,out.getString("entity_id"),r);continue;}
            if(!result.optString("status").equals("applied")||r==null||r.getLong("version")!=out.getLong("base_version")+1||r.getBoolean("deleted")!=(out.getInt("deleted")==1)||!CloudApi.same(r.getJSONObject("payload"),p))throw new IOException("云端未确认本轮学习记录，保留原编号重试。");
            synchronized(b){b.db.beginTransaction();try{b.db.execSQL("UPDATE learning_entities SET base_version=?,payload=?,dirty=CASE WHEN revision=? THEN 0 ELSE 1 END WHERE id=?",new Object[]{r.getLong("version"),p.toString(),out.getLong("revision"),out.getString("entity_id")});b.db.delete("learning_outbox","operation_id=?",new String[]{out.getString("operation_id")});b.db.setTransactionSuccessful();}finally{b.db.endTransaction();}}uploaded++;
        }
        if(!pull)return new int[]{uploaded,0};for(int n=0;n<200;n++){long cursor=Long.parseLong(b.state("learning_cursor","0"));JSONObject page=api.rpc("flandre_learning_pull",new JSONObject().put("p_after",cursor).put("p_limit",5));JSONArray rows=page.getJSONArray("records");if(rows.length()>5||!(page.opt("cursor") instanceof Integer||page.opt("cursor") instanceof Long))throw new IOException("学习分页无效。");List<JSONObject> prepared=new ArrayList<>();for(int i=0;i<rows.length();i++){JSONObject r=record(b,rows.getJSONObject(i));if(r.getLong("seq")<=cursor)throw new IOException("学习变更顺序无效。");cursor=r.getLong("seq");prepared.add(r);}if(page.getLong("cursor")!=cursor)throw new IOException("学习游标无效。");apply(b,prepared,cursor);downloaded+=rows.length();if(rows.length()<5)return new int[]{uploaded,downloaded};}
        throw new IOException("本轮学习变化超过 1000 项，请继续同步。");
    }
}
