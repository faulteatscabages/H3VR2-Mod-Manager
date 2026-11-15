package com.h3vr2mods.core;

import java.util.*;

/** Field edits on type-tree values: {"path":[...], "set"|"append"|"insert"|"remove"|"remove_match": ...}. */
public final class Ops {
    public interface Resolver { Object ref(Map<String, Object> spec); }

    public static final class ModError extends RuntimeException { public ModError(String m) { super(m); } }

    /** Deep-copies a JSON value, turning {"$ref": spec} into PPtrs. */
    @SuppressWarnings("unchecked")
    public static Object value(Object v, Resolver r) {
        if (v instanceof Map) {
            Map<String, Object> m = (Map<String, Object>) v;
            if (m.containsKey("$ref")) return r.ref(Json.obj(m.get("$ref")));
            if (m.containsKey("$bytes")) return Base64.getDecoder().decode((String) m.get("$bytes"));
            LinkedHashMap<String, Object> o = new LinkedHashMap<>();
            for (Map.Entry<String, Object> e : m.entrySet()) o.put(e.getKey(), value(e.getValue(), r));
            return o;
        }
        if (v instanceof List) { ArrayList<Object> o = new ArrayList<>(); for (Object x : (List<Object>) v) o.add(value(x, r)); return o; }
        return v;
    }

    @SuppressWarnings("unchecked")
    public static Object get(Object tree, List<Object> path) {
        Object cur = tree;
        for (Object k : path) cur = step(cur, k, false);
        return cur;
    }

    @SuppressWarnings("unchecked")
    private static Object step(Object cur, Object k, boolean forSet) {
        if (k instanceof String) {
            if (!(cur instanceof Map) || !((Map<String, Object>) cur).containsKey(k)) throw new ModError("field '" + k + "' not found");
            return ((Map<String, Object>) cur).get(k);
        }
        if (k instanceof Number) {
            List<Object> l = (List<Object>) cur; int i = ((Number) k).intValue();
            if (i < 0 || i >= l.size()) throw new ModError("index " + i + " out of range");
            return l.get(i);
        }
        Map<String, Object> sel = Json.obj(k);   // {"first": X}: element of a Unity map
        for (Object e : (List<Object>) cur) if (Objects.equals(Json.obj(e).get("first"), sel.get("first"))) return e;
        throw new ModError("entry '" + sel.get("first") + "' not found");
    }

    @SuppressWarnings("unchecked")
    public static void apply(Object tree, List<Object> edits, Resolver r) {
        for (Object eo : edits) {
            Map<String, Object> e = Json.obj(eo);
            List<Object> path = Json.arr(e.get("path"));
            if (e.containsKey("set")) {
                if (path.isEmpty()) throw new ModError("empty path");
                Object parent = get(tree, path.subList(0, path.size() - 1));
                Object last = path.get(path.size() - 1);
                Object val = value(e.get("set"), r);
                if (last instanceof String) {
                    Map<String, Object> m = (Map<String, Object>) parent;
                    if (!m.containsKey(last)) throw new ModError("field '" + last + "' not found");
                    m.put((String) last, val);
                } else if (last instanceof Number) ((List<Object>) parent).set(((Number) last).intValue(), val);
                else { Map<String, Object> pair = Json.obj(step(parent, last, true)); pair.put("second", val); }
            } else {
                List<Object> list = (List<Object>) get(tree, path);
                if (e.containsKey("append")) list.add(value(e.get("append"), r));
                else if (e.containsKey("insert")) list.add(((Number) e.get("index")).intValue(), value(e.get("insert"), r));
                else if (e.containsKey("remove")) list.remove(((Number) e.get("remove")).intValue());
                else if (e.containsKey("remove_match")) { Object m = value(e.get("remove_match"), r); list.removeIf(x -> deepEq(x, m)); }
                else if (e.containsKey("duplicate_where")) {
                    // copy every entry that mentions a string, rewrite the copy, optionally override fields
                    String needle = (String) Json.obj(e.get("duplicate_where")).get("contains");
                    List<Object> rep = Json.arr(e.get("replace"));
                    Map<String, Object> over = e.containsKey("with") ? Json.obj(e.get("with")) : null;
                    List<Object> add = new ArrayList<>();
                    for (Object x : list) if (contains(x, needle)) {
                        Object copy = replaceStrings(x, (String) rep.get(0), (String) rep.get(1));
                        if (over != null) for (Map.Entry<String, Object> o : over.entrySet()) ((Map<String, Object>) copy).put(o.getKey(), value(o.getValue(), r));
                        add.add(copy);
                    }
                    list.addAll(add);
                }
                else throw new ModError("unknown edit " + e.keySet());
            }
        }
    }

    @SuppressWarnings("unchecked")
    public static boolean contains(Object v, String needle) {
        if (v instanceof String) return v.equals(needle);
        if (v instanceof Map) { for (Object x : ((Map<String, Object>) v).values()) if (contains(x, needle)) return true; return false; }
        if (v instanceof List) { for (Object x : (List<Object>) v) if (contains(x, needle)) return true; return false; }
        return false;
    }

    @SuppressWarnings("unchecked")
    static Object replaceStrings(Object v, String a, String b) {
        if (v instanceof String) return ((String) v).equals(a) ? b : v;
        if (v instanceof Map) { LinkedHashMap<String, Object> o = new LinkedHashMap<>(); for (Map.Entry<String, Object> e : ((Map<String, Object>) v).entrySet()) o.put(e.getKey(), replaceStrings(e.getValue(), a, b)); return o; }
        if (v instanceof List) { ArrayList<Object> o = new ArrayList<>(); for (Object x : (List<Object>) v) o.add(replaceStrings(x, a, b)); return o; }
        return v;
    }

    @SuppressWarnings("unchecked")
    static boolean deepEq(Object a, Object b) {
        if (a instanceof Number && b instanceof Number) return ((Number) a).doubleValue() == ((Number) b).doubleValue();
        if (a instanceof Map && b instanceof Map) {
            Map<String, Object> x = (Map<String, Object>) a, y = (Map<String, Object>) b;
            if (!x.keySet().equals(y.keySet())) return false;
            for (String k : x.keySet()) if (!deepEq(x.get(k), y.get(k))) return false;
            return true;
        }
        if (a instanceof List && b instanceof List) {
            List<Object> x = (List<Object>) a, y = (List<Object>) b;
            if (x.size() != y.size()) return false;
            for (int i = 0; i < x.size(); i++) if (!deepEq(x.get(i), y.get(i))) return false;
            return true;
        }
        if (a instanceof byte[] && b instanceof byte[]) return Arrays.equals((byte[]) a, (byte[]) b);
        return Objects.equals(a, b);
    }

    public static LinkedHashMap<String, Object> pptr(int file, long pid) {
        LinkedHashMap<String, Object> p = new LinkedHashMap<>(); p.put("m_FileID", (long) file); p.put("m_PathID", pid); return p;
    }
}
