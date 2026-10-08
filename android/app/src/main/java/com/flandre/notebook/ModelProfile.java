package com.flandre.notebook;

import android.content.Context;
import android.security.keystore.*;
import android.util.Base64;
import org.json.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;

/** Model settings are local to a workspace; API keys encrypted with Android Keystore. */
final class ModelProfile {
    static final String ALIAS="flandre-model-v1";
    static javax.crypto.SecretKey key() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(!store.containsAlias(ALIAS)){KeyGenerator generator=KeyGenerator.getInstance("AES","AndroidKeyStore");generator.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());generator.generateKey();}
        return (javax.crypto.SecretKey)store.getKey(ALIAS,null);
    }
    static JSONObject read(Context c,String workspace) throws Exception {
        String saved=c.getSharedPreferences("models",0).getString(workspace,"");if(saved.isEmpty())return new JSONObject().put("url","").put("model","").put("key","");
        return unseal(workspace,saved);
    }
    static JSONObject unseal(String workspace,String saved) throws Exception {
        JSONObject e=new JSONObject(saved);Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(e.getString("iv"),Base64.NO_WRAP)));cipher.updateAAD(workspace.getBytes(StandardCharsets.UTF_8));return new JSONObject(new String(cipher.doFinal(Base64.decode(e.getString("data"),Base64.NO_WRAP)),StandardCharsets.UTF_8));
    }
    static void write(Context c,String workspace,JSONObject p) throws Exception {
        String url=p.getString("url");if(!url.isEmpty())AiClient.endpoint(url);
        if(p.getString("key").contains("\n")||p.getString("key").contains("\r"))throw new java.io.IOException("密钥格式无效。");
        if(p.has("web_token")&&!p.optString("web_token").isEmpty())DeepSeekWeb.token(p.getString("web_token"));
        if(!c.getSharedPreferences("models",0).edit().putString(workspace,seal(workspace,p)).commit())throw new java.io.IOException("模型设置未能保存。");
    }
    static String seal(String workspace,JSONObject p) throws Exception {
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());cipher.updateAAD(workspace.getBytes(StandardCharsets.UTF_8));byte[] data=cipher.doFinal(p.toString().getBytes(StandardCharsets.UTF_8));
        JSONObject encoded=new JSONObject().put("iv",Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)).put("data",Base64.encodeToString(data,Base64.NO_WRAP));
        return encoded.toString();
    }
}
