package com.h3vr2mods.core;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/**
 * Applies mods (format 2) to the player's own game content and writes two add-on packs:
 *   footlong.aaa_mods.hdog  patched core bundle + mod bundles (read first, so its core bundle wins)
 *   footlong.zzz_mods.hdog  merged manifest (read last, so its manifest wins)
 *
 * A mod is a list of operations against the game as it is on the headset: clone game objects and
 * edit their fields, edit existing game objects, and build item bundles by cloning a game item's
 * bundle and editing it. Because everything is addressed by name and field, mods keep working across
 * game updates unless the things they refer to are removed or renamed.
 */
public final class Patcher {
    public static final String FIRST = "footlong.aaa_mods.hdog", LAST = "footlong.zzz_mods.hdog";
    public static final String CORE = "footlong.base";

    public interface Log { void log(String s); }

    public static final class Result { public final List<String> installed = new ArrayList<>(); public final Map<String, String> skipped = new LinkedHashMap<>(); }

    public static void uninstall(File gameDir) { new File(gameDir, FIRST).delete(); new File(gameDir, LAST).delete(); }

    public static Result apply(File basePack, List<ModPackage> mods, File outDir, Log log) throws Exception {
        Result res = new Result();
        List<ModPackage> todo = new ArrayList<>(mods);
        while (true) {
            if (todo.isEmpty()) { uninstall(outDir); log.log("No mods to install; add-on files removed."); return res; }
            try {
                build(basePack, todo, outDir, log);
                for (ModPackage m : todo) res.installed.add(m.name);
                log.log("Installed " + todo.size() + " mod(s).");
                return res;
            } catch (Failed f) {
                res.skipped.put(f.mod.name, f.getMessage());
                log.log("Skipping " + f.mod.name + ": " + f.getMessage());
                todo.remove(f.mod);
            }
        }
    }

    private static final class Failed extends Exception { final ModPackage mod; Failed(ModPackage m, String msg) { super(msg); mod = m; } }

    /** Everything about the player's core bundle we need while applying mods. */
    private static final class Core {
        SerializedFile sf; Map<String, Long> scripts = new HashMap<>(); Map<Long, String> scriptOf = new HashMap<>();
        Map<String, Long> keys = new HashMap<>(); SerializedFile.Obj abObj; Map<String, Object> ab; List<Object> preload, container;

        long key(String k) { Long p = keys.get(k); if (p == null) throw new Ops.ModError("the game has no '" + k + "'"); return p; }
        Map<String, Object> tree(long pid) { return Json.obj(sf.readTree(sf.byId.get(pid))); }
        String scriptName(long pid) {
            Object t = sf.readTree(sf.byId.get(pid));
            Object s = Json.obj(t).get("m_Script");
            return s == null ? null : scriptOf.get((Long) Json.obj(s).get("m_PathID"));
        }
        long propOf(String key, String script) {
            for (Object p : Json.arr(tree(key(key)).get("_propertiesList"))) {
                long pid = (Long) Json.obj(p).get("m_PathID");
                String sn = scriptName(pid);
                if (script.equals(sn) || (sn != null && sn.endsWith("." + script))) return pid;
            }
            throw new Ops.ModError("'" + key + "' has no " + script);
        }
        long script(String name) {
            Long p = scripts.get(name);
            if (p != null) return p;
            for (Map.Entry<String, Long> e : scripts.entrySet()) if (e.getKey().endsWith("." + name)) { if (p != null) throw new Ops.ModError("script name " + name + " is ambiguous"); p = e.getValue(); }
            if (p == null) throw new Ops.ModError("the game has no script " + name);
            return p;
        }

        /** All objects of a script class whose fields mention a string, e.g. every loot table listing an item. */
        List<Long> where(Map<String, Object> w) {
            String script = (String) w.get("script"), needle = (String) w.get("contains");
            Long scriptPid = script(script);
            List<Long> out = new ArrayList<>();
            for (SerializedFile.Obj o : sf.objects) {
                SerializedFile.SType t = sf.type(o);
                if (t.classId != 114 || t.scriptTypeIndex < 0 || t.scriptTypeIndex >= sf.scripts.size()) continue;
                if (sf.scripts.get(t.scriptTypeIndex).localId != scriptPid) continue;
                if (needle == null || Ops.contains(sf.readTree(o), needle)) out.add(o.pathId);
            }
            return out;
        }

