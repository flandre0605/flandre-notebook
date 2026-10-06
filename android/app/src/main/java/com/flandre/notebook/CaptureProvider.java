package com.flandre.notebook;

import android.content.*;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;

/** Narrow camera output URI. No other app-private file can be addressed. */
public final class CaptureProvider extends ContentProvider {
    public boolean onCreate(){return true;}
    File file(Uri uri) throws FileNotFoundException {
        if(!"com.flandre.notebook.capture".equals(uri.getAuthority())||!uri.getPath().matches("/[a-f0-9]{32}\\.jpg"))throw new FileNotFoundException();
        File root=new File(getContext().getCacheDir(),"captures");root.mkdirs();return new File(root,uri.getLastPathSegment());
    }
    public String getType(Uri uri){return "image/jpeg";}
    public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        if(!mode.equals("w")&&!mode.equals("rw")&&!mode.equals("r")&&!mode.equals("wt"))throw new FileNotFoundException();
        return ParcelFileDescriptor.open(file(uri),ParcelFileDescriptor.parseMode(mode));
    }
    public Cursor query(Uri uri,String[] projection,String selection,String[] args,String order){
        try {File f=file(uri);MatrixCursor c=new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE});c.addRow(new Object[]{f.getName(),f.length()});return c;}
        catch(FileNotFoundException e){return null;}
    }
    public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
    public int update(Uri uri,ContentValues values,String s,String[] args){throw new UnsupportedOperationException();}
    public int delete(Uri uri,String s,String[] args){throw new UnsupportedOperationException();}
}
