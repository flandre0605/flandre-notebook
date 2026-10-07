package com.flandre.notebook;

import org.json.*;
import java.io.*;
import java.util.*;

/** Bounded file exchange, with quoted/multiline CSV cells and complete validation. */
final class QuestionFiles {
    static List<List<String>> csv(String source) throws IOException {
        if(source.startsWith("\ufeff"))source=source.substring(1);List<List<String>> rows=new ArrayList<>();List<String> row=new ArrayList<>();StringBuilder cell=new StringBuilder();boolean quoted=false,closed=false;
        for(int i=0;i<source.length();i++){char c=source.charAt(i);if(quoted){if(c=='"'){if(i+1<source.length()&&source.charAt(i+1)=='"'){cell.append('"');i++;}else{quoted=false;closed=true;}}else cell.append(c);}
            else if(c==','||c=='\n'||c=='\r'){row.add(cell.toString());cell.setLength(0);closed=false;if(c!=','){if(c=='\r'&&i+1<source.length()&&source.charAt(i+1)=='\n')i++;rows.add(row);row=new ArrayList<>();if(rows.size()>20001)throw new IOException("CSV 记录超过 20000 条。");}}
            else if(c=='"'){if(cell.length()!=0||closed)throw new IOException("CSV 引号格式无效。");quoted=true;}
            else {if(closed)throw new IOException("CSV 引号后应为分隔符。");cell.append(c);}if(cell.length()>2*1024*1024||row.size()>100)throw new IOException("CSV 单项内容过长。");}
        if(quoted)throw new IOException("CSV 引号未闭合，未导入任何内容。");if(cell.length()>0||!row.isEmpty()||closed){row.add(cell.toString());rows.add(row);}return rows;
    }
    static JSONArray questions(String text) throws Exception {
        if(text.startsWith("\ufeff"))text=text.substring(1);String trimmed=text.trim();if(trimmed.startsWith("[")||trimmed.startsWith("{")){JSONTokener parser=new JSONTokener(trimmed);Object parsed=parser.nextValue();if(parser.nextClean()!=0)throw new IOException("JSON 包含额外内容。");return parsed instanceof JSONArray?(JSONArray)parsed:((JSONObject)parsed).getJSONArray("questions");}
        List<List<String>> rows=csv(text);if(rows.isEmpty())throw new IOException("文件为空。");List<String> header=rows.get(0);if(!header.contains("stem")&&!header.contains("题干"))throw new IOException("题目 CSV 首行需要题干列（stem 或题干）。");JSONArray result=new JSONArray();
        String[] labels={"题干","学科","题型","答案","解析","标签","知识点","难度","来源","年级","个人笔记"};Map<String,String> names=new HashMap<>();for(int i=0;i<Notebook.FIELDS.length;i++){names.put(Notebook.FIELDS[i],Notebook.FIELDS[i]);names.put(labels[i],Notebook.FIELDS[i]);}names.put("选项","options");names.put("options","options");names.put("错题","is_wrong");names.put("is_wrong","is_wrong");
        Set<String> seen=new HashSet<>();for(String key:header)if(names.containsKey(key)&&!seen.add(names.get(key)))throw new IOException("CSV 有重复的题目列。");
        for(int i=1;i<rows.size();i++){List<String> values=rows.get(i);if(values.size()==1&&values.get(0).isEmpty())continue;if(values.size()!=header.size())throw new IOException("CSV 第 "+(i+1)+" 行列数不同。");JSONObject q=new JSONObject();for(int j=0;j<header.size();j++){String k=names.get(header.get(j)),value=values.get(j);if(k==null)continue;if(k.equals("options"))q.put(k,value.trim().isEmpty()?new JSONObject():new JSONObject(value));else if(k.equals("is_wrong")){String flag=value.trim().toLowerCase(Locale.ROOT);if(!Arrays.asList("","0","1","true","false","是","否").contains(flag))throw new IOException("CSV 错题列无效。");q.put(k,Arrays.asList("1","true","是").contains(flag)?1:0);}else q.put(k,value);}result.put(Notebook.question(q));}return result;
    }
    static String cell(String text){return "\""+text.replace("\"","\"\"")+"\"";}
    static String export(JSONArray questions) throws Exception {
        List<String> keys=new ArrayList<>(Arrays.asList(Notebook.FIELDS));keys.add("options");keys.add("is_wrong");StringBuilder s=new StringBuilder("\ufeff");s.append(String.join(",",keys)).append("\r\n");for(int i=0;i<questions.length();i++){JSONObject q=Notebook.question(questions.getJSONObject(i));for(int j=0;j<keys.size();j++){if(j>0)s.append(',');s.append(cell(q.get(keys.get(j)).toString()));}s.append("\r\n");}return s.toString();
    }
}
