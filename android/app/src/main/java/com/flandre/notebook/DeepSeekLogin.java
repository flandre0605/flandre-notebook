package com.flandre.notebook;

import android.content.Context;
import android.webkit.*;
import android.net.Uri;
import java.util.function.Consumer;
import org.json.*;

/** User-driven first-party login. Reads the user's own token only on explicit confirmation. */
final class DeepSeekLogin extends WebView {
    // ponytail: first-party login only; add reviewed OAuth callbacks if third-party sign-in is needed.
    static boolean official(Uri uri){String host=uri.getHost();return "https".equals(uri.getScheme())&&host!=null&&(host.equals("deepseek.com")||host.endsWith(".deepseek.com"))&&uri.getUserInfo()==null&&(uri.getPort()==-1||uri.getPort()==443);}
    DeepSeekLogin(Context context){super(context);WebSettings settings=getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);CookieManager.getInstance().setAcceptThirdPartyCookies(this,false);setSaveEnabled(false);setImportantForAutofill(IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);setWebViewClient(new WebViewClient(){
        public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){return !official(request.getUrl());}
        public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){return "https".equals(request.getUrl().getScheme())&&(!request.isForMainFrame()||official(request.getUrl()))?null:new WebResourceResponse("text/plain","UTF-8",new java.io.ByteArrayInputStream(new byte[0]));}
    });loadUrl(DeepSeekWeb.ORIGIN+"/");}
    void capture(Consumer<String> result){if(getUrl()==null||!getUrl().startsWith(DeepSeekWeb.ORIGIN+"/")){result.accept("");return;}evaluateJavascript("(()=>{try{if(location.origin!=='https://chat.deepseek.com')return '';const t=JSON.parse(localStorage.getItem('userToken'));return t&&typeof t.value==='string'?t.value:'';}catch(e){return '';}})()",value->{try{result.accept(DeepSeekWeb.token(new JSONArray("["+value+"]").getString(0)));}catch(Exception invalid){result.accept("");}});}
    static void clear(){CookieManager.getInstance().removeAllCookies(null);CookieManager.getInstance().flush();WebStorage.getInstance().deleteAllData();}
    @Override public void destroy(){stopLoading();super.destroy();clear();}
}
