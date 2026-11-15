"""Export built weapons as .h3mod packages (format 2) for the on-headset mod manager.

  python export_mods.py <original.hdog> <built.hdog> <build_out_dir> <dest_dir>

Format 2 describes a mod as operations against the player's own game, instead of frozen copies:

  core.new        clone a game object (an item definition, a sub-definition, a spawner folder…)
                  and apply field edits to the clone
  core.edit       edit an existing game object (e.g. add an item to a loot table)
  core.container  register new objects under a name (with preload list)
  bundles[]       build an item bundle by cloning a game item's bundle on the headset, then:
                  add types/objects (our model, materials, textures), apply field edits to the
                  donor's objects, rename the bundle, swap the asset GUIDs, extend preload lists

References inside values are written as {"$ref": {...}}: {"local": name} (an object this mod
creates), {"key": name} (a named game object), {"script": class}, {"prop_of": item, "script": class}
(a sub-definition of a game item), {"path": id} / {"ext": cab, "path": id} (inside a bundle).
"""
import base64, io, json, os, struct, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hdog import Hdog
import UnityPy
from UnityPy.streams import EndianBinaryWriter
from weapons import WEAPONS, MOD_FOLDER

FORMAT = 2
FOLDER_KEY = f"ItemSpawnerFolder/{MOD_FOLDER}"


def open_bundle(h, name):
    env = UnityPy.load(h.read(name))
    bf = list(env.files.values())[0]
    cab = next(k for k in bf.files if not k.endswith((".resS", ".resource")))
    return bf, bf.files[cab], cab


def script_name(o):
    s = o.read()
    return f"{s.m_Namespace}.{s.m_ClassName}" if s.m_Namespace else s.m_ClassName


def is_pptr(x):
    return isinstance(x, dict) and set(x.keys()) == {"m_FileID", "m_PathID"}


def normalize(x, ref, strmap=None):
    """Type-tree value -> JSON-able value with PPtrs replaced by {"$ref": token}."""
    if is_pptr(x):
        return {"$ref": ref(x["m_FileID"], x["m_PathID"])}
    if isinstance(x, dict):
        return {k: normalize(v, ref, strmap) for k, v in x.items()}
    if isinstance(x, tuple) and len(x) == 2:
        return {"first": normalize(x[0], ref, strmap), "second": normalize(x[1], ref, strmap)}
    if isinstance(x, (list, tuple)):
        return [normalize(v, ref, strmap) for v in x]
    if isinstance(x, (bytes, bytearray, memoryview)):
        return {"$bytes": base64.b64encode(bytes(x)).decode()}
    if isinstance(x, str) and strmap:
        for a, b in strmap:
            x = x.replace(a, b)
    return x


def atomic(x):
    return isinstance(x, dict) and ("$ref" in x or "$bytes" in x)


