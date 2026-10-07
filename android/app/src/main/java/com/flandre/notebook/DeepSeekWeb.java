package com.flandre.notebook;

import android.os.SystemClock;
import android.util.Base64;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Personal-account web interoperability, adapted from DeeperSeeker's pinned MIT source. */
final class DeepSeekWeb {
    static final String ORIGIN="https://chat.deepseek.com";
    static final String COMPLETION="/api/v0/chat/completion",UPLOAD="/api/v0/file/upload_file";
    interface Pow {long solve(JSONObject challenge) throws Exception;}
    interface Transport {CloudApi.Reply send(String path,String method,byte[] body,String mime,String token,String proof) throws Exception;}
    final Pow pow;final Transport transport;
    DeepSeekWeb(Pow solver){this(solver,DeepSeekWeb::request);}
    DeepSeekWeb(Pow solver,Transport requests){pow=solver;transport=requests;}
    static String token(String value) throws IOException {String s=value.trim();if(s.length()<8||s.length()>16384||!s.matches("[A-Za-z0-9._~+/=-]+"))throw new IOException("请登录自己的 DeepSeek 网页账号，或填写有效的网页登录 Token。");return s;}
    static JSONObject business(CloudApi.Reply r) throws Exception {
        if(r.code!=200)throw new IOException(r.code==401||r.code==403?"DeepSeek 登录已失效或无权限，请重新登录。":r.code==429?"DeepSeek 暂时限制请求频率，请稍后手动重试。":"DeepSeek 请求未完成（"+r.code+"），草稿已保留。");
        JSONObject object=new JSONObject(new String(r.body,StandardCharsets.UTF_8)),data=object.getJSONObject("data");
        if(object.optInt("code",-1)!=0||data.optInt("biz_code",-1)!=0)throw new IOException("DeepSeek 未确认操作，请检查网页登录状态；不会自动重试。");return data.getJSONObject("biz_data");
    }
    static JSONObject challenge(JSONObject input) throws Exception {
        if(!input.optString("algorithm").equals("DeepSeekHashV1")||!input.optString("challenge").matches("[a-fA-F0-9]{64}")||!input.optString("salt").matches("[A-Za-z0-9_-]{1,128}")||!input.optString("signature").matches("[A-Za-z0-9_-]{1,512}")||!(input.opt("difficulty") instanceof Integer||input.opt("difficulty") instanceof Long)||input.getLong("difficulty")<1||input.getLong("difficulty")>1000000||!(input.opt("expire_at") instanceof Integer||input.opt("expire_at") instanceof Long)||input.getLong("expire_at")<1)throw new IOException("DeepSeek 校验格式变化或计算量超限，请更新应用后再试。");return Notebook.copy(input);
    }
    String proof(String path,String secret) throws Exception {
        if(!path.equals(COMPLETION)&&!path.equals(UPLOAD))throw new IOException("DeepSeek 请求路径无效。");
        JSONObject c=challenge(business(transport.send("/api/v0/chat/create_pow_challenge","POST",new JSONObject().put("target_path",path).toString().getBytes(StandardCharsets.UTF_8),"application/json",secret,null)).getJSONObject("challenge"));
        if(!c.optString("target_path",path).equals(path)||c.getLong("expire_at")<=System.currentTimeMillis())throw new IOException("DeepSeek 校验已到期，请手动重试。");long answer=pow.solve(c);if(answer<0||answer>=c.getLong("difficulty")||c.getLong("expire_at")<=System.currentTimeMillis())throw new IOException("DeepSeek 本机校验未通过，请稍后重试。");
        JSONObject result=new JSONObject().put("algorithm","DeepSeekHashV1").put("challenge",c.getString("challenge")).put("salt",c.getString("salt")).put("answer",answer).put("signature",c.getString("signature")).put("target_path",path);
        return Base64.encodeToString(result.toString().getBytes(StandardCharsets.UTF_8),Base64.NO_WRAP);
    }
    String ask(JSONObject profile,String instruction,String text,byte[] image) throws Exception {
        String secret=token(profile.optString("web_token"));JSONArray files=new JSONArray();
        if(image!=null){if(image.length<1||image.length>CloudApi.MAX_IMAGE)throw new IOException("图片为空或过大。");String boundary="flandre"+CloudApi.id();ByteArrayOutputStream body=new ByteArrayOutputStream();body.write(("--"+boundary+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\"question.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").getBytes(StandardCharsets.UTF_8));body.write(image);body.write(("\r\n--"+boundary+"--\r\n").getBytes(StandardCharsets.UTF_8));
            JSONObject uploaded=business(transport.send(UPLOAD,"POST",body.toByteArray(),"multipart/form-data; boundary="+boundary,secret,proof(UPLOAD,secret)));String fid=uploaded.getString("id");if(!fid.matches("[A-Za-z0-9_-]{1,128}"))throw new IOException("DeepSeek 图片编号无效。");String status=uploaded.optString("status");long deadline=SystemClock.elapsedRealtime()+120000;
            while((status.equals("PENDING")||status.equals("PARSING"))&&SystemClock.elapsedRealtime()<deadline){Thread.sleep(400);JSONArray fetched=business(transport.send("/api/v0/file/fetch_files?file_ids="+fid,"GET",null,"application/json",secret,null)).getJSONArray("files");if(fetched.length()!=1||!fid.equals(fetched.getJSONObject(0).optString("id")))throw new IOException("DeepSeek 图片确认不匹配。");status=fetched.getJSONObject(0).optString("status");}
            if(!status.equals("SUCCESS"))throw new IOException("DeepSeek 图片尚未解析成功，照片仍在草稿中，可稍后手动重试。");files.put(fid);
        }
        JSONObject chat=business(transport.send("/api/v0/chat_session/create","POST",null,"application/json",secret,null));String session=chat.getJSONObject("chat_session").getString("id");if(!session.matches("[A-Za-z0-9_-]{1,128}"))throw new IOException("DeepSeek 会话编号无效。");
        // ponytail: one fresh chat per request; no conversational session pool is needed for study tasks.
        JSONObject request=new JSONObject().put("chat_session_id",session).put("parent_message_id",JSONObject.NULL).put("model_type",JSONObject.NULL).put("prompt",instruction+"\n\n"+text).put("ref_file_ids",files).put("thinking_enabled",false).put("search_enabled",false).put("preempt",false).put("action",JSONObject.NULL);
        CloudApi.Reply response=transport.send(COMPLETION,"POST",request.toString().getBytes(StandardCharsets.UTF_8),"application/json",secret,proof(COMPLETION,secret));if(response.code!=200){business(response);throw new IOException("DeepSeek 未返回结果。");}return stream(new ByteArrayInputStream(response.body));
    }
    static final class Sse {
        final StringBuilder answer=new StringBuilder();boolean finished=false;String fragmentType="",lastPath="",lastOp="APPEND";final Map<String,String> types=new HashMap<>();int fragmentCount=0;
        void append(String s) throws IOException {if(answer.length()+s.length()>2*1024*1024)throw new IOException("DeepSeek 返回内容过长。");answer.append(s);}
        void fragments(JSONArray a) throws Exception {for(int i=0;i<a.length();i++){JSONObject f=a.getJSONObject(i);fragmentType=f.optString("type");types.put(Integer.toString(fragmentCount++),fragmentType);if(fragmentType.equals("RESPONSE"))append(f.optString("content"));}lastPath="";lastOp="APPEND";}
        String type(String path) throws IOException {int index;try{index=Integer.parseInt(path.split("/")[2]);}catch(RuntimeException invalid){throw new IOException("DeepSeek 文本片段格式变化，请更新应用后再试。");}if(index<0)index=fragmentCount+index;String kind=types.get(Integer.toString(index));if(kind==null)throw new IOException("DeepSeek 文本片段不完整，结果未保存。");return kind;}
        void event(JSONObject e) throws Exception {event(e,"");}
        void event(JSONObject e,String base) throws Exception {
            if(e.optString("type").equals("error")||e.has("error"))throw new IOException("DeepSeek 返回错误，原照片和草稿已保留，请手动重试。");
            String path=e.optString("p",lastPath),op=e.optString("o",e.has("p")?"APPEND":lastOp);Object value=e.opt("v");
            if(!base.isEmpty()&&e.has("p")&&!path.equals("response")&&!path.startsWith("response/"))path=base+(path.isEmpty()?"":"/"+path);
            // BATCH child paths are relative to the parent, e.g. response -> fragments.
            if(op.equals("BATCH")&&value instanceof JSONArray){JSONArray a=(JSONArray)value;for(int i=0;i<a.length()&&!finished;i++)event(a.getJSONObject(i),path);return;}
            if(path.equals("response/status")||path.equals("status")){if("CONTENT_FILTER".equals(value))throw new IOException("DeepSeek 未提供完整结果，请调整内容后手动重试。");if("FINISHED".equals(value))finished=true;return;}
            if(value instanceof JSONObject){JSONObject v=(JSONObject)value;if(v.optJSONObject("response")!=null){JSONObject response=v.getJSONObject("response");if(response.optJSONArray("fragments")!=null)fragments(response.getJSONArray("fragments"));if(response.optString("status").equals("CONTENT_FILTER"))throw new IOException("DeepSeek 未提供完整结果。");if(response.optString("status").equals("FINISHED"))finished=true;}return;}
            if(path.equals("response/fragments")&&op.equals("APPEND")&&value instanceof JSONArray){fragments((JSONArray)value);return;}
            if(path.matches("response/fragments/-?\\d+/type")&&value instanceof String){int index=Integer.parseInt(path.split("/")[2]);if(index<0)index=fragmentCount+index;if(index<0||index>=fragmentCount)throw new IOException("DeepSeek 文本片段不完整。");types.put(Integer.toString(index),(String)value);if(index==fragmentCount-1)fragmentType=(String)value;return;}
            if(value instanceof String&&(path.isEmpty()||path.equals("response/content")||path.matches("response/fragments/-?\\d+/content"))){
                if(!op.equals("APPEND"))throw new IOException("DeepSeek 文本更新格式变化，未保存不完整结果。");
                String kind=path.isEmpty()?fragmentType:path.equals("response/content")?"RESPONSE":type(path);
                if(kind.equals("RESPONSE"))append((String)value);lastPath=path;lastOp=op;
            }
        }
        void line(String text) throws Exception {if(!text.startsWith("data:"))return;String data=text.substring(5).trim();if(data.equals("[DONE]")){finished=true;return;}if(data.isEmpty())return;event(new JSONObject(data));}
    }
    static String stream(InputStream in) throws Exception {Sse parser=new Sse();readStream(in,parser,null);if(!parser.finished||parser.answer.toString().trim().isEmpty())throw new IOException("DeepSeek 响应不完整，未收录题目；照片和草稿已保留。");return parser.answer.toString();}
    static void readStream(InputStream in,Sse parser,ByteArrayOutputStream raw) throws Exception {
        ByteArrayOutputStream line=new ByteArrayOutputStream();int c,total=0;long deadline=SystemClock.elapsedRealtime()+180000;
        while(!parser.finished&&(c=in.read())!=-1){if(++total>2*1024*1024||SystemClock.elapsedRealtime()>deadline||line.size()>256*1024)throw new IOException("DeepSeek 响应过长或超时，草稿仍保留。");if(raw!=null)raw.write(c);if(c=='\n'){parser.line(new String(line.toByteArray(),StandardCharsets.UTF_8).trim());line.reset();}else line.write(c);}if(line.size()>0&&!parser.finished)parser.line(new String(line.toByteArray(),StandardCharsets.UTF_8).trim());
    }
    static CloudApi.Reply request(String path,String method,byte[] body,String mime,String secret,String proof) throws Exception {
        if(!Arrays.asList("/api/v0/chat_session/create","/api/v0/chat/create_pow_challenge",COMPLETION,UPLOAD).contains(path)&&!path.matches("/api/v0/file/fetch_files\\?file_ids=[A-Za-z0-9_-]{1,128}"))throw new IOException("DeepSeek 请求路径无效。");HttpURLConnection c=(HttpURLConnection)new URL(ORIGIN+path).openConnection();
        try{c.setInstanceFollowRedirects(false);c.setConnectTimeout(20000);c.setReadTimeout(120000);c.setRequestMethod(method);c.setRequestProperty("Content-Type",mime);c.setRequestProperty("Accept",path.equals(COMPLETION)?"text/event-stream":"application/json");c.setRequestProperty("Authorization","Bearer "+token(secret));c.setRequestProperty("Origin",ORIGIN);c.setRequestProperty("Referer",ORIGIN+"/");c.setRequestProperty("User-Agent","Dalvik/2.1.0 (Linux; U; Android 14; Pixel 7)");c.setRequestProperty("x-client-platform","android");c.setRequestProperty("x-client-version","2.4.5");c.setRequestProperty("x-client-locale","en_US");c.setRequestProperty("x-client-bundle-id","com.deepseek.chat");c.setRequestProperty("x-client-timezone-offset",Integer.toString(TimeZone.getDefault().getOffset(System.currentTimeMillis())/1000));if(proof!=null)c.setRequestProperty("x-ds-pow-response",proof);
            if(body!=null){if(path.equals(UPLOAD)){int start=index(body,"\r\n\r\n".getBytes(StandardCharsets.UTF_8))+4;int tail=("\r\n--"+mime.substring(mime.indexOf("boundary=")+9)+"--\r\n").getBytes(StandardCharsets.UTF_8).length;c.setRequestProperty("x-file-size",Integer.toString(body.length-start-tail));}c.setDoOutput(true);c.setFixedLengthStreamingMode(body.length);try(OutputStream out=c.getOutputStream()){out.write(body);}}
            int status=c.getResponseCode();if(status!=200)return new CloudApi.Reply(status,new byte[0]);try(InputStream in=new BufferedInputStream(c.getInputStream())){if(path.equals(COMPLETION)){ByteArrayOutputStream raw=new ByteArrayOutputStream();readStream(in,new Sse(),raw);return new CloudApi.Reply(status,raw.toByteArray());}return new CloudApi.Reply(status,NotebookBackup.read(in,256*1024));}
        }catch(SocketTimeoutException e){throw new IOException("DeepSeek 连接超时，照片和草稿已保留；请手动重试。");}finally{c.disconnect();}
    }
    static int index(byte[] a,byte[] b){for(int i=0;i<=a.length-b.length;i++){boolean equal=true;for(int j=0;j<b.length;j++)if(a[i+j]!=b[j]){equal=false;break;}if(equal)return i;}return -1;}
}
