package com.flandre.notebook;

import android.content.*;
import org.json.*;
import java.io.IOException;

/** One remembered account; encrypted refresh only, excluded from notebook exports. */
final class CloudLoginStore {
    private final SharedPreferences prefs;
    CloudLoginStore(Context context){prefs=context.getSharedPreferences("cloud-login",0);}
    private String binding(String uid){return "cloud-account:"+CloudApi.BASE+":"+uid;}
    synchronized void save(CloudApi api) throws IOException {
        if(api.refresh.isEmpty())return;
        try{
            String value=ModelProfile.seal(binding(api.uid),new JSONObject().put("uid",api.uid).put("environment",CloudApi.BASE).put("username",api.username).put("device",api.device).put("refresh",api.refresh));
            if(!prefs.edit().putString("uid",api.uid).putString("session",value).commit())throw new IOException();
        }catch(Exception error){throw new IOException("登录状态未能安全保存，请重新登录。密码不会保存，题库仍保留。");}
    }
    synchronized CloudApi load(String uid) throws IOException {
        if(!uid.equals(prefs.getString("uid","")))return null;
        try{
            JSONObject p=ModelProfile.unseal(binding(uid),prefs.getString("session",""));
            String refresh=p.getString("refresh"),device=p.getString("device");
            if(!uid.matches("[A-Za-z0-9_-]{1,64}")||!uid.equals(p.getString("uid"))||!CloudApi.BASE.equals(p.getString("environment"))||refresh.isEmpty()||refresh.length()>4096||device.isEmpty()||device.length()>128)throw new IOException();
            CloudApi api=new CloudApi(uid,p.getString("username"),"",0,CloudApi::request);api.refresh=refresh;api.device=device;api.store=this;return api;
        }catch(Exception error){throw new IOException("无法恢复安全保存的登录，请重新登录。原账号题库仍保留。");}
    }
    synchronized void clear(String uid) throws IOException {
        if(uid.equals(prefs.getString("uid",""))&&!prefs.edit().clear().commit())throw new IOException("登录状态未能清除，请重试退出账号。");
    }
}
