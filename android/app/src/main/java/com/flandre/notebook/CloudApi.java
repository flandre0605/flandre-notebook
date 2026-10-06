package com.flandre.notebook;

import android.os.SystemClock;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Ordinary account requests only; no admin secret, logging or persisted token. */
final class CloudApi {
    static final String BASE="https://flandre-d5gtb0c714184017a.api.tcloudbasegateway.com";
    static final int MAX_IMAGE=20*1024*1024;
    final String uid, username;
    private String token;
    private final long expires;
    interface Transport {Reply send(String path,String method,byte[] body,String mime,String token,String device,int limit) throws IOException;}
    private final Transport transport;
    private CloudApi(String u,String name,String t,long seconds) {
        this(u,name,t,seconds,CloudApi::request);
    }
    CloudApi(String u,String name,String t,long seconds,Transport requests) {
        uid=u; username=name; token=t; expires=SystemClock.elapsedRealtime()+seconds*1000;
        transport=requests;
    }
    synchronized void close() { token=""; }
    synchronized String bearer() throws IOException {
        if(token.isEmpty()||SystemClock.elapsedRealtime()>=expires) throw new IOException("登录已到期，请重新登录。上传队列会保留。");
        return token;
    }
    static CloudApi login(String name,String password,String device) throws Exception {
        JSONObject args=new JSONObject().put("username",name).put("password",password);
        Reply r=request("/auth/v1/signin","POST",args.toString().getBytes(StandardCharsets.UTF_8),"application/json",null,device,128*1024);
        JSONObject result=new JSONObject(new String(r.body,StandardCharsets.UTF_8));
        if(r.code!=200||result.has("error")) throw new IOException("登录失败，请检查用户名、密码及网络后重试。");
        String uid=result.optString("sub"),token=result.optString("access_token");
        long seconds=result.optLong("expires_in");
        if(!uid.matches("[A-Za-z0-9_-]{1,64}")||token.isEmpty()||!"bearer".equalsIgnoreCase(result.optString("token_type"))||seconds<=0||seconds>86400)
            throw new IOException("登录响应无效。");
        return new CloudApi(uid,name,token,seconds);
    }
    static final class Reply { final int code; final byte[] body; Reply(int c,byte[] b){code=c;body=b;} }
    static Reply request(String path,String method,byte[] data,String mime,String token,String device,int limit) throws IOException {
        if(!path.startsWith("/")||path.contains("..")||path.contains("?")) throw new IOException("请求路径无效。");
        HttpURLConnection c=(HttpURLConnection)new URL(BASE+path).openConnection();
        try {
            c.setInstanceFollowRedirects(false); c.setConnectTimeout(20000);c.setReadTimeout(30000);
            c.setRequestMethod(method);c.setRequestProperty("Content-Type",mime);c.setRequestProperty("Cache-Control","no-store");
            if(token!=null)c.setRequestProperty("Authorization","Bearer "+token);
            if(device!=null)c.setRequestProperty("x-device-id",device);
            if(data!=null){c.setDoOutput(true);c.setFixedLengthStreamingMode(data.length);try(OutputStream out=c.getOutputStream()){out.write(data);}}
            int status=c.getResponseCode();InputStream input=status<400?c.getInputStream():c.getErrorStream();
            if(input==null)return new Reply(status,new byte[0]);
            try(InputStream in=input;ByteArrayOutputStream out=new ByteArrayOutputStream()) {
                byte[] buffer=new byte[8192];int n;
                while((n=in.read(buffer))!=-1){if(out.size()+n>limit)throw new IOException("云端响应过大，未确认完成。");out.write(buffer,0,n);}
                return new Reply(status,out.toByteArray());
            }
        } catch(SocketTimeoutException e){throw new IOException("连接超时，已保存的任务可稍后重试。");}
        finally{c.disconnect();}
    }
    JSONObject rpc(String name,JSONObject args) throws Exception {
        if(!Arrays.asList("flandre_inbox_submit","flandre_inbox_pull","flandre_sync_pull").contains(name))throw new IOException("接口无效。");
        Reply r=transport.send("/v1/rdb/rest/rpc/"+name,"POST",args.toString().getBytes(StandardCharsets.UTF_8),"application/json",bearer(),null,2*1024*1024);
        if(r.code!=200)throw new IOException(r.code==404?"云端尚未部署手机待整理脚本，请在电脑端复制 005 脚本执行。":r.code==401||r.code==403?"请重新登录并检查此账号的权限。":"云端暂未完成操作，请重试（"+r.code+"）。");
        return new JSONObject(new String(r.body,StandardCharsets.UTF_8));
    }
    String objectPath(JSONObject image,String receipt) throws Exception {
        String key=image.getString("key"),aid=image.getString("id"),hash=image.getString("sha256");
        if(!receipt.matches("[a-f0-9]{32}")||!aid.matches("[a-f0-9]{32}")||!hash.matches("[a-f0-9]{64}")||
           !key.matches(java.util.regex.Pattern.quote(uid+"/"+receipt+"/"+aid+"/"+hash)+"\\.(png|jpg|jpeg|webp)"))throw new IOException("图片路径不属于当前账号。");
        return "/v1/storages/object/flandre-inbox-images/"+key;
    }
    void upload(String receipt,JSONObject image,File file) throws Exception {
        byte[] content=read(file,MAX_IMAGE);
        if(content.length!=image.getInt("size")||!sha(content).equals(image.getString("sha256")))throw new IOException("本地原图已变化，未上传。");
        String path=objectPath(image,receipt);
        Reply r=transport.send(path,"POST",content,image.getString("mime_type"),bearer(),null,128*1024);
        if(r.code!=200&&r.code!=409)throw new IOException("图片上传未完成，可稍后重试（"+r.code+"）。");
        Reply downloaded=transport.send(path,"GET",null,"application/json",bearer(),null,MAX_IMAGE);
        if(downloaded.code!=200||!Arrays.equals(content,downloaded.body))throw new IOException("云端图片校验未通过，任务已保留。");
    }
    static byte[] read(File file,int limit) throws IOException {
        if(!file.isFile()||file.length()<1||file.length()>limit)throw new IOException("文件缺失或超过大小限制。");
        try(InputStream in=new FileInputStream(file);ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1){if(out.size()+n>limit)throw new IOException("文件过大。");out.write(buffer,0,n);}return out.toByteArray();
        }
    }
    static String sha(byte[] content) throws Exception {
        StringBuilder s=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(content))s.append(String.format(Locale.ROOT,"%02x",b&255));return s.toString();
    }
    static String id(){return UUID.randomUUID().toString().replace("-","");}
    static boolean same(Object a,Object b) throws JSONException {
        if(a instanceof JSONObject&&b instanceof JSONObject){JSONObject x=(JSONObject)a,y=(JSONObject)b;if(x.length()!=y.length())return false;Iterator<String> keys=x.keys();while(keys.hasNext()){String k=keys.next();if(!y.has(k)||!same(x.get(k),y.get(k)))return false;}return true;}
        if(a instanceof JSONArray&&b instanceof JSONArray){JSONArray x=(JSONArray)a,y=(JSONArray)b;if(x.length()!=y.length())return false;for(int i=0;i<x.length();i++)if(!same(x.get(i),y.get(i)))return false;return true;}
        return Objects.equals(a,b);
    }
}