        long resolve(Map<String, Object> s, Map<String, Long> locals) {
            if (s.containsKey("local")) { Long p = locals.get((String) s.get("local")); if (p == null) throw new Ops.ModError("bad local " + s.get("local")); return p; }
            if (s.containsKey("prop_of")) return propOf((String) s.get("prop_of"), (String) s.get("script"));
            if (s.containsKey("key")) return key((String) s.get("key"));
            if (s.containsKey("script")) return script((String) s.get("script"));
            if (s.containsKey("null")) return 0;
            throw new Ops.ModError("bad reference " + s);
        }
    }

    private static void build(File basePack, List<ModPackage> mods, File outDir, Log log) throws Exception {
        log.log("Reading game content…");
        Map<String, Object> manifest; UnityBundle bundle; Core c = new Core();
        Map<String, byte[]> outBundles = new LinkedHashMap<>();
        try (Hdog base = new Hdog(basePack)) {
            manifest = base.manifest();
            bundle = UnityBundle.read(base.read(CORE));
            UnityBundle.Node cabNode = bundle.node(null);
            c.sf = SerializedFile.read(cabNode.data);
            for (SerializedFile.Obj o : c.sf.objects) {
                int cls = c.sf.type(o).classId;
                if (cls == 115) {
                    Map<String, Object> s = Json.obj(c.sf.readTree(o));
                    String ns = (String) s.get("m_Namespace"), cn = (String) s.get("m_ClassName");
                    String full = ns == null || ns.isEmpty() ? cn : ns + "." + cn;
                    c.scripts.put(full, o.pathId); c.scriptOf.put(o.pathId, full);
                } else if (cls == 142) c.abObj = o;
            }
            c.ab = Json.obj(c.sf.readTree(c.abObj));
            c.preload = Json.arr(c.ab.get("m_PreloadTable")); c.container = Json.arr(c.ab.get("m_Container"));
            for (Object e : c.container) {
                Map<String, Object> p = Json.obj(e);
                c.keys.putIfAbsent((String) p.get("first"), (Long) Json.obj(Json.obj(p.get("second")).get("asset")).get("m_PathID"));
            }
            Map<String, Object> a2b = Json.obj(manifest.get("AssetToBundleMap"));
            Map<String, Object> deps = Json.obj(manifest.get("BundleDependencyMap"));
            log.log("Indexed " + c.sf.objects.size() + " game objects.");

            for (ModPackage m : mods) {
                log.log("Adding " + m.name + "…");
                try {
                    Map<String, Object> core = m.meta.containsKey("core") ? Json.obj(m.meta.get("core")) : new HashMap<>();
                    Map<String, Long> locals = new HashMap<>();
                    applyCore(c, m, core, locals);
                    for (Object oo : Json.arr(m.meta.getOrDefault("options", new ArrayList<>()))) {
                        Map<String, Object> opt = Json.obj(oo);
                        if (m.options.contains((String) opt.get("id"))) applyCore(c, m, Json.obj(opt.get("core")), locals);
                    }
                    for (Object bo : m.meta.containsKey("bundles") ? Json.arr(m.meta.get("bundles")) : new ArrayList<>()) {
                        Map<String, Object> b = Json.obj(bo);
                        String name = (String) b.get("name");
                        if (outBundles.containsKey(name) || base.byName.containsKey(name)) throw new Ops.ModError("bundle " + name + " already exists");
                        if (b.containsKey("file")) outBundles.put(name, m.entry((String) b.get("file")));
                        else {
                            String donorKey = (String) Json.obj(b.get("donor")).get("item");
                            String guid = (String) Json.obj(c.tree(c.key(donorKey)).get("_prefab")).get("_assetGuid");
                            String donorBundle = (String) a2b.get(guid);
                            if (donorBundle == null) throw new Ops.ModError("can't find the bundle of " + donorKey);
                            outBundles.put(name, buildBundle(c, m, b, base.read(donorBundle)));
                            if (!b.containsKey("deps")) deps.put(name, new ArrayList<>(Json.arr(deps.getOrDefault(donorBundle, new ArrayList<>()))));
                        }
                        if (b.containsKey("deps")) deps.put(name, new ArrayList<>(Json.arr(b.get("deps"))));
                        for (Object d : Json.arr(deps.getOrDefault(name, new ArrayList<>())))
                            if (!base.byName.containsKey((String) d) && !outBundles.containsKey((String) d)) throw new Ops.ModError("needs " + d + ", which this game version doesn't have");
                        for (Object g : Json.arr(b.getOrDefault("guids", new ArrayList<>()))) a2b.put((String) g, name);
                    }
                } catch (Ops.ModError | ClassCastException | NullPointerException | IndexOutOfBoundsException e) {
                    throw new Failed(m, e instanceof Ops.ModError ? e.getMessage() : "doesn't fit this game version (" + e + ")");
                }
            }
        }

        c.container.sort((x, y) -> compareUtf8((String) Json.obj(x).get("first"), (String) Json.obj(y).get("first")));
        c.sf.writeTree(c.abObj, c.ab);
        log.log("Writing patched game files…");
        bundle.node(null).data = c.sf.write();
        byte[] core = bundle.write();
        byte[] man = Hdog.encodeManifest(manifest);
        File first = new File(outDir, FIRST + ".tmp"), last = new File(outDir, LAST + ".tmp");
        try (Hdog.Writer w = new Hdog.Writer(first)) {
            w.add("manifest", "INFO", man);
            w.add(CORE, "UABP", core);
            for (Map.Entry<String, byte[]> e : outBundles.entrySet()) w.add(e.getKey(), "UABR", e.getValue());
        }
        try (Hdog.Writer w = new Hdog.Writer(last)) { w.add("manifest", "INFO", man); }
        finish(first, new File(outDir, FIRST)); finish(last, new File(outDir, LAST));
    }