def diff(a, b, path=()):
    if atomic(a) or atomic(b) or type(a) != type(b):
        return [] if a == b else [{"path": list(path), "set": b}]
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return [{"path": list(path), "set": b}]
        out = []
        for k in b:
            out += diff(a[k], b[k], path + (k,))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [{"path": list(path), "set": b}]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, path + (i,))
        # many element edits on one list: just set the list
        return out if len(out) <= max(8, len(a) // 4) else [{"path": list(path), "set": b}]
    return [] if a == b else [{"path": list(path), "set": b}]


def raw_type(sf, st):
    w = EndianBinaryWriter(endian="<")
    st.write(sf, w, False)
    return base64.b64encode(w.bytes).decode()


def main(orig_path, built_path, out_dir, dest):
    os.makedirs(dest, exist_ok=True)
    ho, hb = Hdog(orig_path), Hdog(built_path)
    mo = ho.manifest()
    _, so, _ = open_bundle(ho, "footlong.base")
    _, sb, _ = open_bundle(hb, "footlong.base")
    scripts = {pid: script_name(o) for pid, o in sb.objects.items() if o.type.name == "MonoScript"}
    tree_o = {}
    def to(pid):
        if pid not in tree_o: tree_o[pid] = so.objects[pid].read_typetree()
        return tree_o[pid]
    ab_o = so.objects[1].read_typetree(); ab_b = sb.objects[1].read_typetree()
    key_of = {}
    for k, v in ab_o["m_Container"]:
        key_of.setdefault(v["asset"]["m_PathID"], k)
    cont_b = {k: v for k, v in ab_b["m_Container"]}

    def mb_script(sf, pid):
        return scripts.get(sf.objects[pid].read_typetree()["m_Script"]["m_PathID"])

    # Modded spawner folder: which game folder it was cloned from
    fold_pid = cont_b[FOLDER_KEY]["asset"]["m_PathID"]
    fold_tree = sb.objects[fold_pid].read_typetree()
    tmpl_key = None
    for pid, k in key_of.items():
        if k.startswith("ItemSpawnerFolder/") and so.objects[pid].type.name == "MonoBehaviour":
            t = to(pid)
            if t.get("_parent", {}).get("_refId") == fold_tree["_parent"]["_refId"]:
                tmpl_key = k; break

    # which loot tables / groups mention which items
    loot_refs, loot_refs_by_ref = {}, {}
    for pid, o in so.objects.items():
        if o.type.name != "MonoBehaviour": continue
        t = o.read_typetree(); cls = scripts.get(t["m_Script"]["m_PathID"], "")
        if cls.split(".")[-1] not in ("LootTable", "LootGroup"): continue
        loot_refs[pid] = cls
        for e in t.get("loot", []):
            for v in e.values():
                if isinstance(v, dict) and v.get("_refId"):
                    loot_refs_by_ref.setdefault(v["_refId"], set()).add(pid)

    for w in WEAPONS:
        wid, donor = w["id"], w["donor"]
        print("exporting", wid)
        donor_pid = next(p for p, k in key_of.items() if k == donor)
        new_pid = cont_b[wid]["asset"]["m_PathID"]
        donor_def, new_def = to(donor_pid), sb.objects[new_pid].read_typetree()

        # --- core: locals and their sources
        locals_ = {new_pid: "def"}
        source = {"def": {"key": donor}}
        donor_side = {donor_pid: "def"}
        donor_props = {mb_script(so, p["m_PathID"]): p["m_PathID"] for p in donor_def["_propertiesList"]}
        for p in new_def["_propertiesList"]:
            cls = mb_script(sb, p["m_PathID"])
            name = "p_" + cls
            locals_[p["m_PathID"]] = name
            source[name] = {"prop_of": donor, "script": cls}
            donor_side[donor_props[cls]] = name
        locals_[fold_pid] = "folder"; donor_side[next(p for p, k in key_of.items() if k == tmpl_key)] = "folder"

        def ref_core(side, lenient=False):
            def ref(fid, pid):
                if fid != 0: raise SystemExit(f"{wid}: external reference in a definition")
                if pid == 0: return {"null": True}
                if pid in side: return {"local": side[pid]}
                if pid in scripts: return {"script": scripts[pid]}
                if pid in key_of: return {"key": key_of[pid]}
                if lenient: return {"unnamed": pid}   # only on the donor side; the diff replaces it
                raise SystemExit(f"{wid}: reference to unnamed game object {pid}")
            return ref

        news = [{"as": "folder", "from": {"key": tmpl_key}, "unless_exists": FOLDER_KEY,
                 "edits": diff(normalize(to(donor_side_inv(donor_side, "folder")), ref_core(donor_side, True)),
                               normalize(fold_tree, ref_core(locals_)))}]
        for pid, name in locals_.items():
            if name == "folder": continue
            src_pid = donor_side_inv(donor_side, name)
            a = normalize(to(src_pid), ref_core(donor_side, True))
            b = normalize(sb.objects[pid].read_typetree(), ref_core(locals_))
            news.append({"as": name, "from": source[name], "edits": diff(a, b)})
        container = [
            {"key": FOLDER_KEY, "asset": {"$local": "folder"}, "preload": {"like": tmpl_key}, "shared": True},
            {"key": wid, "asset": {"$local": "def"}, "preload": {"like": donor}},
        ]
        for c in container:
            c["asset"] = {"local": c["asset"]["$local"]}

        # --- item bundle
        bname = f"footlong.base_{wid}"
        donor_bundle = mo["AssetToBundleMap"][donor_def["_prefab"]["_assetGuid"]]
        dbf, dsf, dcab = open_bundle(ho, donor_bundle)
        mbf, msf, mcab = open_bundle(hb, bname)
        strmap = [(dcab, mcab)]
        ext_d = {i + 1: e.path for i, e in enumerate(dsf.externals)}
        ext_m = {i + 1: e.path for i, e in enumerate(msf.externals)}

        def ref_b(ext):
            def ref(fid, pid):
                return {"path": pid} if fid == 0 else {"ext": ext[fid], "path": pid}
            return ref

        donor_classes = {t.class_id for t in dsf.types}
        types = [raw_type(msf, t) for t in msf.types if t.class_id not in donor_classes]
        new_objs, edits = [], []
        for pid, o in msf.objects.items():
            if o.type.name == "AssetBundle":
                continue
            raw = bytes(o.get_raw_data())
            if pid not in dsf.objects:
                ext = []
                def walk(x):
                    if is_pptr(x) and x["m_FileID"] != 0:
                        pat = struct.pack("<iq", x["m_FileID"], x["m_PathID"]); at = raw.find(pat)
                        while at != -1:
                            ext.append({"off": at, "cab": ext_m[x["m_FileID"]]}); at = raw.find(pat, at + 1)
                    elif isinstance(x, dict): [walk(v) for v in x.values()]
                    elif isinstance(x, (list, tuple)): [walk(v) for v in x]
                walk(o.read_typetree())
                ext = [dict(t) for t in {tuple(sorted(e.items())) for e in ext}]
                new_objs.append({"path": pid, "class": o.type_id if False else o.serialized_type.class_id,
                                 "data": base64.b64encode(raw).decode(), "ext": ext})
            elif raw != bytes(dsf.objects[pid].get_raw_data()):
                a = normalize(dsf.objects[pid].read_typetree(), ref_b(ext_d), strmap)
                b = normalize(o.read_typetree(), ref_b(ext_m))
                e = diff(a, b)
                if e: edits.append({"path": pid, "edits": e})
        g = {k: cont_b and None for k in ()}
        spawner_cls = next(c for c in donor_props if c.split(".")[-1] == "ItemSpawnerDef")
        new_spawner = sb.objects[next(p for p, n in locals_.items() if n == "p_" + spawner_cls)].read_typetree()
        rename = [
            {"from": {"of": {"key": donor}, "path": ["_prefab", "_assetGuid"]}, "to": new_def["_prefab"]["_assetGuid"]},
            {"from": {"of": {"key": donor}, "path": ["_icon", "_assetGuid"]}, "to": new_def["_icon"]["_assetGuid"]},
            {"from": {"of": {"prop_of": donor, "script": spawner_cls}, "path": ["_spriteRef", "_assetGuid"]},
             "to": new_spawner["_spriteRef"]["_assetGuid"]},
        ]
        added = sorted(p for p in msf.objects if p not in dsf.objects)
        bundle = {"name": bname, "donor": {"item": donor}, "cab": mcab, "types": types, "new": new_objs,
                  "edit": edits, "rename": rename, "preload_add": {new_def["_prefab"]["_assetGuid"]: added},
                  "guids": [r["to"] for r in rename]}

        # option: show up wherever the donor shows up in loot tables / loot groups (incl. shops)
        donor_ref = f"extref://footlong.base/{donor}"
        loot_classes = sorted({loot_refs[pid] for pid in loot_refs_by_ref.get(donor_ref, [])})
        options = []
        if loot_classes:
            options.append({"id": "loot", "name": f"Also found in loot and shops (wherever the {donor_name(donor)} is)", "default": False,
                            "core": {"edit": [{"target": {"where": {"script": cls, "contains": donor_ref}},
                                               "edits": [{"path": ["loot"], "duplicate_where": {"contains": donor_ref},
                                                          "replace": [donor_ref, f"extref://footlong.base/{wid}"]}]}
                                              for cls in loot_classes]}})

        meta = {"format": FORMAT, "id": wid, "name": new_spawner["_itemName"], "description": new_spawner.get("_description", ""),
                "kind": "weapon", "version": 2,
                "core": {"new": news, "container": container}, "bundles": [bundle], "options": options}
        path = os.path.join(dest, f"{wid}.h3mod")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("mod.json", json.dumps(meta, separators=(",", ":")))
            icon = os.path.join(out_dir, f"{wid}_sprite.png")
            if os.path.exists(icon):
                z.write(icon, "icon.png")
        ne = sum(len(n["edits"]) for n in news) + sum(len(e["edits"]) for e in edits)
        print(f"  {len(news)} cloned defs, {len(new_objs)} new bundle objects, {len(edits)} edited bundle objects, {ne} field edits -> {os.path.getsize(path)//1024} KB")


def donor_name(key):
    return {"USAS12": "USAS-12", "P90_Tactical": "P90", "ShortSledge": "Short Sledge"}.get(key, key)


def donor_side_inv(side, name):
    return next(p for p, n in side.items() if n == name)


if __name__ == "__main__":
    main(*sys.argv[1:5])
