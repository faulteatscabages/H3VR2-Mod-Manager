package com.h3vr2mods.core;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * Unity SerializedFile (format 22, Unity 6) with type trees.
 * Supports reading/adding/replacing objects, adding types and external references; everything else is kept.
 */
public final class SerializedFile {
    public static final class TreeNode {
        public String type, name; public int level, byteSize, metaFlag; public List<TreeNode> children = new ArrayList<>();
    }
    public static final class SType {
        public int classId, scriptTypeIndex; public byte[] scriptId, oldTypeHash; public TreeNode tree; public byte[] raw;
    }
    public static final class Obj { public long pathId; public long start; public int size; public int typeIndex; public byte[] newData; }
    public static final class Script { public int fileIndex; public long localId; }
    public static final class External { public String tempEmpty; public byte[] guid; public int type; public String path; }

    private byte[] b; private boolean little;
    public int version; private long dataOffset;
    private byte[] metaHead;   // unity version, platform, type-tree flag
    private byte[] metaTail;   // ref types + user information
    private int metaStart;
    public final List<SType> types = new ArrayList<>();
    public final List<Obj> objects = new ArrayList<>();
    public final Map<Long, Obj> byId = new HashMap<>();
    public final List<Script> scripts = new ArrayList<>();
    public final List<External> externals = new ArrayList<>();

    public static SerializedFile read(byte[] b) throws IOException {
        SerializedFile s = new SerializedFile(); s.b = b;
        Bin.R r = new Bin.R(b, 0, true);
        r.i32(); r.i32(); s.version = r.i32(); r.i32();
        if (s.version != 22) throw new IOException("SerializedFile version " + s.version + " not supported");
        int endian = r.u8(); r.bytes(3);
        long metaSize = r.u32(); r.i64(); s.dataOffset = r.i64(); r.i64();
        s.metaStart = r.p; s.little = endian == 0; r.be = !s.little;
        r.cstr(); r.i32(); boolean typeTree = r.u8() != 0;
        if (!typeTree) throw new IOException("file has no type trees");
        s.metaHead = Arrays.copyOfRange(b, s.metaStart, r.p);
        int nt = r.i32();
        for (int i = 0; i < nt; i++) { int st = r.p; SType t = readType(r); t.raw = Arrays.copyOfRange(b, st, r.p); s.types.add(t); }
        int no = r.i32();
        for (int i = 0; i < no; i++) {
            r.align(4, 0);
            Obj o = new Obj(); o.pathId = r.i64(); o.start = r.i64(); o.size = r.i32(); o.typeIndex = r.i32();
            s.objects.add(o); s.byId.put(o.pathId, o);
        }
        int ns = r.i32();
        for (int i = 0; i < ns; i++) { Script sc = new Script(); sc.fileIndex = r.i32(); r.align(4, 0); sc.localId = r.i64(); s.scripts.add(sc); }
        int ne = r.i32();
        for (int i = 0; i < ne; i++) {
            External e = new External(); e.tempEmpty = r.cstr(); e.guid = r.bytes(16); e.type = r.i32(); e.path = r.cstr(); s.externals.add(e);
        }
        s.metaTail = Arrays.copyOfRange(b, r.p, (int) (s.metaStart + metaSize));
        return s;
    }

    public static SType parseType(byte[] raw, boolean little) {
        Bin.R r = new Bin.R(raw, 0, !little); SType t = readType(r); t.raw = raw; return t;
    }

    private static SType readType(Bin.R r) {
        SType t = new SType();
        t.classId = r.i32(); r.u8(); t.scriptTypeIndex = r.i16();
        if (t.classId == 114) t.scriptId = r.bytes(16);
        t.oldTypeHash = r.bytes(16);
        int nodeCount = r.i32(), strSize = r.i32();
        int nodesAt = r.p; r.p += nodeCount * 32;
        byte[] strs = r.bytes(strSize);
        Bin.R nr = new Bin.R(r.b, nodesAt, r.be);
        List<TreeNode> flat = new ArrayList<>();
        for (int i = 0; i < nodeCount; i++) {
            TreeNode n = new TreeNode();
            nr.u16(); n.level = nr.u8(); nr.u8();
            int ts = nr.i32(), ns = nr.i32(); n.byteSize = nr.i32(); nr.i32(); n.metaFlag = nr.i32(); nr.i64();
            n.type = str(strs, ts); n.name = str(strs, ns);
            flat.add(n);
        }
        Deque<TreeNode> stack = new ArrayDeque<>();
        for (TreeNode n : flat) {
            while (!stack.isEmpty() && stack.peek().level >= n.level) stack.pop();
            if (!stack.isEmpty()) stack.peek().children.add(n);
            stack.push(n);
        }
        t.tree = flat.isEmpty() ? null : flat.get(0);
        int deps = r.i32(); r.p += deps * 4;
        return t;
    }

    private static String str(byte[] local, int off) {
        if (off < 0) return Common.get(off & 0x7FFFFFFF);
        int e = off; while (local[e] != 0) e++;
        return new String(local, off, e - off, StandardCharsets.UTF_8);
    }