    private static void applyCore(Core c, ModPackage m, Map<String, Object> core, Map<String, Long> locals) throws Exception {
        Map<Long, Long> cloneOf = new HashMap<>();     // source path id -> new path id
        Map<String, Map<String, Object>> trees = new HashMap<>();
        List<Object> news = Json.arr(core.getOrDefault("new", new ArrayList<>()));
        List<Map<String, Object>> made = new ArrayList<>();
        for (Object no : news) {
            Map<String, Object> n = Json.obj(no);
            String onlyIf = (String) n.get("unless_exists");
            if (onlyIf != null && c.keys.containsKey(onlyIf)) { locals.put((String) n.get("as"), c.keys.get(onlyIf)); continue; }
            long src = c.resolve(Json.obj(n.get("from")), locals);
            long id = newPathId(m.id + ":" + n.get("as"), c.sf);
            locals.put((String) n.get("as"), id); cloneOf.put(src, id);
            SerializedFile.Obj so = c.sf.byId.get(src);
            c.sf.add(id, so.typeIndex, c.sf.data(so));
            trees.put((String) n.get("as"), Json.obj(c.sf.readTree(so)));
            made.add(n);
        }
        Ops.Resolver r = s -> Ops.pptr(0, c.resolve(s, locals));
        for (Map<String, Object> n : made) {
            Map<String, Object> t = trees.get((String) n.get("as"));
            Ops.apply(t, Json.arr(n.getOrDefault("edits", new ArrayList<>())), r);
            c.sf.writeTree(c.sf.byId.get(locals.get((String) n.get("as"))), t);
        }
        for (Object eo : Json.arr(core.getOrDefault("edit", new ArrayList<>()))) {
            Map<String, Object> e = Json.obj(eo);
            Map<String, Object> target = Json.obj(e.get("target"));
            List<Long> targets = new ArrayList<>();
            if (target.containsKey("where")) targets.addAll(c.where(Json.obj(target.get("where"))));
            else targets.add(c.resolve(target, locals));
            for (long pid : targets) {
                SerializedFile.Obj o = c.sf.byId.get(pid);
                Object t = c.sf.readTree(o);
                Ops.apply(t, Json.arr(e.get("edits")), r);
                c.sf.writeTree(o, t);
            }
        }
        for (Object eo : Json.arr(core.getOrDefault("container", new ArrayList<>()))) {
            Map<String, Object> e = Json.obj(eo);
            String key = (String) e.get("key");
            if (c.keys.containsKey(key)) {
                if (Boolean.TRUE.equals(e.get("shared"))) continue;
                throw new Ops.ModError("the game already has an item called " + key);
            }
            long asset = c.resolve(Json.obj(e.get("asset")), locals);
            int start = c.preload.size();
            Object pre = e.get("preload");
            if (pre instanceof Map && Json.obj(pre).containsKey("like")) {
                String like = (String) Json.obj(pre).get("like");
                Map<String, Object> info = null;
                for (Object ce : c.container) if (like.equals(Json.obj(ce).get("first"))) info = Json.obj(Json.obj(ce).get("second"));
                if (info == null) throw new Ops.ModError("the game has no '" + like + "'");
                int pi = ((Long) info.get("preloadIndex")).intValue(), ps = ((Long) info.get("preloadSize")).intValue();
                for (int i = pi; i < pi + ps; i++) {
                    Map<String, Object> p = Json.obj(c.preload.get(i));
                    long fid = (Long) p.get("m_FileID"), pid = (Long) p.get("m_PathID");
                    if (fid != 0) c.preload.add(Ops.pptr((int) fid, pid));
                    else if (cloneOf.containsKey(pid)) c.preload.add(Ops.pptr(0, cloneOf.get(pid)));
                    else if (c.scriptOf.containsKey(pid)) c.preload.add(Ops.pptr(0, pid));
                    // other game objects (e.g. sub-definitions the mod didn't clone) are left out
                }
            } else for (Object ref : Json.arr(pre)) c.preload.add(Ops.pptr(0, c.resolve(Json.obj(ref), locals)));
            LinkedHashMap<String, Object> info = new LinkedHashMap<>();
            info.put("preloadIndex", (long) start); info.put("preloadSize", (long) (c.preload.size() - start)); info.put("asset", Ops.pptr(0, asset));
            LinkedHashMap<String, Object> pair = new LinkedHashMap<>(); pair.put("first", key); pair.put("second", info);
            c.container.add(pair); c.keys.put(key, asset);
        }
    }

