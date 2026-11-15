package com.h3vr2mods.core;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

/** H3VR2 .hdog content pack: "HDOG"+u8, blobs, TOC {u32 off,u32 size,str7 name,4cc tag}, u32 count, u32 tocOffset. */
public final class Hdog implements Closeable {
    public static final class Entry { public String name, tag; public long offset, size; }
    public final List<Entry> entries = new ArrayList<>();
    public final Map<String, Entry> byName = new HashMap<>();
    private final RandomAccessFile f;

    public Hdog(File file) throws IOException {
        f = new RandomAccessFile(file, "r");
        long end = f.length();
        byte[] head = new byte[5]; f.readFully(head);
        if (head[0] != 'H' || head[1] != 'D' || head[2] != 'O' || head[3] != 'G') throw new IOException("not an HDOG file: " + file);
        byte[] foot = new byte[8]; f.seek(end - 8); f.readFully(foot);
        Bin.R r = new Bin.R(foot, 0, false);
        int count = r.i32(); long toc = r.u32();
        byte[] t = new byte[(int) (end - 8 - toc)]; f.seek(toc); f.readFully(t);
        r = new Bin.R(t, 0, false);
        for (int i = 0; i < count; i++) {
            Entry e = new Entry(); e.offset = r.u32(); e.size = r.u32();
            int n = 0, s = 0, c; do { c = r.u8(); n |= (c & 0x7F) << s; s += 7; } while (c >= 0x80);
            e.name = new String(r.bytes(n), StandardCharsets.UTF_8);
            e.tag = new String(r.bytes(4), StandardCharsets.US_ASCII);
            entries.add(e); byName.put(e.name, e);
        }
    }

    public byte[] read(String name) throws IOException {
        Entry e = byName.get(name); if (e == null) throw new IOException("missing entry " + name);
        byte[] b = new byte[(int) e.size]; f.seek(e.offset); f.readFully(b); return b;
    }

    public Map<String, Object> manifest() throws IOException { return decodeManifest(read("manifest")); }

    public static Map<String, Object> decodeManifest(byte[] gz) throws IOException {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        try (GZIPInputStream in = new GZIPInputStream(new ByteArrayInputStream(gz))) { in.transferTo(o); }
        String s = o.toString(StandardCharsets.UTF_8);
        if (s.startsWith("﻿")) s = s.substring(1);
        return Json.obj(Json.parse(s));
    }

    public static byte[] encodeManifest(Map<String, Object> m) throws IOException {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        try (GZIPOutputStream g = new GZIPOutputStream(o)) { g.write(("﻿" + Json.write(m)).getBytes(StandardCharsets.UTF_8)); }
        return o.toByteArray();
    }

    @Override public void close() throws IOException { f.close(); }

    /** Streamed writer for a new pack. */
    public static final class Writer implements Closeable {
        private final OutputStream out; private long pos = 5;
        private final List<Entry> toc = new ArrayList<>();
        public Writer(File file) throws IOException {
            out = new BufferedOutputStream(new FileOutputStream(file), 1 << 20);
            out.write(new byte[]{'H', 'D', 'O', 'G', 0});
        }
        public void add(String name, String tag, byte[] data) throws IOException {
            Entry e = new Entry(); e.name = name; e.tag = tag; e.offset = pos; e.size = data.length;
            out.write(data); pos += data.length; toc.add(e);
        }
        @Override public void close() throws IOException {
            Bin.W w = new Bin.W(false);
            for (Entry e : toc) {
                w.i32((int) e.offset); w.i32((int) e.size);
                byte[] n = e.name.getBytes(StandardCharsets.UTF_8); int len = n.length;
                while (len >= 0x80) { w.u8((len & 0x7F) | 0x80); len >>>= 7; } w.u8(len);
                w.bytes(n); w.bytes(e.tag.getBytes(StandardCharsets.US_ASCII));
            }
            w.i32(toc.size()); w.i32((int) pos);
            out.write(w.toBytes()); out.close();
        }
    }
}
