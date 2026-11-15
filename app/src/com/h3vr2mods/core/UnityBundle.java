package com.h3vr2mods.core;

import java.io.IOException;
import java.util.*;

/** UnityFS asset bundle: reads LZ4/uncompressed bundles, writes uncompressed ones. */
public final class UnityBundle {
    public static final class Node { public String path; public int flags; public byte[] data; }
    public int formatVersion; public String unityVersion, unityRevision;
    public final List<Node> nodes = new ArrayList<>();

    public static UnityBundle read(byte[] b) throws IOException {
        UnityBundle u = new UnityBundle();
        Bin.R r = new Bin.R(b, 0, true);
        if (!r.cstr().equals("UnityFS")) throw new IOException("not UnityFS");
        u.formatVersion = r.i32(); u.unityVersion = r.cstr(); u.unityRevision = r.cstr();
        r.i64(); int csz = r.i32(), usz = r.i32(), flags = r.i32();
        if (u.formatVersion >= 7) r.align(16, 0);
        byte[] info;
        if ((flags & 0x80) != 0) throw new IOException("block info at end not supported");
        info = decode(b, r.p, csz, usz, flags & 0x3F); r.p += csz;
        if ((flags & 0x200) != 0) r.align(16, 0);
        Bin.R ir = new Bin.R(info, 16, true);
        int nb = ir.i32();
        long total = 0; int[][] blocks = new int[nb][3];
        for (int i = 0; i < nb; i++) { blocks[i][0] = ir.i32(); blocks[i][1] = ir.i32(); blocks[i][2] = ir.u16(); total += blocks[i][0] & 0xFFFFFFFFL; }
        byte[] data = new byte[(int) total]; int dp = 0;
        for (int[] bl : blocks) {
            byte[] d = decode(b, r.p, bl[1], bl[0], bl[2] & 0x3F); r.p += bl[1];
            System.arraycopy(d, 0, data, dp, d.length); dp += d.length;
        }
        int nn = ir.i32();
        for (int i = 0; i < nn; i++) {
            long off = ir.i64(), size = ir.i64(); int fl = ir.i32(); String path = ir.cstr();
            Node n = new Node(); n.path = path; n.flags = fl; n.data = Arrays.copyOfRange(data, (int) off, (int) (off + size));
            u.nodes.add(n);
        }
        return u;
    }

    private static byte[] decode(byte[] b, int off, int csz, int usz, int comp) throws IOException {
        switch (comp) {
            case 0: return Arrays.copyOfRange(b, off, off + csz);
            case 2: case 3: return Lz4.decompress(b, off, csz, usz);
            default: throw new IOException("unsupported compression " + comp);
        }
    }

    public Node node(String suffixOrNull) {
        for (Node n : nodes) if (suffixOrNull == null ? !n.path.endsWith(".resS") && !n.path.endsWith(".resource") : n.path.endsWith(suffixOrNull)) return n;
        return null;
    }

    /** Writes an uncompressed bundle (128 KB blocks, block info and directory stored plainly). */
    public byte[] write() {
        long total = 0; for (Node n : nodes) total += n.data.length;
        // one uncompressed "streamed" block, the way Unity/UnityPy write uncompressed bundles
        Bin.W info = new Bin.W(true);
        info.bytes(new byte[16]); info.i32(1);
        info.i32((int) total); info.i32((int) total); info.i16(0x40);
        info.i32(nodes.size()); long off = 0;
        for (Node n : nodes) { info.i64(off); info.i64(n.data.length); info.i32(n.flags); info.cstr(n.path); off += n.data.length; }
        byte[] ib = info.toBytes();
        Bin.W w = new Bin.W(true);
        w.cstr("UnityFS"); w.i32(formatVersion); w.cstr(unityVersion); w.cstr(unityRevision);
        int sizePos = w.size(); w.i64(0); w.i32(ib.length); w.i32(ib.length); w.i32(0x40);
        if (formatVersion >= 7) w.align(16, 0);
        w.bytes(ib);
        for (Node n : nodes) w.bytes(n.data);
        byte[] out = w.toBytes();
        long size = out.length;
        for (int i = 0; i < 8; i++) out[sizePos + i] = (byte) (size >>> (56 - 8 * i));
        return out;
    }
}
