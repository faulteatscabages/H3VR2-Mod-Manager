package com.h3vr2mods.core;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

/** Small little/big-endian reader and writer over byte arrays. */
public final class Bin {
    public static final class R {
        public final byte[] b; public int p; public boolean be;
        public R(byte[] b, int p, boolean bigEndian) { this.b = b; this.p = p; this.be = bigEndian; }
        public int u8() { return b[p++] & 0xFF; }
        public int i16() { int v = be ? ((b[p] & 0xFF) << 8) | (b[p + 1] & 0xFF) : (b[p] & 0xFF) | ((b[p + 1] & 0xFF) << 8); p += 2; return (short) v; }
        public int u16() { return i16() & 0xFFFF; }
        public int i32() {
            int v = be ? ((b[p] & 0xFF) << 24) | ((b[p + 1] & 0xFF) << 16) | ((b[p + 2] & 0xFF) << 8) | (b[p + 3] & 0xFF)
                       : (b[p] & 0xFF) | ((b[p + 1] & 0xFF) << 8) | ((b[p + 2] & 0xFF) << 16) | ((b[p + 3] & 0xFF) << 24);
            p += 4; return v;
        }
        public long u32() { return i32() & 0xFFFFFFFFL; }
        public long i64() { long hi, lo; if (be) { hi = u32(); lo = u32(); } else { lo = u32(); hi = u32(); } return (hi << 32) | lo; }
        public byte[] bytes(int n) { byte[] o = new byte[n]; System.arraycopy(b, p, o, 0, n); p += n; return o; }
        public String cstr() { int s = p; while (b[p] != 0) p++; String r = new String(b, s, p - s, StandardCharsets.UTF_8); p++; return r; }
        public void align(int n, int base) { int rel = p - base; p += (n - rel % n) % n; }
    }

    public static final class W {
        public final ByteArrayOutputStream o; public boolean be;
        public W(boolean bigEndian) { o = new ByteArrayOutputStream(1 << 16); be = bigEndian; }
        public int size() { return o.size(); }
        public void u8(int v) { o.write(v); }
        public void i16(int v) { if (be) { o.write(v >>> 8); o.write(v); } else { o.write(v); o.write(v >>> 8); } }
        public void i32(int v) {
            if (be) { o.write(v >>> 24); o.write(v >>> 16); o.write(v >>> 8); o.write(v); }
            else { o.write(v); o.write(v >>> 8); o.write(v >>> 16); o.write(v >>> 24); }
        }
        public void i64(long v) { if (be) { i32((int) (v >>> 32)); i32((int) v); } else { i32((int) v); i32((int) (v >>> 32)); } }
        public void bytes(byte[] b) { o.write(b, 0, b.length); }
        public void bytes(byte[] b, int off, int len) { o.write(b, off, len); }
        public void cstr(String s) { bytes(s.getBytes(StandardCharsets.UTF_8)); o.write(0); }
        public void align(int n, int base) { while ((o.size() + base) % n != 0) o.write(0); }
        public byte[] toBytes() { return o.toByteArray(); }
    }
}
