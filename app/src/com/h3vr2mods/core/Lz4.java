package com.h3vr2mods.core;

/** LZ4 block-format decoder (Unity uses LZ4/LZ4HC blocks in asset bundles). */
public final class Lz4 {
    public static byte[] decompress(byte[] src, int off, int len, int outLen) {
        byte[] dst = new byte[outLen];
        int sp = off, end = off + len, dp = 0;
        while (sp < end) {
            int token = src[sp++] & 0xFF;
            int lit = token >>> 4;
            if (lit == 15) { int b; do { b = src[sp++] & 0xFF; lit += b; } while (b == 255); }
            System.arraycopy(src, sp, dst, dp, lit); sp += lit; dp += lit;
            if (sp >= end) break;
            int offset = (src[sp] & 0xFF) | ((src[sp + 1] & 0xFF) << 8); sp += 2;
            int ml = token & 15;
            if (ml == 15) { int b; do { b = src[sp++] & 0xFF; ml += b; } while (b == 255); }
            ml += 4;
            int mp = dp - offset;
            if (offset >= ml) { System.arraycopy(dst, mp, dst, dp, ml); dp += ml; }
            else { for (int i = 0; i < ml; i++) dst[dp++] = dst[mp++]; }
        }
        if (dp != outLen) throw new IllegalStateException("LZ4 size mismatch " + dp + " != " + outLen);
        return dst;
    }
}
