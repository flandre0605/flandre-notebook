package com.flandre.notebook;

import android.content.Context;
import android.webkit.*;
import android.net.Uri;
import android.print.*;

/** Offline, escaped question text. No bridge, remote requests or arbitrary file access. */
final class FormulaView extends WebView {
    boolean ready=false,disposed=false;int measuredWidth=0;
    FormulaView(Context context,String text){
        super(context);getSettings().setJavaScriptEnabled(true);getSettings().setAllowFileAccess(false);getSettings().setAllowContentAccess(false);getSettings().setAllowFileAccessFromFileURLs(false);getSettings().setAllowUniversalAccessFromFileURLs(false);getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        setBackgroundColor(0);setWebViewClient(new WebViewClient(){
            public void onPageFinished(WebView v,String url){v.evaluateJavascript("document.documentElement.dataset.ready==='1'",value->{ready="true".equals(value);fit();postDelayed(()->fit(),350);});}
            public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){return true;}
            public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest r){
                String url=r.getUrl().toString(),prefix="https://app.local/math/";
                if(url.startsWith(prefix)){String path=url.substring(prefix.length());if(!path.contains("..")&&path.matches("[A-Za-z0-9_./-]+"))try{return new WebResourceResponse(path.endsWith(".css")?"text/css":path.endsWith(".js")?"application/javascript":"font/woff2","UTF-8",context.getAssets().open("math/"+path));}catch(Exception ignored){}}
                return new WebResourceResponse("text/plain","UTF-8",new java.io.ByteArrayInputStream(new byte[0]));
            }
        });
        String escaped=text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\"","&quot;").replace("'","&#39;");
        getSettings().setTextZoom(Math.round(context.getResources().getConfiguration().fontScale*100));
        String html="<!doctype html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; script-src https://app.local 'unsafe-inline'; style-src https://app.local 'unsafe-inline'; font-src https://app.local; img-src 'none'; connect-src 'none'\"><link rel='stylesheet' href='https://app.local/math/katex.min.css'><style>body{color:#322b39;font:17px sans-serif;line-height:1.8;margin:0;padding:4px 0;white-space:pre-wrap;overflow-wrap:anywhere}.katex-display{overflow-x:auto;overflow-y:hidden}.katex{white-space:normal}</style><script src='https://app.local/math/katex.min.js'></script><script src='https://app.local/math/contrib/auto-render.min.js'></script></head><body><main id='content'>"+escaped+"</main><script>renderMathInElement(document.getElementById('content'),{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false},{left:'\\\\(',right:'\\\\)',display:false},{left:'\\\\[',right:'\\\\]',display:true}],throwOnError:false,trust:false,maxExpand:1000});document.documentElement.dataset.ready='1';</script></body></html>";
        loadDataWithBaseURL("https://app.local/",html,"text/html","UTF-8",null);
    }
    void fit(){if(disposed||!ready||getWidth()<1)return;evaluateJavascript("Math.ceil(document.getElementById('content').getBoundingClientRect().height+12)",value->{if(disposed)return;try{float density=getResources().getDisplayMetrics().density;int height=Math.round(Math.max(56,Math.min(4096,Float.parseFloat(value)))*density);android.view.ViewGroup.LayoutParams p=getLayoutParams();if(p!=null&&p.height!=height){p.height=height;setLayoutParams(p);}}catch(NumberFormatException ignored){}});}
    protected void onSizeChanged(int w,int h,int oldw,int oldh){super.onSizeChanged(w,h,oldw,oldh);if(w!=measuredWidth){measuredWidth=w;post(()->fit());}}
    public void destroy(){disposed=true;super.destroy();}
    void print(String title){if(!ready){android.widget.Toast.makeText(getContext(),"正在排版，请稍后再打印。",android.widget.Toast.LENGTH_SHORT).show();return;}PrintManager manager=(PrintManager)getContext().getSystemService(Context.PRINT_SERVICE);if(manager!=null)manager.print(title,createPrintDocumentAdapter(title),new PrintAttributes.Builder().setMediaSize(PrintAttributes.MediaSize.ISO_A4).build());}
}
