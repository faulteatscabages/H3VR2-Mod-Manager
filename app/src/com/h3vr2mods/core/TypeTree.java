package com.h3vr2mods.core;

import java.nio.charset.StandardCharsets;
import java.util.*;

/** Generic reader/writer for objects described by a Unity type tree. */
public final class TypeTree {
    private static final int ALIGN = 0x4000;

    public static Object read(SerializedFile.TreeNode root, byte[] data, boolean little) {
        Bin.R r = new Bin.R(data, 0, !little);
        Object v = read(root, r);
        return v;
    }

    private static Object read(SerializedFile.TreeNode n, Bin.R r) {
        Object v; boolean align = (n.metaFlag & ALIGN) != 0;
        switch (n.type) {
            case "bool": v = r.u8() != 0; break;
            case "SInt8": v = (long) (byte) r.u8(); break;
            case "UInt8": case "char": v = (long) r.u8(); break;
            case "SInt16": case "short": v = (long) r.i16(); break;
            case "UInt16": case "unsigned short": v = (long) r.u16(); break;
            case "SInt32": case "int": case "Type*": v = (long) r.i32(); break;
            case "UInt32": case "unsigned int": v = r.u32(); break;
            case "SInt64": case "long long": case "UInt64": case "unsigned long long": case "FileSize": v = r.i64(); break;
            case "float": v = (double) Float.intBitsToFloat(r.i32()); break;
            case "double": v = Double.longBitsToDouble(r.i64()); break;
            case "string": {
                int len = r.i32(); v = new String(r.b, r.p, len, StandardCharsets.UTF_8); r.p += len;
                if (!n.children.isEmpty() && (n.children.get(0).metaFlag & ALIGN) != 0) align = true;
                break;
            }
            case "TypelessData": { int len = r.i32(); v = r.bytes(len); break; }
            default:
                if (!n.children.isEmpty() && n.children.get(0).type.equals("Array")) {
                    SerializedFile.TreeNode arr = n.children.get(0);
                    if ((arr.metaFlag & ALIGN) != 0) align = true;
                    int count = r.i32(); SerializedFile.TreeNode el = arr.children.get(1);
                    ArrayList<Object> list = new ArrayList<>(count);
                    for (int i = 0; i < count; i++) list.add(read(el, r));
                    v = list;
                } else {
                    LinkedHashMap<String, Object> m = new LinkedHashMap<>();
                    for (SerializedFile.TreeNode c : n.children) m.put(c.name, read(c, r));
                    v = m;
                }
        }
        if (align) r.align(4, 0);
        return v;
    }

    public static byte[] write(SerializedFile.TreeNode root, Object value, boolean little) {
        Bin.W w = new Bin.W(!little); write(root, value, w); return w.toBytes();
    }

    @SuppressWarnings("unchecked")
    private static void write(SerializedFile.TreeNode n, Object v, Bin.W w) {
        boolean align = (n.metaFlag & ALIGN) != 0;
        switch (n.type) {
            case "bool": w.u8(v instanceof Boolean ? (((Boolean) v) ? 1 : 0) : (((Number) v).intValue() != 0 ? 1 : 0)); break;
            case "SInt8": case "UInt8": case "char": w.u8(((Number) v).intValue()); break;
            case "SInt16": case "short": case "UInt16": case "unsigned short": w.i16(((Number) v).intValue()); break;
            case "SInt32": case "int": case "Type*": case "UInt32": case "unsigned int": w.i32((int) ((Number) v).longValue()); break;
            case "SInt64": case "long long": case "UInt64": case "unsigned long long": case "FileSize": w.i64(((Number) v).longValue()); break;
            case "float": w.i32(Float.floatToIntBits(((Number) v).floatValue())); break;
            case "double": w.i64(Double.doubleToLongBits(((Number) v).doubleValue())); break;
            case "string": {
                byte[] s = ((String) v).getBytes(StandardCharsets.UTF_8); w.i32(s.length); w.bytes(s);
                if (!n.children.isEmpty() && (n.children.get(0).metaFlag & ALIGN) != 0) align = true;
                break;
            }
            case "TypelessData": { byte[] d = v instanceof byte[] ? (byte[]) v : Base64.getDecoder().decode((String) Json.obj(v).get("$bytes")); w.i32(d.length); w.bytes(d); break; }
            default:
                if (!n.children.isEmpty() && n.children.get(0).type.equals("Array")) {
                    SerializedFile.TreeNode arr = n.children.get(0);
                    if ((arr.metaFlag & ALIGN) != 0) align = true;
                    SerializedFile.TreeNode el = arr.children.get(1);
                    if (v instanceof byte[]) { byte[] d = (byte[]) v; w.i32(d.length); w.bytes(d); }
                    else if (v instanceof Map && ((Map<String, Object>) v).containsKey("$bytes")) {
                        byte[] d = Base64.getDecoder().decode((String) ((Map<String, Object>) v).get("$bytes")); w.i32(d.length); w.bytes(d);
                    } else { List<Object> list = (List<Object>) v; w.i32(list.size()); for (Object o : list) write(el, o, w); }
                } else {
                    Map<String, Object> m = (Map<String, Object>) v;
                    for (SerializedFile.TreeNode c : n.children) write(c, m.get(c.name), w);
                }
        }
        if (align) w.align(4, 0);
    }
}
