package com.flandre.notebook;

import android.content.ContentValues;
import android.database.Cursor;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.*;

/** Transactional JSON snapshot plus content-addressed images; never raw WAL copies. */
final class NotebookBackup {
    static final String[] TABLES={"entries","outbox","drafts","attempts","words","state","imports"};
    static final int MAX_TOTAL=256*1024*1024;
    static byte[] read(InputStream in,int limit) throws Exception {ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){if(out.size()+n>limit)throw new IOException("文件超过手机导入上限。");out.write(b,0,n);}return out.toByteArray();}
    static void export(Notebook book,OutputStream destination) throws Exception {
        synchronized(book){JSONObject manifest=new JSONObject().put("format","flandre-android-notebook").put("version",1).put("owner",book.uid),tables=new JSONObject();
            book.db.beginTransaction();try{for(String table:TABLES){JSONArray rows=new JSONArray();try(Cursor c=book.db.rawQuery("SELECT * FROM "+table,null)){while(c.moveToNext())rows.put(Notebook.row(c));}tables.put(table,rows);}book.db.setTransactionSuccessful();}finally{book.db.endTransaction();}
            manifest.put("tables",tables);Map<String,File> images=new TreeMap<>();File dir=new File(book.root,"images");File[] files=dir.listFiles();if(files!=null)for(File f:files){if(!f.getName().matches("[a-f0-9]{64}\\.(png|jpg|jpeg|webp)")||!f.getCanonicalFile().getParentFile().equals(dir.getCanonicalFile()))throw new IOException("备份图片路径无效。");images.put("images/"+f.getName(),f);}
            JSONArray blobs=new JSONArray();long total=0;for(Map.Entry<String,File> item:images.entrySet()){byte[] content=CloudApi.read(item.getValue(),CloudApi.MAX_IMAGE);String hash=CloudApi.sha(content);if(!item.getValue().getName().startsWith(hash+"."))throw new IOException("本机图片损坏，未完成备份。");blobs.put(new JSONObject().put("path",item.getKey()).put("sha256",hash).put("size",content.length));total+=content.length;if(total>MAX_TOTAL)throw new IOException("备份超过当前手机 256 MB 上限。");}
            manifest.put("files",blobs);byte[] metadata=manifest.toString().getBytes(StandardCharsets.UTF_8);if(metadata.length>16*1024*1024||total+metadata.length>MAX_TOTAL)throw new IOException("备份超过文本 16 MB 或总量 256 MB 上限。");try(ZipOutputStream zip=new ZipOutputStream(destination)){zip.putNextEntry(new ZipEntry("manifest.json"));zip.write(metadata);zip.closeEntry();for(Map.Entry<String,File> item:images.entrySet()){zip.putNextEntry(new ZipEntry(item.getKey()));try(InputStream in=new FileInputStream(item.getValue())){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)zip.write(b,0,n);}zip.closeEntry();}}
        }
    }
    static void validate(Notebook book,JSONObject tables,Map<String,File> files) throws Exception {
        Set<String> entryIds=new HashSet<>();
        for(String table:TABLES)if(tables.getJSONArray(table).length()>20000)throw new IOException("备份记录过多。");
        JSONArray entries=tables.getJSONArray("entries");for(int i=0;i<entries.length();i++){JSONObject e=entries.getJSONObject(i);String id=Notebook.id(e.getString("id"));if(!entryIds.add(id)||e.getLong("revision")<1||e.getLong("base_version")<0||!Arrays.asList(0,1).contains(e.getInt("dirty"))||!Arrays.asList(0,1).contains(e.getInt("deleted")))throw new IOException("备份题目版本无效。");
            if(e.getInt("deleted")==0)checkPayload(book,e.getJSONObject("payload"),id,files);
            JSONObject conflict=e.optJSONObject("conflict");if(conflict!=null&&conflict.length()>0){JSONObject r=book.validateRecord(conflict);if(!r.getString("id").equals(id))throw new IOException("备份冲突归属无效。");if(!r.getBoolean("deleted"))checkPayload(book,r.getJSONObject("payload"),id,files);}
        }
        JSONArray outbox=tables.getJSONArray("outbox");Set<String> operations=new HashSet<>();for(int i=0;i<outbox.length();i++){JSONObject o=outbox.getJSONObject(i);String id=Notebook.id(o.getString("entity_id"));if(!entryIds.contains(id)||!operations.add(Notebook.id(o.getString("operation_id")))||o.getLong("revision")<1||o.getLong("base_version")<0||!Arrays.asList(0,1).contains(o.getInt("deleted")))throw new IOException("备份同步任务无效。");if(o.getInt("deleted")==0)checkPayload(book,o.getJSONObject("payload"),id,files);}
        JSONArray drafts=tables.getJSONArray("drafts");for(int i=0;i<drafts.length();i++){JSONObject d=drafts.getJSONObject(i);Notebook.id(d.getString("id"));JSONObject p=d.getJSONObject("payload");JSONArray images=p.optJSONArray("images");if(images!=null)for(int j=0;j<images.length();j++)checkImage(book,images.getJSONObject(j),files);JSONArray qs=p.optJSONArray("questions");if(qs!=null){if(qs.length()>50)throw new IOException("草稿题目过多。");for(int j=0;j<qs.length();j++){JSONObject q=qs.getJSONObject(j);for(String f:Notebook.FIELDS)if(q.optString(f).length()>20000)throw new IOException("草稿文本过长。");}}if(p.optString("raw").length()>2*1024*1024)throw new IOException("草稿响应过长。");}
        JSONArray state=tables.getJSONArray("state");for(int i=0;i<state.length();i++){JSONObject s=state.getJSONObject(i);if(s.getString("key").equals("owner")&&!book.uid.equals(s.getString("value")))throw new IOException("备份账号无效。");if(s.getString("key").equals("cursor")&&Long.parseLong(s.getString("value"))<0)throw new IOException("备份游标无效。");}
        JSONArray words=tables.getJSONArray("words");for(int i=0;i<words.length();i++){JSONObject w=words.getJSONObject(i);Notebook.id(w.getString("id"));if(w.getString("word").trim().isEmpty()||w.getString("word").length()>300||w.optString("meaning").length()>2000||w.optString("phonetic").length()>300||w.optString("example").length()>4000||!Arrays.asList("mastered","unsure","unknown").contains(w.optString("mastery")))throw new IOException("备份单词无效。");}
        JSONArray attempts=tables.getJSONArray("attempts");for(int i=0;i<attempts.length();i++){JSONObject a=attempts.getJSONObject(i);Notebook.id(a.getString("id"));Notebook.id(a.getString("question_id"));if(!Arrays.asList(0,1).contains(a.getInt("correct"))||!Arrays.asList("mastered","unsure","unknown").contains(a.optString("mastery"))||a.optString("answer").length()>20000)throw new IOException("备份练习记录无效。");}
        JSONArray imports=tables.getJSONArray("imports");for(int i=0;i<imports.length();i++){JSONObject a=imports.getJSONObject(i);Notebook.id(a.getString("source_id"));Notebook.id(a.getString("target_id"));}
    }
    static void checkPayload(Notebook book,JSONObject p,String id,Map<String,File> files) throws Exception {Notebook.payload(p,book.uid,id);JSONArray a=p.getJSONArray("attachments");for(int i=0;i<a.length();i++)checkImage(book,a.getJSONObject(i),files);}
    static void checkImage(Notebook book,JSONObject a,Map<String,File> files) throws Exception {String[] parts=a.getString("key").split("/");if(parts.length!=4)throw new IOException("备份图片归属无效。");Notebook.imageInfo(a,book.uid,Notebook.id(parts[1]));String name="images/"+book.file(a).getName();File source=files.get(name);byte[] b=source==null?null:CloudApi.read(source,CloudApi.MAX_IMAGE);if(b==null||b.length!=a.getLong("size")||!CloudApi.sha(b).equals(a.getString("sha256")))throw new IOException("备份缺少完整原图，未替换题库。");}
    static void restore(Notebook book,InputStream input) throws Exception {
        File staging=new File(book.root,"_restore-"+CloudApi.id());if(!staging.mkdirs())throw new IOException("无法建立恢复校验目录。");
        try{restoreFiles(book,input,staging);}finally{File[] parts=staging.listFiles();if(parts!=null)for(File f:parts)if(f.isFile()&&f.getCanonicalFile().getParentFile().equals(staging.getCanonicalFile()))f.delete();staging.delete();}
    }
    static void restoreFiles(Notebook book,InputStream input,File staging) throws Exception {
        Map<String,File> files=new HashMap<>();Set<String> names=new HashSet<>();JSONObject manifest=null;long total=0;
        try(ZipInputStream zip=new ZipInputStream(input)){ZipEntry entry;while((entry=zip.getNextEntry())!=null){String name=entry.getName();if(!names.add(name)||entry.isDirectory()||(!name.equals("manifest.json")&&!name.matches("images/[a-f0-9]{64}\\.(png|jpg|jpeg|webp)")))throw new IOException("备份路径或格式无效。");byte[] data=read(zip,name.equals("manifest.json")?16*1024*1024:CloudApi.MAX_IMAGE);total+=data.length;if(total>MAX_TOTAL||names.size()>20000)throw new IOException("备份超过当前手机上限。");if(name.equals("manifest.json"))manifest=new JSONObject(new String(data,StandardCharsets.UTF_8));else{File part=new File(staging,name.substring("images/".length()));PhotoQueue.atomic(part,data);files.put(name,part);}}}
        if(manifest==null||!manifest.optString("format").equals("flandre-android-notebook")||manifest.getInt("version")!=1||!manifest.getString("owner").equals(book.uid))throw new IOException("请选择此本机空间或同一账号导出的手机备份。");
        JSONArray blobs=manifest.getJSONArray("files");if(blobs.length()!=files.size())throw new IOException("备份图片清单不完整。");Set<String> listed=new HashSet<>();for(int i=0;i<blobs.length();i++){JSONObject a=blobs.getJSONObject(i);String path=a.getString("path");File blob=files.get(path);byte[] b=blob==null?null:CloudApi.read(blob,CloudApi.MAX_IMAGE);if(!listed.add(path)||b==null||b.length!=a.getLong("size")||!CloudApi.sha(b).equals(a.getString("sha256"))||!path.startsWith("images/"+a.getString("sha256")+"."))throw new IOException("备份图片校验失败。");}
        JSONObject tables=manifest.getJSONObject("tables");validate(book,tables,files);
        // Keep a complete recovery snapshot before changing any current content.
        File backups=new File(book.root,"backups");if(!backups.isDirectory()&&!backups.mkdirs())throw new IOException("无法创建恢复前备份。");try(OutputStream out=new FileOutputStream(new File(backups,"before-restore-"+CloudApi.id()+".zip"))){export(book,out);}
        synchronized(book){
            for(Map.Entry<String,File> f:files.entrySet()){String relative=f.getKey();byte[] content=CloudApi.read(f.getValue(),CloudApi.MAX_IMAGE);File target=new File(book.root,relative);if(!target.getParentFile().isDirectory()&&!target.getParentFile().mkdirs())throw new IOException("无法恢复图片。");if(target.isFile()){if(!Arrays.equals(CloudApi.read(target,CloudApi.MAX_IMAGE),content))throw new IOException("同名图片已损坏，原题库仍保留。");}else PhotoQueue.atomic(target,content);}
            book.db.beginTransaction();try{for(String table:TABLES){String[] columns;try(Cursor c=book.db.rawQuery("SELECT * FROM "+table+" LIMIT 0",null)){columns=c.getColumnNames();}book.db.delete(table,null,null);JSONArray rows=tables.getJSONArray(table);for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);ContentValues values=new ContentValues();for(String k:columns){Object v=row.get(k);if(v==JSONObject.NULL)values.putNull(k);else if(v instanceof Number)values.put(k,((Number)v).longValue());else values.put(k,v.toString());}book.db.insertOrThrow(table,null,values);}}book.db.setTransactionSuccessful();}finally{book.db.endTransaction();}
        }
    }
}
