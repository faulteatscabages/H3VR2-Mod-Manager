package com.h3vr2mods.core;

import java.util.*;

/** Minimal JSON parser/serializer (objects -> LinkedHashMap, arrays -> ArrayList, numbers -> Long/Double). */
public final class Json {
    private final String s; private int p;
    private Json(String s) { this.s = s; }

    public static Object parse(String text) {
        Json j = new Json(text); j.ws(); Object v = j.value(); j.ws();
        if (j.p != j.s.length()) throw new IllegalArgumentException("trailing JSON at " + j.p);
        return v;
    }

    private void ws() { while (p < s.length() && Character.isWhitespace(s.charAt(p))) p++; }

    private Object value() {
        char c = s.charAt(p);
        if (c == '{') {
            p++; LinkedHashMap<String, Object> m = new LinkedHashMap<>(); ws();
            if (s.charAt(p) == '}') { p++; return m; }
            while (true) { ws(); String k = str(); ws(); p++; ws(); m.put(k, value()); ws(); char d = s.charAt(p++); if (d == '}') return m; }
        }
        if (c == '[') {
            p++; ArrayList<Object> a = new ArrayList<>(); ws();
            if (s.charAt(p) == ']') { p++; return a; }
            while (true) { ws(); a.add(value()); ws(); char d = s.charAt(p++); if (d == ']') return a; }
        }
        if (c == '"') return str();
        if (s.startsWith("true", p)) { p += 4; return Boolean.TRUE; }
        if (s.startsWith("false", p)) { p += 5; return Boolean.FALSE; }
        if (s.startsWith("null", p)) { p += 4; return null; }
        int st = p; boolean real = false;
        while (p < s.length() && "+-0123456789.eE".indexOf(s.charAt(p)) >= 0) { if (".eE".indexOf(s.charAt(p)) >= 0) real = true; p++; }
        String n = s.substring(st, p);
        return real ? (Object) Double.parseDouble(n) : (Object) Long.parseLong(n);
    }

    private String str() {
        p++; StringBuilder b = new StringBuilder();
        while (true) {
            char c = s.charAt(p++);
            if (c == '"') return b.toString();
            if (c != '\\') { b.append(c); continue; }
            char e = s.charAt(p++);
            switch (e) {
                case 'n': b.append('\n'); break; case 't': b.append('\t'); break; case 'r': b.append('\r'); break;
                case 'b': b.append('\b'); break; case 'f': b.append('\f'); break;
                case 'u': b.append((char) Integer.parseInt(s.substring(p, p + 4), 16)); p += 4; break;
                default: b.append(e);
            }
        }
    }

    public static String write(Object v) { StringBuilder b = new StringBuilder(); write(b, v); return b.toString(); }

    @SuppressWarnings("unchecked")
    private static void write(StringBuilder b, Object v) {
        if (v == null) b.append("null");
        else if (v instanceof String) quote(b, (String) v);
        else if (v instanceof Map) {
            b.append('{'); boolean first = true;
            for (Map.Entry<String, Object> e : ((Map<String, Object>) v).entrySet()) {
                if (!first) b.append(','); first = false; quote(b, e.getKey()); b.append(':'); write(b, e.getValue());
            }
            b.append('}');
        } else if (v instanceof List) {
            b.append('['); boolean first = true;
            for (Object o : (List<Object>) v) { if (!first) b.append(','); first = false; write(b, o); }
            b.append(']');
        } else b.append(v.toString());
    }

    private static void quote(StringBuilder b, String s) {
        b.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': b.append("\\\""); break; case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break; case '\r': b.append("\\r"); break; case '\t': b.append("\\t"); break;
                default: if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
            }
        }
        b.append('"');
    }

    @SuppressWarnings("unchecked") public static Map<String, Object> obj(Object o) { return (Map<String, Object>) o; }
    @SuppressWarnings("unchecked") public static List<Object> arr(Object o) { return (List<Object>) o; }
}
