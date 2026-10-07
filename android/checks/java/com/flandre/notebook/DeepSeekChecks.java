package com.flandre.notebook;

import android.app.Activity;
import android.graphics.Bitmap;
import android.net.Uri;
import android.util.Base64;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Local protocol fixtures and the real offline WASM worker; no account or upstream requests. */
final class DeepSeekChecks {
    final NativeChecks c;
    DeepSeekChecks(NativeChecks checks){c=checks;}
    void reject(NotebookChecks.Call action,String label) throws Exception {boolean failed=false;try{action.run();}catch(Exception expected){failed=true;}c.check(failed,label);}
    static JSONObject challenge() throws Exception {return new JSONObject().put("algorithm","DeepSeekHashV1").put("challenge","34d4c336676aa2e83c3308148e12ba8bc5e77ccb2fc12eeea1046e20c4c64eec").put("salt","6c3a962c828dd81d7d69").put("signature","f68a3f7b13fde1a3c5f484869bed76d82160e39b401172865e31485219682b74").put("difficulty",144000).put("expire_at",1780227446451L);}
    static CloudApi.Reply reply(JSONObject value) throws Exception {return new CloudApi.Reply(200,value.toString().getBytes(StandardCharsets.UTF_8));}
    static CloudApi.Reply business(JSONObject value) throws Exception {return reply(new JSONObject().put("code",0).put("data",new JSONObject().put("biz_code",0).put("biz_data",value)));}
    static final class Server implements DeepSeekWeb.Transport {
        int chats=0,uploads=0,proofs=0;boolean authError=false,expired=false;final List<JSONObject> messages=new ArrayList<>();
        public CloudApi.Reply send(String path,String method,byte[] body,String mime,String token,String proof) throws Exception {
            if(authError)return new CloudApi.Reply(401,new byte[0]);if(!token.equals("synthetic-test-token"))throw new AssertionError("Unexpected token");
            if(path.equals("/api/v0/chat/create_pow_challenge")){proofs++;JSONObject request=new JSONObject(new String(body,StandardCharsets.UTF_8));return business(new JSONObject().put("challenge",challenge().put("expire_at",expired?1L:System.currentTimeMillis()+60000).put("target_path",request.getString("target_path"))));}
            if(path.equals(DeepSeekWeb.UPLOAD)){uploads++;JSONObject p=new JSONObject(new String(Base64.decode(proof,Base64.NO_WRAP),StandardCharsets.UTF_8));if(!p.getString("target_path").equals(path)||p.getLong("answer")!=86022||!mime.startsWith("multipart/form-data; boundary="))throw new AssertionError("Bad upload proof");return business(new JSONObject().put("id","file_fixture").put("status","PARSING"));}
            if(path.startsWith("/api/v0/file/fetch_files?"))return business(new JSONObject().put("files",new JSONArray().put(new JSONObject().put("id","file_fixture").put("status","SUCCESS"))));
            if(path.equals("/api/v0/chat_session/create"))return business(new JSONObject().put("chat_session",new JSONObject().put("id","session_"+(++chats))));
            if(path.equals(DeepSeekWeb.COMPLETION)){JSONObject request=new JSONObject(new String(body,StandardCharsets.UTF_8));messages.add(request);JSONObject p=new JSONObject(new String(Base64.decode(proof,Base64.NO_WRAP),StandardCharsets.UTF_8));if(!p.getString("target_path").equals(path)||p.getLong("answer")!=86022)throw new AssertionError("Bad completion proof");String json="{\"questions\":[{\"stem\":\"手机题目\",\"options\":{},\"answer\":\"0\",\"explanation\":\"说明\"}]}";String sse="data: "+new JSONObject().put("p","response/fragments").put("o","APPEND").put("v",new JSONArray().put(new JSONObject().put("type","RESPONSE").put("content",json)))+"\n\ndata: {\"p\":\"response/status\",\"v\":\"FINISHED\"}\n";return new CloudApi.Reply(200,sse.getBytes(StandardCharsets.UTF_8));}
            throw new AssertionError("Unexpected path");
        }
    }
    static String stream(String s) throws Exception {return DeepSeekWeb.stream(new ByteArrayInputStream(s.getBytes(StandardCharsets.UTF_8)));}
    void run() throws Exception {
        Server server=new Server();DeepSeekWeb client=new DeepSeekWeb(challenge->86022,server);JSONObject profile=new JSONObject().put("web_token","synthetic-test-token");String raw=client.ask(profile,AiClient.RECOGNITION,"image",c.image(Bitmap.CompressFormat.JPEG));c.check(AiClient.parse(raw).length()==1&&server.uploads==1&&server.messages.get(0).getJSONArray("ref_file_ids").getString(0).equals("file_fixture"),"native DeepSeek mock uploads image with proof and parses only confirmed file");client.ask(profile,"words","word",null);c.check(server.chats==2&&server.proofs==3&&server.messages.get(1).getJSONArray("ref_file_ids").length()==0&&server.messages.get(0).isNull("parent_message_id"),"each DeepSeek task uses independent chat; no image reused for words");
        server.authError=true;reject(()->client.ask(profile,"words","word",null),"expired DeepSeek login fails without retries");c.check(server.chats==2,"expired auth never sends model task");server.authError=false;server.expired=true;reject(()->client.ask(profile,"words","word",null),"expired proof cannot send completion");
        reject(()->DeepSeekWeb.token("raw\nsecret"),"web token header injection refused");reject(()->DeepSeekWeb.challenge(challenge().put("difficulty",1000001)),"unbounded phone computation refused");reject(()->DeepSeekWeb.challenge(challenge().put("algorithm","unknown")),"unknown challenge algorithm fails closed");
        String s="data: {\"p\":\"response/fragments\",\"o\":\"APPEND\",\"v\":[{\"type\":\"THINK\",\"content\":\"secret thought\"},{\"type\":\"RESPONSE\",\"content\":\"你\"}]}\n"+
            "data: {\"p\":\"response/fragments/1/content\",\"o\":\"APPEND\",\"v\":\"好\"}\n"+"data: {\"v\":\"！\"}\n"+"data: {\"p\":\"response/status\",\"v\":\"FINISHED\"}";
        c.check(stream(s).equals("你好！"),"SSE keeps UTF8 and compact continuation while excluding thinking");String batch="data: {\"o\":\"BATCH\",\"v\":[{\"p\":\"quasi_status\",\"v\":\"FINISHED\"},{\"p\":\"response/fragments\",\"o\":\"APPEND\",\"v\":[{\"type\":\"RESPONSE\",\"content\":\"final\"}]}]}\ndata: {\"p\":\"response/status\",\"v\":\"FINISHED\"}\n";c.check(stream(batch).equals("final"),"SSE batch completion marker does not truncate final answer");
        reject(()->stream("data: {\"p\":\"response/fragments\",\"o\":\"APPEND\",\"v\":[{\"type\":\"RESPONSE\",\"content\":\"partial\"}]}\n"),"incomplete response cannot be treated as completed draft");reject(()->stream("data: {\"type\":\"error\",\"content\":\"synthetic\"}\n"),"SSE service error cannot become a question");reject(()->stream("data: {\"p\":\"response/status\",\"v\":\"FINISHED\"}\n"),"empty completed response refused");
        c.check(AiClient.object("```json\n{\"words\":[{\"word\":\"limit\",\"meaning\":\"极限\"}]}\n```").getJSONArray("words").length()==1,"word AI accepts complete fenced JSON from native web provider");
        String words="{\"words\":[{\"word\":\"limit\",\"meaning\":\"n. 极限\",\"example\":\"a limit\"}]}";
        String prefix="data: "+new JSONObject().put("v",new JSONObject().put("response",new JSONObject().put("fragments",new JSONArray().put(new JSONObject().put("type","RESPONSE").put("content",words.substring(0,2))))))+"\r\n\r\n";
        String tail="data: "+new JSONObject().put("p","response/fragments/-1/content").put("o","APPEND").put("v",words.substring(2,15))+"\n\ndata: "+new JSONObject().put("v",words.substring(15))+"\n\ndata: {\"p\":\"response/status\",\"o\":\"SET\",\"v\":\"FINISHED\"}\n";
        c.check(stream(prefix+tail).equals(words)&&AiClient.words(stream(prefix+tail)).getJSONObject(0).getString("meaning").equals("n. 极限"),"negative last-fragment index reconstructs complete word JSON instead of only its opening brace and quote");
        ByteArrayOutputStream wire=new ByteArrayOutputStream();DeepSeekWeb.readStream(new ByteArrayInputStream((prefix+tail).getBytes(StandardCharsets.UTF_8)),new DeepSeekWeb.Sse(),wire);c.check(DeepSeekWeb.stream(new ByteArrayInputStream(wire.toByteArray())).equals(words),"HTTP stream capture and second-pass parser keep the complete negative-index response");
        String relative="data: {\"v\":{\"response\":{\"fragments\":[]}}}\n"+"data: "+new JSONObject().put("p","response").put("o","BATCH").put("v",new JSONArray().put(new JSONObject().put("p","fragments").put("o","APPEND").put("v",new JSONArray().put(new JSONObject().put("type","THINK").put("content","private reasoning")))).put(new JSONObject().put("p","fragments").put("o","APPEND").put("v",new JSONArray().put(new JSONObject().put("type","RESPONSE").put("content",words.substring(0,2))))).put(new JSONObject().put("p","has_pending_fragment").put("o","SET").put("v",false)))+"\n"+tail;
        c.check(stream(relative).equals(words),"relative batch children initialize fragments without mixing metadata or thinking into content");
        String negativeTwo="data: {\"p\":\"response/fragments\",\"o\":\"APPEND\",\"v\":[{\"type\":\"THINK\",\"content\":\"hidden\"},{\"type\":\"RESPONSE\",\"content\":\"a\"},{\"type\":\"THINK\",\"content\":\"hidden\"}]}\ndata: {\"p\":\"response/fragments/-2/content\",\"o\":\"APPEND\",\"v\":\"b\"}\ndata: {\"p\":\"response\",\"o\":\"BATCH\",\"v\":[{\"p\":\"status\",\"v\":\"FINISHED\"}]}\n";
        c.check(stream(negativeTwo).equals("ab"),"negative indices resolve from actual fragment count and relative batch status completes stream");
        c.check(stream("data: {\"p\":\"response/content\",\"o\":\"APPEND\",\"v\":\"a\"}\ndata: {\"v\":\" b\"}\ndata: {\"p\":\"response/status\",\"v\":\"FINISHED\"}\n").equals("a b"),"normal content path preserves bare token continuation and spaces");
        reject(()->stream(prefix+"data: {\"p\":\"response/status\",\"v\":\"CONTENT_FILTER\"}\n"),"filtered prefix cannot count as a completed result");
        reject(()->stream("data: {\"p\":\"response/fragments/-1/content\",\"o\":\"APPEND\",\"v\":\"unknown fragment\"}\ndata: {\"p\":\"response/status\",\"v\":\"FINISHED\"}\n"),"unknown fragment identity fails instead of silently discarding body");
        reject(()->AiClient.words("{\""),"word review rejects truncated opening JSON");reject(()->AiClient.words("{\"words\":[]}"),"empty word completion is not a successful review");reject(()->AiClient.words("{\"words\":[{\"word\":\"limit\",\"meaning\":null}]}"),"word fields cannot coerce null or structured content into visible text");
        c.check(DeepSeekLogin.official(Uri.parse("https://chat.deepseek.com/"))&&!DeepSeekLogin.official(Uri.parse("https://chat.deepseek.com.evil.example/"))&&!DeepSeekLogin.official(Uri.parse("http://chat.deepseek.com/")),"login top-level navigation confines credentials to first-party HTTPS");
    }
    void ui(Activity activity) throws Exception {
        MainActivity main=(MainActivity)activity;DeepSeekPow solver=new DeepSeekPow(main);try{c.check(solver.solve(challenge())==86022,"real Android Web Worker WASM matches upstream public reference answer");c.check(solver.solve(challenge())==86022,"sequential native proof requests do not share worker state or leave stale jobs");}finally{solver.close();}
        c.runOnMainSync(()->{try{String owner="WEB_UI_"+CloudApi.id();main.openWorkspace(owner);JSONObject profile=new JSONObject().put("url","").put("model","").put("key","").put("provider","deepseek_web").put("web_token","synthetic-test-token");ModelProfile.write(main,owner,profile);c.check(ModelProfile.read(main,owner).getString("web_token").equals("synthetic-test-token")&&!main.getSharedPreferences("models",0).getString(owner,"").contains("synthetic-test-token"),"web login survives encrypted settings roundtrip with no plaintext token");main.screens.modelSettings();c.check(c.findText(main.getWindow().getDecorView(),"DeepSeek 网页版（手机本机）"),"native model settings expose phone-only web provider");main.screens.webModelSettings();c.check(c.findText(main.getWindow().getDecorView(),"在手机登录 DeepSeek"),"phone login entry exists without API address requirement");main.getSharedPreferences("models",0).edit().remove(owner).commit();}catch(Exception error){throw new AssertionError(error);}});
    }
}