    public byte[] data(Obj o) {
        if (o.newData != null) return o.newData;
        return Arrays.copyOfRange(b, (int) (dataOffset + o.start), (int) (dataOffset + o.start + o.size));
    }

    public SType type(Obj o) { return types.get(o.typeIndex); }
    public Object readTree(Obj o) { return TypeTree.read(type(o).tree, data(o), little); }
    public void writeTree(Obj o, Object tree) { o.newData = TypeTree.write(type(o).tree, tree, little); o.size = o.newData.length; }

    public Obj add(long pathId, int typeIndex, byte[] data) {
        if (byId.containsKey(pathId)) throw new IllegalStateException("object " + pathId + " already exists");
        Obj o = new Obj(); o.pathId = pathId; o.typeIndex = typeIndex; o.newData = data; o.size = data.length;
        objects.add(o); byId.put(pathId, o); return o;
    }

    /** Index of a type with this class id (and script id for MonoBehaviours), or -1. */
    public int findType(int classId, byte[] scriptId) {
        for (int i = 0; i < types.size(); i++) {
            SType t = types.get(i);
            if (t.classId == classId && (scriptId == null || Arrays.equals(scriptId, t.scriptId))) return i;
        }
        return -1;
    }

    public int addType(byte[] raw) {
        SType t = parseType(raw, little);
        int i = findType(t.classId, t.classId == 114 ? t.scriptId : null);
        if (i >= 0) return i;
        types.add(t); return types.size() - 1;
    }

    /** File id (1-based) of an external file, adding it if missing. */
    public int externalId(String path) {
        for (int i = 0; i < externals.size(); i++) if (externals.get(i).path.equals(path)) return i + 1;
        External e = new External(); e.tempEmpty = ""; e.guid = new byte[16]; e.type = 0; e.path = path; externals.add(e);
        return externals.size();
    }

    /** Replaces a same-length byte string everywhere in object data (used to rename a cloned bundle's CAB). */
    public void replaceBytes(byte[] from, byte[] to) {
        if (from.length != to.length) throw new IllegalArgumentException("lengths differ");
        for (Obj o : objects) {
            byte[] d = data(o); boolean hit = false;
            for (int i = 0; i + from.length <= d.length; i++) {
                int j = 0; while (j < from.length && d[i + j] == from[j]) j++;
                if (j == from.length) { if (!hit) { d = d.clone(); hit = true; } System.arraycopy(to, 0, d, i, to.length); i += from.length - 1; }
            }
            if (hit) { o.newData = d; o.size = d.length; }
        }
    }

    public byte[] write() {
        long origEnd = 0;
        for (Obj o : objects) if (o.newData == null) origEnd = Math.max(origEnd, o.start + o.size);
        Bin.W extra = new Bin.W(!little);
        long cursor = (origEnd + 7) & ~7L;
        for (Obj o : objects) {
            if (o.newData == null) continue;
            while ((cursor + extra.size()) % 8 != 0) extra.u8(0);
            o.start = cursor + extra.size(); o.size = o.newData.length; extra.bytes(o.newData);
        }
        int headerLen = metaStart;
        Bin.W meta = new Bin.W(!little);
        meta.bytes(metaHead);
        meta.i32(types.size()); for (SType t : types) meta.bytes(t.raw);
        meta.i32(objects.size());
        // Unity looks objects up by binary search, so the table must be sorted by path id
        List<Obj> sorted = new ArrayList<>(objects);
        sorted.sort((x, y) -> Long.compare(x.pathId, y.pathId));
        for (Obj o : sorted) {
            meta.align(4, headerLen);
            meta.i64(o.pathId); meta.i64(o.start); meta.i32(o.size); meta.i32(o.typeIndex);
        }
        meta.i32(scripts.size());
        for (Script s : scripts) { meta.i32(s.fileIndex); meta.align(4, headerLen); meta.i64(s.localId); }
        meta.i32(externals.size());
        for (External e : externals) { meta.cstr(e.tempEmpty); meta.bytes(e.guid); meta.i32(e.type); meta.cstr(e.path); }
        meta.bytes(metaTail);
        byte[] mb = meta.toBytes();
        long newDataOffset = Math.max(dataOffset, ((headerLen + mb.length) + 15) & ~15L);
        long fileSize = newDataOffset + cursor + extra.size();
        Bin.W w = new Bin.W(true);
        w.i32(0); w.i32(0); w.i32(version); w.i32(0);
        w.u8(little ? 0 : 1); w.u8(0); w.u8(0); w.u8(0);
        w.i32(mb.length); w.i64(fileSize); w.i64(newDataOffset); w.i64(0);
        w.bytes(mb);
        while (w.size() < newDataOffset) w.u8(0);
        w.bytes(b, (int) dataOffset, (int) origEnd);
        while (w.size() < newDataOffset + cursor) w.u8(0);
        w.bytes(extra.toBytes());
        return w.toBytes();
    }

    public boolean isLittleEndian() { return little; }
}
