package com.flandre.notebook;

import android.app.Activity;
import android.os.*;
import android.util.Base64;
import android.webkit.*;
import org.json.*;
import java.io.*;
import java.util.concurrent.*;

/** Local WASM computation in a bounded Web Worker. No secrets, network or JavaScript bridge. */
final class DeepSeekPow implements DeepSeekWeb.Pow,AutoCloseable {
    final Activity activity;final Handler main=new Handler(Looper.getMainLooper());
    volatile CompletableFuture<String> pending;WebView view;volatile boolean closed=false;
    DeepSeekPow(Activity a){activity=a;}
    public long solve(JSONObject input) throws Exception {
        if(Looper.myLooper()==Looper.getMainLooper())throw new IOException("校验需要在后台执行。");JSONObject c=DeepSeekWeb.challenge(input);if(closed)throw new IOException("识题窗口已关闭，草稿保留。");
        CompletableFuture<String> result=new CompletableFuture<>();synchronized(this){if(pending!=null)throw new IOException("请等待当前本机校验完成。");pending=result;}
        String wasm;try(InputStream in=activity.getAssets().open("deepseek/solver.wasm")){wasm=Base64.encodeToString(NotebookBackup.read(in,128*1024),Base64.NO_WRAP);}catch(Exception error){pending=null;throw error;}
        main.post(()->{if(closed||activity.isDestroyed()){result.completeExceptionally(new IOException("识题窗口已关闭。"));return;}
            view=new WebView(activity);WebSettings settings=view.getSettings();settings.setJavaScriptEnabled(true);settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setAllowFileAccessFromFileURLs(false);settings.setAllowUniversalAccessFromFileURLs(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
            view.setWebViewClient(new WebViewClient(){public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest request){return true;}public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest request){return new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));}});
            String worker="onmessage=async e=>{try{if(typeof BigInt==='undefined')throw Error('unsupported');const raw=atob(e.data.wasm),bytes=Uint8Array.from(raw,c=>c.charCodeAt(0)),instance=new WebAssembly.Instance(new WebAssembly.Module(bytes),{}),x=instance.exports,encoder=new TextEncoder();function write(s){const b=encoder.encode(s),p=x.alloc(b.length);new Uint8Array(x.memory.buffer).set(b,p);return[p,b.length];}const c=e.data.challenge,a=write(c.challenge),b=write(c.salt),answer=x.solve_pow(a[0],a[1],b[0],b[1],BigInt(c.expire_at),BigInt(c.difficulty));postMessage(answer===BigInt(-1)?'error':'ok:'+answer.toString());}catch(error){postMessage('error');}}";
            String script="window.powResult='';try{window.worker=new Worker(URL.createObjectURL(new Blob(["+JSONObject.quote(worker)+"],{type:'application/javascript'})));worker.onmessage=e=>{window.powResult=e.data;worker.terminate();};worker.onerror=()=>{window.powResult='error';worker.terminate();};worker.postMessage({wasm:"+JSONObject.quote(wasm)+",challenge:"+c.toString()+"});}catch(error){window.powResult='error';}";
            String html="<!doctype html><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob:; worker-src blob:; connect-src 'none'\"><script>"+script+"</script>";
            view.loadDataWithBaseURL("https://app.local/deepseek/",html,"text/html","UTF-8",null);poll(result);
        });
        try{String answer=result.get(60,TimeUnit.SECONDS);if(!answer.matches("ok:[0-9]{1,16}"))throw new IOException("手机本机校验未通过，请更新 Android System WebView 后重试。");return Long.parseLong(answer.substring(3));}
        catch(TimeoutException e){throw new IOException("手机本机校验超时，请手动重试；草稿保留。");}catch(ExecutionException e){throw new IOException("手机本机校验已停止，草稿保留。");}
        finally{result.cancel(false);main.post(()->{if(view!=null){view.destroy();view=null;}});pending=null;}
    }
    void poll(CompletableFuture<String> result){if(result.isDone()||closed||view==null)return;view.evaluateJavascript("window.powResult||''",value->{if(result.isDone())return;try{String answer=new JSONArray("["+value+"]").getString(0);if(!answer.isEmpty()){result.complete(answer);return;}}catch(Exception ignored){}main.postDelayed(()->poll(result),100);});}
    public void close(){closed=true;CompletableFuture<String> job=pending;if(job!=null)job.completeExceptionally(new IOException("窗口已关闭。"));main.post(()->{if(view!=null){view.destroy();view=null;}});}
}
