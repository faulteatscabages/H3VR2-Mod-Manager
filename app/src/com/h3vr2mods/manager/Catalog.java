package com.h3vr2mods.manager;

import com.h3vr2mods.core.Json;

import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * Online mod catalog: a JSON file hosted anywhere (e.g. GitHub):
 * {
 *   "app":  {"versionCode": 2, "versionName": "1.1", "url": "https://…/H3VR2-ModManager.apk", "notes": "…"},
 *   "mods": [{"id": "Mod_PortalGun", "name": "…", "description": "…", "kind": "weapon", "version": 2,
 *             "url": "https://…/Mod_PortalGun.h3mod", "size": 1669070}]
 * }
 * Relative URLs are resolved against the catalog's own URL.
 */
final class Catalog {
    /** Where the app looks for mods. Set this before building a public release (see README). */
    static final String DEFAULT_URL = "https://faulteatscabages.github.io/H3VR2-Mod-Manager/catalog.json";

    static final class Entry { String id, name, description, kind, url; long version, size; }
    static final class App { long versionCode; String versionName, url, notes; }

    final List<Entry> mods = new ArrayList<>(); App app;

    static Catalog fetch(String url) throws IOException {
        Map<String, Object> m = Json.obj(Json.parse(new String(get(url), StandardCharsets.UTF_8)));
        Catalog c = new Catalog();
        if (m.get("app") != null) {
            Map<String, Object> a = Json.obj(m.get("app"));
            c.app = new App(); c.app.versionCode = num(a.get("versionCode")); c.app.versionName = str(a.get("versionName"));
            c.app.url = resolve(url, str(a.get("url"))); c.app.notes = str(a.get("notes"));
        }
        for (Object o : Json.arr(m.getOrDefault("mods", new ArrayList<>()))) {
            Map<String, Object> e = Json.obj(o);
            Entry x = new Entry();
            x.id = str(e.get("id")); x.name = str(e.get("name")); x.description = str(e.get("description"));
            x.kind = str(e.get("kind")); x.version = num(e.get("version")); x.size = num(e.get("size"));
            x.url = resolve(url, str(e.get("url")));
            if (x.id != null && x.url != null) c.mods.add(x);
        }
        return c;
    }

    static byte[] get(String url) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(10000); c.setReadTimeout(30000); c.setInstanceFollowRedirects(true);
        c.setRequestProperty("User-Agent", "H3VR2ModManager");
        if (c.getResponseCode() / 100 != 2) throw new IOException("HTTP " + c.getResponseCode() + " for " + url);
        try (InputStream in = c.getInputStream()) { ByteArrayOutputStream o = new ByteArrayOutputStream(); in.transferTo(o); return o.toByteArray(); }
    }

    static void download(String url, File dst) throws IOException {
        File tmp = new File(dst.getPath() + ".part");
        try (OutputStream o = new FileOutputStream(tmp)) { o.write(get(url)); }
        dst.delete();
        if (!tmp.renameTo(dst)) throw new IOException("could not save " + dst.getName());
    }

    private static String resolve(String base, String u) {
        if (u == null) return null;
        try { return new URL(new URL(base), u).toString(); } catch (Exception e) { return u; }
    }
    private static String str(Object o) { return o == null ? null : o.toString(); }
    private static long num(Object o) { return o instanceof Number ? ((Number) o).longValue() : 0; }
}
