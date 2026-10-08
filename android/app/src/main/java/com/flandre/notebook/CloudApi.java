package com.flandre.notebook;

import android.os.SystemClock;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Ordinary account requests only; no admin secret; only refresh credentials may be saved with Android Keystore. */
final class CloudApi {
    static final String BASE="https://flandre-d5gtb0c714184017a.api.tcloudbasegateway.com";
    static final int MAX_IMAGE=20*1024*1024;
    final String uid, username;
    private String token;
    long expires;
    String refresh="", device="";
    CloudLoginStore store;
    private boolean closed;
    interface Transport {Reply send(String path,String method,byte[] body,String mime,String token,String device,int limit) throws IOException;}
    private final Transport transport;
    private CloudApi(String u,String name,String t,long seconds) {
        this(u,name,t,seconds,CloudApi::request);
    }
    CloudApi(String u,String name,String t,long seconds,Transport requests) {
        uid=u; username=name; token=t; expires=SystemClock.elapsedRealtime()+seconds*1000;
        transport=requests;
    }
    synchronized void close() { closed=true;token=refresh=""; }
    synchronized void logout() throws IOException {close();if(store!=null)store.clear(uid);}
    synchronized String bearer() throws IOException {return bearer(null);}
    private synchronized String bearer(String rejected) throws IOException {
        if(closed)throw new IOException("账号已关闭，请重新登录。");
        if((token.isEmpty()||SystemClock.elapsedRealtime()>=expires-60000||rejected!=null&&rejected.equals(token))&&!refresh.isEmpty()){
            try {
                JSONObject result=auth("token",new JSONObject().put("grant_type","refresh_token").put("refresh_token",refresh),device,transport);
                CloudApi next=session(result,username);
                if(!uid.equals(next.uid)||next.refresh.isEmpty())throw new LoginExpired();
                token=next.token;refresh=next.refresh;expires=next.expires;next.close();
                if(store!=null)try{store.save(this);}catch(IOException error){store.clear(uid);throw error;}
            }catch(LoginExpired error){logout();throw error;}
            catch(JSONException error){throw new IOException("续期响应无效，请重新登录。原题库已保留。");}
        }
        if(token.isEmpty()||SystemClock.elapsedRealtime()>=expires)throw new IOException("登录已到期，请重新登录。上传队列会保留。");
        return token;
    }
    Reply authenticated(String path,String method,byte[] body,String mime,int limit) throws IOException {
        String current=bearer();Reply reply=transport.send(path,method,body,mime,current,null,limit);
        if(reply.code==401&&!refresh.isEmpty())reply=transport.send(path,method,body,mime,bearer(current),null,limit);
        return reply;
    }
    static final class LoginExpired extends IOException {LoginExpired(){super("登录已失效，请重新登录。本地题库和待同步修改已保留。");}}
    static CloudApi login(String name,String password,String device) throws Exception {
        JSONObject args=new JSONObject().put("username",name).put("password",password);
        CloudApi api=session(auth("signin",args,device,CloudApi::request),name);api.device=device;return api;
    }
    static CloudApi session(JSONObject result,String name) throws IOException {
        String uid=result.optString("sub"),token=result.optString("access_token");
        long seconds=result.optLong("expires_in");
        if(!(result.opt("sub") instanceof String)||!(result.opt("access_token") instanceof String)||!uid.matches("[A-Za-z0-9_-]{1,64}")||token.isEmpty()||token.length()>4096||!"bearer".equalsIgnoreCase(result.optString("token_type"))||!(result.opt("expires_in") instanceof Integer||result.opt("expires_in") instanceof Long)||seconds<=0||seconds>86400)
            throw new IOException("登录响应无效。");
        String refresh=result.optString("refresh_token","");
        if(result.has("refresh_token")&&(!(result.opt("refresh_token") instanceof String)||refresh.isEmpty()||refresh.length()>4096))throw new IOException("续期凭据无效。");
        CloudApi api=new CloudApi(uid,name,token,seconds);api.refresh=refresh;return api;
    }
    static JSONObject auth(String path,JSONObject args,String device,Transport requests) throws IOException {
        Reply reply=requests.send("/auth/v1/"+path,"POST",args.toString().getBytes(StandardCharsets.UTF_8),"application/json",null,device,128*1024);
        JSONObject result;try{result=new JSONObject(new String(reply.body,StandardCharsets.UTF_8));}catch(JSONException e){throw new IOException("账号响应无法识别，尚未确认完成。注册时请先尝试登录。 ");}
        if(reply.code!=200||result.has("error")){
            String code=result.optString("error"),message;
            switch(code){
                case "invalid_grant":case "invalid_refresh_token":case "unauthenticated":throw new LoginExpired();
                case "invalid_verification_code":message="验证码不正确，请检查后重试。";break;
                case "verification_code_expired":case "verification_expired":case "invalid_verification_token":message="邮箱验证已失效，请重新获取验证码。";break;
                case "email_already_exists":case "email_exists":message="此邮箱已注册，请返回登录。";break;
                case "username_already_exists":case "username_exists":message="用户名已被使用，请换一个。";break;
                case "already_exists":message="邮箱或用户名已被使用，请尝试登录或更换。";break;
                case "rate_limit_exceeded":case "resource_exhausted":message="请求过于频繁，请稍后再试。";break;
                case "captcha_required":message="云端要求额外的人机验证，本版暂不支持此验证，请稍后再试。";break;
                case "unimplemented":message="云端未启用此方式。请管理员开启邮箱验证码及用户名密码登录。";break;
                case "weak_password":message="密码未达到云端强度要求，请使用更强的密码。";break;
                case "invalid_username_or_password":message="用户名或密码不正确。";break;
                default:message="云端未接受账号请求，请检查信息和配置。注册时请先尝试登录，避免重复提交。";
            }
            throw new IOException(message); // Never echo arbitrary server descriptions or credentials.
        }return result;
    }
    static String registrationFields(String email,String name,String password) throws IOException {
        email=email.trim();if(email.length()>254||!email.matches("[^\\s@]+@[^\\s@]+\\.[^\\s@]+"))throw new IOException("请填写有效的邮箱地址。");
        if(name!=null&&!name.matches("[A-Za-z0-9_-]{5,24}"))throw new IOException("用户名需为 5～24 位字母、数字、下划线或短横线。");
        if(password!=null&&(password.length()<8||password.length()>32||!password.matches("(?s).*[A-Za-z].*")||!password.matches("(?s).*[0-9].*")))throw new IOException("密码需为 8～32 位，包含字母和数字。");return email;
    }
    static EmailChallenge sendRegistrationCode(String email,String device) throws Exception {return sendRegistrationCode(email,device,CloudApi::request);}
    static EmailChallenge sendRegistrationCode(String email,String device,Transport requests) throws Exception {
        email=registrationFields(email,null,null);JSONObject response=auth("verification",new JSONObject().put("email",email).put("target","ANY"),device,requests);
        if(response.optBoolean("is_user"))throw new IOException("此邮箱已注册，请返回登录。");return new EmailChallenge(email,response,requests);
    }
    static final class EmailChallenge {
        final String email;final long deadline;final Transport requests;String identity;
        EmailChallenge(String e,JSONObject result,Transport transport) throws IOException {
            email=e;requests=transport;identity=result.optString("verification_id");long seconds=result.optLong("expires_in");
            if(!(result.opt("verification_id") instanceof String)||identity.isEmpty()||identity.length()>4096||!(result.opt("expires_in") instanceof Integer||result.opt("expires_in") instanceof Long)||seconds<=0||seconds>3600)throw new IOException("验证码发送响应无效，请稍后重新获取。");deadline=SystemClock.elapsedRealtime()+seconds*1000;
        }
        CloudApi signup(String currentEmail,String name,String password,String code,String device) throws Exception {
            currentEmail=registrationFields(currentEmail,name,password);
            if(!email.equals(currentEmail)||identity.isEmpty()||SystemClock.elapsedRealtime()>=deadline)throw new IOException("请为当前邮箱重新获取验证码。");
            if(!code.matches("[0-9]{6}"))throw new IOException("请输入邮件中的 6 位数字验证码。");
            JSONObject verified=auth("verification/verify",new JSONObject().put("verification_id",identity).put("verification_code",code),device,requests);String token=verified.optString("verification_token");
            if(!(verified.opt("verification_token") instanceof String)||token.isEmpty()||token.length()>4096)throw new IOException("邮箱验证响应无效，请重新获取验证码。");identity="";
            try{CloudApi api=session(auth("signup",new JSONObject().put("email",email).put("username",name).put("password",password).put("verification_token",token),device,requests),name);api.device=device;return api;}
            catch(IOException e){throw new IOException(e.getMessage()+" 若注册已成功请先登录；继续注册需重新获取验证码。");}
        }
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
        if(!Arrays.asList("flandre_inbox_submit","flandre_inbox_pull","flandre_sync_pull","flandre_sync_push").contains(name))throw new IOException("接口无效。");
        Reply r=authenticated("/v1/rdb/rest/rpc/"+name,"POST",args.toString().getBytes(StandardCharsets.UTF_8),"application/json",2*1024*1024);
        if(r.code!=200)throw new IOException(r.code==404?"图片接收服务暂不可用，请稍后重试。":r.code==401||r.code==403?"请重新登录并检查此账号的权限。":"云端暂未完成操作，请重试（"+r.code+"）。");
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
        Reply r=authenticated(path,"POST",content,image.getString("mime_type"),128*1024);
        if(r.code!=200&&r.code!=409)throw new IOException("图片上传未完成，可稍后重试（"+r.code+"）。");
        Reply downloaded=authenticated(path,"GET",null,"application/json",MAX_IMAGE);
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
        if(a instanceof Number&&b instanceof Number)return new java.math.BigDecimal(a.toString()).compareTo(new java.math.BigDecimal(b.toString()))==0;
        if(a instanceof JSONObject&&b instanceof JSONObject){JSONObject x=(JSONObject)a,y=(JSONObject)b;if(x.length()!=y.length())return false;Iterator<String> keys=x.keys();while(keys.hasNext()){String k=keys.next();if(!y.has(k)||!same(x.get(k),y.get(k)))return false;}return true;}
        if(a instanceof JSONArray&&b instanceof JSONArray){JSONArray x=(JSONArray)a,y=(JSONArray)b;if(x.length()!=y.length())return false;for(int i=0;i<x.length();i++)if(!same(x.get(i),y.get(i)))return false;return true;}
        return Objects.equals(a,b);
    }
    String questionPath(JSONObject image,String question) throws Exception {
        Notebook.imageInfo(image,uid,Notebook.id(question));return "/v1/storages/object/flandre-question-images/"+image.getString("key");
    }
    void uploadQuestion(String question,JSONObject image,File file) throws Exception {
        byte[] content=read(file,MAX_IMAGE);if(content.length!=image.getLong("size")||!sha(content).equals(image.getString("sha256")))throw new IOException("原图缺失或损坏，保留同步队列。");
        String path=questionPath(image,question);Reply r=authenticated(path,"POST",content,image.getString("mime_type"),128*1024);
        if(r.code!=200&&r.code!=409)throw new IOException("题目原图上传失败，可稍后重试（"+r.code+"）。");
        Reply read=authenticated(path,"GET",null,"application/json",MAX_IMAGE);
        if(read.code!=200||!Arrays.equals(content,read.body))throw new IOException("原图校验失败，未提交题目。");
    }
    byte[] downloadQuestion(String question,JSONObject image) throws Exception {
        Reply r=authenticated(questionPath(image,question),"GET",null,"application/json",MAX_IMAGE);
        if(r.code!=200)throw new IOException("题目原图下载失败（"+r.code+"），未推进同步。");return r.body;
    }
}