    /** Clones a game item's bundle and applies the mod's changes to it. */
    private static byte[] buildBundle(Core c, ModPackage m, Map<String, Object> b, byte[] donorBytes) throws Exception {
        UnityBundle ub = UnityBundle.read(donorBytes);
        UnityBundle.Node node = ub.node(null);
        SerializedFile sf = SerializedFile.read(node.data);
        String oldCab = node.path, newCab = (String) b.get("cab");
        if (oldCab.length() != newCab.length()) throw new Ops.ModError("bad bundle id");
        for (UnityBundle.Node n : ub.nodes) n.path = n.path.replace(oldCab, newCab);
        sf.replaceBytes(oldCab.getBytes(StandardCharsets.UTF_8), newCab.getBytes(StandardCharsets.UTF_8));
        for (Object t : Json.arr(b.getOrDefault("types", new ArrayList<>()))) sf.addType(Base64.getDecoder().decode((String) t));
        Ops.Resolver r = s -> {
            if (s.containsKey("ext")) return Ops.pptr(sf.externalId((String) s.get("ext")), ((Number) s.get("path")).longValue());
            if (s.containsKey("path")) return Ops.pptr(0, ((Number) s.get("path")).longValue());
            return Ops.pptr(0, c.resolve(s, new HashMap<>()));
        };
        for (Object no : Json.arr(b.getOrDefault("new", new ArrayList<>()))) {
            Map<String, Object> n = Json.obj(no);
            byte[] data;
            if (n.containsKey("file")) data = m.entry((String) n.get("file"));
            else data = Base64.getDecoder().decode((String) n.get("data"));
            for (Object xo : Json.arr(n.getOrDefault("ext", new ArrayList<>()))) {
                Map<String, Object> x = Json.obj(xo);
                putLE32(data, ((Number) x.get("off")).intValue(), sf.externalId((String) x.get("cab")));
            }
            int ti = sf.findType(((Number) n.get("class")).intValue(), null);
            if (ti < 0) throw new Ops.ModError("missing type " + n.get("class"));
            sf.add(((Number) n.get("path")).longValue(), ti, data);
        }
        for (Object eo : Json.arr(b.getOrDefault("edit", new ArrayList<>()))) {
            Map<String, Object> e = Json.obj(eo);
            SerializedFile.Obj o = sf.byId.get(((Number) e.get("path")).longValue());
            if (o == null) throw new Ops.ModError("the game item it's based on has changed");
            Object t = sf.readTree(o);
            Ops.apply(t, Json.arr(e.get("edits")), r);
            sf.writeTree(o, t);
        }
        // asset bundle index: new name, new guids, register new objects for preloading
        SerializedFile.Obj abo = null;
        for (SerializedFile.Obj o : sf.objects) if (sf.type(o).classId == 142) abo = o;
        Map<String, Object> ab = Json.obj(sf.readTree(abo));
        String name = (String) b.get("name");
        ab.put("m_Name", name); ab.put("m_AssetBundleName", name);
        List<Object> pre = Json.arr(ab.get("m_PreloadTable")), cont = Json.arr(ab.get("m_Container"));
        for (Object ro : Json.arr(b.getOrDefault("rename", new ArrayList<>()))) {
            Map<String, Object> rn = Json.obj(ro);
            Map<String, Object> from = Json.obj(rn.get("from"));
            Object v = Ops.get(c.tree(c.resolve(Json.obj(from.get("of")), new HashMap<>())), Json.arr(from.get("path")));
            boolean hit = false;
            for (Object ce : cont) if (v.equals(Json.obj(ce).get("first"))) { Json.obj(ce).put("first", rn.get("to")); hit = true; }
            if (!hit) throw new Ops.ModError("the game item it's based on has changed");
        }
        for (Map.Entry<String, Object> pa : Json.obj(b.getOrDefault("preload_add", new LinkedHashMap<>())).entrySet()) {
            for (Object ce : cont) {
                if (!pa.getKey().equals(Json.obj(ce).get("first"))) continue;
                Map<String, Object> info = Json.obj(Json.obj(ce).get("second"));
                int pi = ((Long) info.get("preloadIndex")).intValue(), ps = ((Long) info.get("preloadSize")).intValue();
                int start = pre.size();
                for (int i = pi; i < pi + ps; i++) pre.add(pre.get(i));
                for (Object p : Json.arr(pa.getValue())) pre.add(Ops.pptr(0, ((Number) p).longValue()));
                info.put("preloadIndex", (long) start); info.put("preloadSize", (long) (pre.size() - start));
            }
        }
        cont.sort((x, y) -> compareUtf8((String) Json.obj(x).get("first"), (String) Json.obj(y).get("first")));
        sf.writeTree(abo, ab);
        node.data = sf.write();
        return ub.write();
    }

    private static void finish(File tmp, File dst) throws IOException {
        dst.delete();
        if (!tmp.renameTo(dst)) throw new IOException("could not rename " + tmp + " to " + dst);
        // the game opens packs read/write, so they must be writable by it
        dst.setReadable(true, false); dst.setWritable(true, false);
    }

    private static long newPathId(String seed, SerializedFile sf) throws Exception {
        byte[] h = MessageDigest.getInstance("SHA-256").digest(seed.getBytes(StandardCharsets.UTF_8));
        long id = 0; for (int i = 0; i < 8; i++) id = (id << 8) | (h[i] & 0xFF);
        while (id == 0 || id == 1 || sf.byId.containsKey(id)) id++;
        return id;
    }

    private static int compareUtf8(String a, String b) {
        byte[] x = a.getBytes(StandardCharsets.UTF_8), y = b.getBytes(StandardCharsets.UTF_8);
        for (int i = 0; i < Math.min(x.length, y.length); i++) { int d = (x[i] & 0xFF) - (y[i] & 0xFF); if (d != 0) return d; }
        return x.length - y.length;
    }

    private static void putLE32(byte[] b, int o, int v) { for (int i = 0; i < 4; i++) b[o + i] = (byte) (v >>> (8 * i)); }
}
