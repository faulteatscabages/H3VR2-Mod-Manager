package com.h3vr2mods.core;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** A .h3mod package (zip with mod.json, bundles/, icon.png). */
public final class ModPackage {
    public final File file; public final Map<String, Object> meta;
    public final String id, name, description, kind;
    public final long version;
    /** Option ids the player turned on for this mod. */
    public final Set<String> options = new HashSet<>();

    public ModPackage(File f) throws IOException {
        file = f;
        try (ZipFile z = new ZipFile(f)) {
            ZipEntry e = z.getEntry("mod.json");
            if (e == null) throw new IOException(f.getName() + ": no mod.json");
            meta = Json.obj(Json.parse(new String(readAll(z.getInputStream(e)), StandardCharsets.UTF_8)));
        }
        id = (String) meta.get("id");
        name = meta.containsKey("name") ? (String) meta.get("name") : id;
        description = meta.containsKey("description") ? (String) meta.get("description") : "";
        kind = meta.containsKey("kind") ? (String) meta.get("kind") : "mod";
        version = meta.get("version") instanceof Number ? ((Number) meta.get("version")).longValue() : 0;
        long fmt = (Long) meta.get("format"); if (fmt != 2L) throw new IOException(f.getName() + ": made for a different version of the mod manager (format " + fmt + ")");
    }

    public byte[] entry(String path) throws IOException {
        try (ZipFile z = new ZipFile(file)) {
            ZipEntry e = z.getEntry(path); return e == null ? null : readAll(z.getInputStream(e));
        }
    }

    public List<Map<String, Object>> optionList() {
        List<Map<String, Object>> o = new ArrayList<>();
        for (Object x : Json.arr(meta.getOrDefault("options", new ArrayList<>()))) o.add(Json.obj(x));
        return o;
    }

    public byte[] icon() { try { return entry("icon.png"); } catch (IOException e) { return null; } }

    static byte[] readAll(InputStream in) throws IOException {
        try (InputStream i = in) { ByteArrayOutputStream o = new ByteArrayOutputStream(); i.transferTo(o); return o.toByteArray(); }
    }
}
