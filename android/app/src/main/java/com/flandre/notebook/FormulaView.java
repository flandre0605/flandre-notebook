package com.flandre.notebook;

import android.content.Context;
import android.webkit.*;
import android.net.Uri;
import android.print.*;

/** Offline, escaped question text. No bridge, remote requests or arbitrary file access. */
final class FormulaView extends WebView {
    boolean ready=false,disposed=false;int measuredWidth=0,readyChecks=0;final boolean preview;
    FormulaView(Context context,String text){this(context,text,false);}
    FormulaView(Context context,String text,boolean compact){
        super(context);preview=compact;getSettings().setJavaScriptEnabled(true);getSettings().setAllowFileAccess(false);getSettings().setAllowContentAccess(false);getSettings().setAllowFileAccessFromFileURLs(false);getSettings().setAllowUniversalAccessFromFileURLs(false);getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        setBackgroundColor(0);setWebViewClient(new WebViewClient(){
            public void onPageFinished(WebView v,String url){fit();postDelayed(()->fit(),350);}
            public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){return true;}
            public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest r){
                String url=r.getUrl().toString(),prefix="https://app.local/math/";
                if(url.startsWith(prefix)){String path=url.substring(prefix.length());if(!path.contains("..")&&path.matches("[A-Za-z0-9_./-]+"))try{return new WebResourceResponse(path.endsWith(".css")?"text/css":path.endsWith(".js")?"application/javascript":"font/woff2","UTF-8",context.getAssets().open("math/"+path));}catch(Exception ignored){}}
                return new WebResourceResponse("text/plain","UTF-8",new java.io.ByteArrayInputStream(new byte[0]));
            }
        });
        String escaped=text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\"","&quot;").replace("'","&#39;");
        getSettings().setTextZoom(Math.round(context.getResources().getConfiguration().fontScale*100));
        String previewCss=preview?"body{font-size:16px;line-height:1.65}.katex-display{margin:12px 0;text-align:left}.katex-display>.katex{text-align:left}#content{display:flow-root}":"";
        String previewFit=preview?"window.fitPreview=function(){document.querySelectorAll('.katex').forEach(function(el){el.style.fontSize='1.21em';var inner=el.querySelector('.katex-html');if(inner){var width=Math.max(inner.scrollWidth,inner.getBoundingClientRect().width),available=document.getElementById('content').clientWidth;if(width>available&&width>0)el.style.fontSize=Math.max(.72,1.21*available/width)+'em';}});};window.addEventListener('resize',window.fitPreview);":"";
        String html="<!doctype html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; script-src https://app.local 'unsafe-inline'; style-src https://app.local 'unsafe-inline'; font-src https://app.local; img-src 'none'; connect-src 'none'\"><link rel='stylesheet' href='https://app.local/math/katex.min.css'><style>body{color:#322b39;font:17px sans-serif;line-height:1.8;margin:0;padding:4px 0;white-space:pre-wrap;overflow-wrap:anywhere}.katex-display{overflow-x:auto;overflow-y:hidden}.katex{white-space:normal}"+previewCss+"</style><script src='https://app.local/math/katex.min.js'></script><script src='https://app.local/math/contrib/auto-render.min.js'></script></head><body><main id='content'>"+escaped+"</main><script>renderMathInElement(document.getElementById('content'),{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:"+preview+"},{left:'\\\\(',right:'\\\\)',display:"+preview+"},{left:'\\\\[',right:'\\\\]',display:true}],throwOnError:false,trust:false,maxExpand:1000});"+previewFit+"document.fonts.ready.then(function(){if(window.fitPreview)window.fitPreview();document.documentElement.dataset.ready='1';});</script></body></html>";
        loadDataWithBaseURL("https://app.local/",html,"text/html","UTF-8",null);
    }
    void fit(){if(disposed||getWidth()<1)return;evaluateJavascript("document.documentElement.dataset.ready==='1'",value->{if(disposed)return;ready="true".equals(value);if(!ready){if(++readyChecks<=100)postDelayed(()->fit(),100);return;}evaluateJavascript("(function(){if(window.fitPreview)window.fitPreview();return Math.ceil(document.getElementById('content').getBoundingClientRect().height+12)})()",heightValue->{if(disposed)return;try{float density=getResources().getDisplayMetrics().density;float limit=preview?Math.min(240,160*getResources().getConfiguration().fontScale):4096;int height=Math.round(Math.max(preview?48:56,Math.min(limit,Float.parseFloat(heightValue)))*density);android.view.ViewGroup.LayoutParams p=getLayoutParams();if(p!=null&&p.height!=height){p.height=height;setLayoutParams(p);}}catch(NumberFormatException ignored){}});});}
    protected void onSizeChanged(int w,int h,int oldw,int oldh){super.onSizeChanged(w,h,oldw,oldh);if(w!=measuredWidth){measuredWidth=w;post(()->fit());}}
    public void destroy(){disposed=true;super.destroy();}
    void print(String title){if(!ready){android.widget.Toast.makeText(getContext(),"正在排版，请稍后再打印。",android.widget.Toast.LENGTH_SHORT).show();return;}PrintManager manager=(PrintManager)getContext().getSystemService(Context.PRINT_SERVICE);if(manager!=null)manager.print(title,createPrintDocumentAdapter(title),new PrintAttributes.Builder().setMediaSize(PrintAttributes.MediaSize.ISO_A4).build());}
}
