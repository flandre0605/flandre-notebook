package com.flandre.notebook;

import android.content.Context;
import android.graphics.*;
import android.view.*;
import java.io.*;

final class CropView extends View {
    final Bitmap bitmap;
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF image=new RectF(),crop=new RectF(0,0,1,1);
    private float startX,startY;
    CropView(Context c,Bitmap b){super(c);bitmap=b;setContentDescription("题目预览，拖动框选题目区域");}
    void reset(){crop.set(0,0,1,1);invalidate();}
    protected void onDraw(Canvas canvas){
        super.onDraw(canvas);float scale=Math.min((float)getWidth()/bitmap.getWidth(),(float)getHeight()/bitmap.getHeight());
        float w=bitmap.getWidth()*scale,h=bitmap.getHeight()*scale;
        image.set((getWidth()-w)/2,(getHeight()-h)/2,(getWidth()+w)/2,(getHeight()+h)/2);
        paint.setColor(Color.WHITE);canvas.drawBitmap(bitmap,null,image,paint);
        RectF box=new RectF(image.left+crop.left*w,image.top+crop.top*h,image.left+crop.right*w,image.top+crop.bottom*h);
        paint.setColor(0x77972756);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(4);canvas.drawRect(box,paint);paint.setStyle(Paint.Style.FILL);
    }
    float x(float p){return Math.max(0,Math.min(1,(p-image.left)/image.width()));}
    float y(float p){return Math.max(0,Math.min(1,(p-image.top)/image.height()));}
    public boolean onTouchEvent(MotionEvent e){
        if(image.isEmpty())return false;
        if(e.getAction()==MotionEvent.ACTION_DOWN){startX=x(e.getX());startY=y(e.getY());if(getParent()!=null)getParent().requestDisallowInterceptTouchEvent(true);return true;}
        if(e.getAction()==MotionEvent.ACTION_MOVE||e.getAction()==MotionEvent.ACTION_UP){
            float endX=x(e.getX()),endY=y(e.getY());crop.set(Math.min(startX,endX),Math.min(startY,endY),Math.max(startX,endX),Math.max(startY,endY));
            if(e.getAction()==MotionEvent.ACTION_UP){if(crop.width()<0.01||crop.height()<0.01)crop.set(0,0,1,1);if(getParent()!=null)getParent().requestDisallowInterceptTouchEvent(false);performClick();}invalidate();return true;
        }
        return true;
    }
    public boolean performClick(){super.performClick();return true;}
    byte[] cropped() throws IOException {
        int left=Math.max(0,Math.min(bitmap.getWidth()-1,(int)(crop.left*bitmap.getWidth())));
        int top=Math.max(0,Math.min(bitmap.getHeight()-1,(int)(crop.top*bitmap.getHeight())));
        int width=Math.max(1,Math.min(bitmap.getWidth()-left,Math.round(crop.right*bitmap.getWidth())-left));
        int height=Math.max(1,Math.min(bitmap.getHeight()-top,Math.round(crop.bottom*bitmap.getHeight())-top));
        Bitmap b=Bitmap.createBitmap(bitmap,left,top,width,height);
        try(ByteArrayOutputStream out=new ByteArrayOutputStream()){if(!b.compress(Bitmap.CompressFormat.JPEG,94,out))throw new IOException("裁剪图保存失败。");return out.toByteArray();}
        finally{if(b!=bitmap)b.recycle();}
    }
}
