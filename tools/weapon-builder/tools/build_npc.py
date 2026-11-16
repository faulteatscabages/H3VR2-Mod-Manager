"""Turn a humanoid GLB model into an H3VR2 sosig NPC mod (.h3mod, format 2).

  python build_npc.py <original footlong.base.hdog> <model.glb> <out dir> [config.json]

How it works
  A sosig's body is ONE mesh bent by the game across 4 physics bones (legs, hips, torso, head at
  y = 0.3 / 0.7 / 1.1 / 1.5 m). Bone weights live in the vertex colour (R = hips, G = torso,
  B = head, rest = legs). We replace that mesh with the model, painted with weights by body part,
  so it walks, bobs, leans, ragdolls and loses limbs like any sosig. Eight variants are written:
  intact + every combination of severed joints (triangles across a cut joint are dropped).

  The body is cloned on the player's headset from a game sosig with its own prefab
  (default "Heavy Greydog"); the mod only carries our mesh/material/textures and field edits.
"""
import base64, copy, json, math, os, struct, sys, zipfile
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hdog import Hdog
import UnityPy
import glbload, modkit as mk
from export_mods import normalize, diff, raw_type, open_bundle, is_pptr

DEFAULTS = {
    "id": "Mod_Shrek",
    "name": "Shrek (enemy)",
    "display": "Shrek",
    "description": "It's all ogre now. A Shrek sosig that walks, leans, ragdolls and can be dismembered "
                   "like any sosig. Find him in the sosig spawner.",
    "version": 1,
    "height": 1.85,                       # model height in metres (a sosig is 1.8)
    # body-part boundaries as a fraction of model height: legs|hips, hips|torso, torso|head
    "cuts": [0.27, 0.49, 0.745],
    "arm_x": 0.21,                        # |x| / height beyond which a vertex is arm -> torso bone
    "head_x": 0.1,                        # |x| / height beyond which a vertex near the neck is shoulder
    "blend": 0.03,                        # weight blend half-width (m)
    "donor_profile": "SosigProfile/SProfile_Greydog_Heavy",    # whose body prefab we clone
    "base_profile": "SosigProfile/SProfile_SoSecEnforcer",     # whose AI / gear / stats we copy
    "atlas": 1024,
    "drop_materials": [],                 # model materials to leave out (e.g. a misplaced eyeball mesh)
    "credit": "Model: \"Shrek\" by burnt.melon (sketchfab.com/burnt.melon), CC-BY-4.0",
}
BONE_Y = [0.3, 0.7, 1.1, 1.5]
# SosigSkinnedMesh field -> severed joints (bit a = torso|head, b = hips|torso, c = legs|hips)
VARIANTS = {"meshIntact": "000", "meshSevered001": "001", "meshSevered010": "010", "meshSevered011": "011",
            "meshSevered100": "100", "meshSevered101": "101", "meshSevered110": "110", "meshSevered111": "111"}


# ----------------------------------------------------------------------------- model

def load_model(path, cfg):
    parts = [p for p in glbload.load(path)
             if p["mat"]["name"] not in cfg.get("drop_materials", []) and len(p["idx"]) >= cfg.get("min_tris", 3)]
    allv = np.concatenate([p["pos"] for p in parts])
    lo, hi = allv.min(0), allv.max(0)
    s = cfg["height"] / (hi[1] - lo[1])
    core = allv[np.abs(allv[:, 0] - (lo[0] + hi[0]) / 2) < 0.15 * (hi[1] - lo[1])]
    off = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(core[:, 2].min() + core[:, 2].max()) / 2])
    F = np.diag([-1.0, 1.0, 1.0])          # glTF (right-handed, +Z front) -> Unity (left-handed, +Z front)
    out = []
    for p in parts:
        pos = ((p["pos"] + off) * s) @ F
        nrm = p["nrm"] @ F
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
        uv = p["uv"] if p["uv"] is not None else np.zeros((len(pos), 2))
        out.append(dict(p, pos=pos, nrm=nrm, uv=uv, idx=p["idx"][:, ::-1].copy()))
    return out


def build_atlas(parts, size):
    """Pack every distinct base texture into one atlas (shelf packing). Returns image, remapped parts."""
    mats = []
    for p in parts:
        if not any(m is p["mat"] for m in mats):
            mats.append(p["mat"])
    imgs = []
    for m in mats:
        bf = np.asarray(m["base_factor"], float)
        if m["base"] is not None:
            a = np.asarray(m["base"].convert("RGBA")).astype(np.float32)
            a[..., :3] *= bf[:3]; a[..., 3] = 255
            imgs.append(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)))
        else:
            imgs.append(Image.new("RGBA", (16, 16), tuple(int(c * 255) for c in bf[:3]) + (255,)))
    # scale so that the total area fits comfortably, then shelf-pack
    area = sum(i.size[0] * i.size[1] for i in imgs)
    k = min(4.0, math.sqrt(0.6 * size * size / area))
    while True:
        rects, x, y, row = [], 0, 0, 0
        ok = True
        for im in imgs:
            w, h = max(8, int(im.size[0] * k)), max(8, int(im.size[1] * k))
            if x + w > size:
                x, y, row = 0, y + row, 0
            if y + h > size:
                ok = False; break
            rects.append((x, y, w, h)); x += w; row = max(row, h)
        if ok: break
        k *= 0.9
    atlas = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    for im, (x, y, w, h) in zip(imgs, rects):
        r = im.resize((w, h), Image.Resampling.LANCZOS)
        atlas.paste(r, (x, y))
        # bleed edges by 4 px against mip/ASTC seams
        for d in range(1, 5):
            atlas.paste(r.crop((0, 0, w, 1)).resize((w, 1)), (x, max(0, y - d)))
            atlas.paste(r.crop((0, h - 1, w, h)), (x, min(size - 1, y + h - 1 + d)))
            atlas.paste(r.crop((0, 0, 1, h)), (max(0, x - d), y))
            atlas.paste(r.crop((w - 1, 0, w, h)), (min(size - 1, x + w - 1 + d), y))
    out = []
    for p in parts:
        i = next(j for j, m in enumerate(mats) if m is p["mat"])
        x, y, w, h = rects[i]
        uv = np.mod(p["uv"], 1.0)            # tiling isn't possible inside an atlas
        u = (x + uv[:, 0] * w) / size
        v = 1.0 - (y + (1.0 - uv[:, 1]) * h) / size   # uv is v-up, image rows go down
        out.append(dict(p, uv=np.stack([u, v], 1)))
    return atlas, out


def merge(parts):
    P, N, U, I, off = [], [], [], [], 0
    for p in parts:
        P.append(p["pos"]); N.append(p["nrm"]); U.append(p["uv"]); I.append(p["idx"] + off); off += len(p["pos"])
    return np.concatenate(P), np.concatenate(N), np.concatenate(U), np.concatenate(I)


def bone_weights(P, cfg):
    H = cfg["height"]
    cuts = [c * H for c in cfg["cuts"]]
    y = P[:, 1].copy()
    arm = np.abs(P[:, 0]) > cfg["arm_x"] * H
    y[arm & (y < cuts[2])] = (cuts[1] + cuts[2]) / 2          # arms and hands ride on the torso
    shoulder = (np.abs(P[:, 0]) > cfg["head_x"] * H) & (y >= cuts[2]) & (y < cuts[2] + 0.1 * H)
    y[shoulder] = cuts[2] - 2 * cfg["blend"]                    # so do the shoulders beside the head
    W = np.zeros((len(P), 4))
    b = cfg["blend"]
    # piecewise: weight of bone i = step up at cut[i-1] minus step up at cut[i]
    def step(c):
        return np.clip((y - (c - b)) / (2 * b), 0, 1)
    s = [step(c) for c in cuts]
    W[:, 0] = 1 - s[0]
    W[:, 1] = s[0] - s[1]
    W[:, 2] = s[1] - s[2]
    W[:, 3] = s[2]
    return W


def variant(P, N, U, I, W, bits):
    """Drop triangles that cross a severed joint; vertices next to a cut snap to one bone."""
    severed = [bits[2] == "1", bits[1] == "1", bits[0] == "1"]     # joints 0|1, 1|2, 2|3
    dom = np.argmax(W, 1)
    W = W.copy()
    keep = np.ones(len(I), bool)
    for j, cut in enumerate(severed):
        if not cut: continue
        side = dom[I] > j
        keep &= side.all(1) | (~side).all(1)
        # no blending across the cut
        mix = (W[:, j] > 0) & (W[:, j + 1] > 0)
        lo_side = dom <= j
        W[mix & lo_side, j] += W[mix & lo_side, j + 1]; W[mix & lo_side, j + 1] = 0
        W[mix & ~lo_side, j + 1] += W[mix & ~lo_side, j]; W[mix & ~lo_side, j] = 0
    return I[keep], W


def vertex_bytes(P, N, U, W, H):
    """Sosig vertex layout (stride 48): pos f32x3, normal f16x4, tangent f16x4, colour u8x4,
    uv0 f16x2, uv1 f32x2, uv2 f16x2."""
    n = len(P)
    T = mk.compute_tangents(P, N, U, CUR_IDX)
    ang = (np.arctan2(P[:, 0], P[:, 2]) / (2 * np.pi)) % 1.0
    dv = 0.05 + 0.5 * P[:, 1] * (1.8 / H)
    buf = np.zeros((n, 48), np.uint8)
    buf[:, 0:12] = P.astype("<f4").view(np.uint8).reshape(n, 12)
    buf[:, 12:20] = np.concatenate([N, np.zeros((n, 1))], 1).astype("<f2").view(np.uint8).reshape(n, 8)
    buf[:, 20:28] = T.astype("<f2").view(np.uint8).reshape(n, 8)
    col = np.clip(np.round(W[:, 1:4] * 255), 0, 255)
    buf[:, 28:32] = np.concatenate([col, np.full((n, 1), 255)], 1).astype(np.uint8)
    buf[:, 32:36] = U.astype("<f2").view(np.uint8).reshape(n, 4)
    buf[:, 36:44] = np.stack([ang, dv], 1).astype("<f4").view(np.uint8).reshape(n, 8)
    buf[:, 44:48] = np.stack([ang, dv], 1).astype("<f2").view(np.uint8).reshape(n, 4)
    return buf.tobytes()


CUR_IDX = None


def mesh_tree(tmpl, name, P, N, U, I, W, H):
    global CUR_IDX
    CUR_IDX = I
    t = copy.deepcopy(tmpl)
    t["m_Name"] = name
    # only keep vertices the triangles use (cut variants drop some)
    used = np.unique(I)
    remap = np.full(len(P), -1); remap[used] = np.arange(len(used))
    P, N, U, W, I = P[used], N[used], U[used], W[used], remap[I]
    CUR_IDX = I
    vb = vertex_bytes(P, N, U, W, H)
    ib = I.astype("<u2").reshape(-1).tobytes()
    lo, hi = P.min(0), P.max(0)
    aabb = {"m_Center": mk.v3((lo + hi) / 2), "m_Extent": mk.v3((hi - lo) / 2)}
    sm = copy.deepcopy(t["m_SubMeshes"][0])
    sm.update(firstByte=0, indexCount=int(I.size), topology=0, baseVertex=0, firstVertex=0,
              vertexCount=len(P), localAABB=aabb)
    t["m_SubMeshes"] = [sm]
    t["m_IndexFormat"] = 0
    t["m_IndexBuffer"] = list(ib)
    t["m_VertexData"]["m_VertexCount"] = len(P)
    t["m_VertexData"]["m_DataSize"] = vb
    t["m_LocalAABB"] = aabb
    t["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
    t["m_MeshLodInfo"]["m_NumLevels"] = 1
    t["m_MeshLodInfo"]["m_SubMeshes"] = [{"m_Levels": [{"m_IndexStart": 0, "m_IndexCount": 0}]}]
    assert len(P) < 65536
    return t


# ----------------------------------------------------------------------------- build

def main(orig, glb, out_dir, cfg_path=None):
    cfg = dict(DEFAULTS)
    if cfg_path:
        cfg.update(json.load(open(cfg_path)))
    mid = cfg["id"]; H = cfg["height"]
    os.makedirs(out_dir, exist_ok=True)
    h = Hdog(orig)
    man = h.manifest()
    a2b, deps = man["AssetToBundleMap"], man["BundleDependencyMap"]

    core_env = UnityPy.load(h.read("footlong.base"))
    _, core_sf = mk.bundle_parts(core_env)
    core_ab = next(o for o in core_sf.objects.values() if o.type.name == "AssetBundle").read_typetree()
    keys = {k: v["asset"]["m_PathID"] for k, v in core_ab["m_Container"]}
    donor_prof = core_sf.objects[keys[cfg["donor_profile"]]].read_typetree()
    donor_guid = donor_prof["customPrefab"]["_assetGuid"]
    donor_bundle = a2b[donor_guid]
    print("donor body:", donor_prof["customPrefab"]["_subAssetName"], "in", donor_bundle)

    # ---- geometry
    parts = load_model(glb, cfg)
    atlas, parts = build_atlas(parts, cfg["atlas"])
    atlas.save(os.path.join(out_dir, f"{mid}_atlas.png"))
    P, N, U, I = merge(parts)
    W = bone_weights(P, cfg)
    print(f"model: {len(P)} verts, {len(I)} tris, bounds {P.min(0).round(3)} {P.max(0).round(3)}")
    preview_weights(P, I, W, os.path.join(out_dir, f"{mid}_weights.png"))

    # ---- body bundle
    from build_mod import Prefab
    pf = Prefab(h.read(donor_bundle))
    bf, sf = pf.bf, pf.sf
    old_cab = next(n for n in bf.files if not n.endswith(".resS"))
    bname = f"footlong.base_{mid}"
    new_cab = mk.cab(bname)
    bf.files = {k.replace(old_cab, new_cab): v for k, v in bf.files.items()}
    for pid in list(sf.objects):
        o = sf.objects[pid]
        if o.type.name in ("Texture2D", "Mesh"):
            t = pf.tree(pid)
            if t.get("m_StreamData", {}).get("path"):
                t["m_StreamData"]["path"] = t["m_StreamData"]["path"].replace(old_cab, new_cab)
    pidgen = mk.PidGen(mid, sf.objects.keys())

    scripts = {o.path_id: o.read().m_ClassName for o in core_sf.objects.values() if o.type.name == "MonoScript"}
    def cls(pid):
        return scripts.get(pf.tree(pid)["m_Script"]["m_PathID"])
    skinned = next(p for p in pf.of_type("MonoBehaviour") if cls(p) == "SosigSkinnedMesh")
    skinner = next(p for p in pf.of_type("MonoBehaviour") if cls(p) == "SosigSkinner")
    body_go = pf.go_of(skinner)
    mf = pf.comps(body_go, "MeshFilter")[0]; mr = pf.comps(body_go, "MeshRenderer")[0]
    tmpl_mesh_pid = pf.tree(skinned)["meshIntact"]["m_PathID"]
    tmpl_mesh = (sf.objects[tmpl_mesh_pid], pf.tree(tmpl_mesh_pid))

    added = []
    mesh_pids = {}
    for field, bits in VARIANTS.items():
        Iv, Wv = variant(P, N, U, I, W, bits)
        mt = mesh_tree(tmpl_mesh[1], f"{mid}_{bits}", P, N, U, Iv, Wv, H)
        mp = pidgen()
        mk.add_object(sf, tmpl_mesh[0], tmpl_mesh[0].type_id, mp, mt)
        mesh_pids[field] = mp; added.append(mp)
        pf.tree(skinned)[field] = mk.pptr(mp)
    pf.tree(skinned)["m_Name"] = mid
    pf.tree(mf)["m_Mesh"] = mk.pptr(mesh_pids["meshIntact"])

    # material: a copy of the donor's body material (sosig shader) with our textures
    mat_ref = pf.tree(mr)["m_Materials"][0]
    mat_cab = sf.externals[mat_ref["m_FileID"] - 1].path.split("/")[-1]
    mat_bundle = next(n for n in deps[donor_bundle] if mat_cab.encode() in h.read(n)[:600])
    menv = UnityPy.load(h.read(mat_bundle)); _, msf = mk.bundle_parts(menv)
    mobj = msf.objects[mat_ref["m_PathID"]]; mtree = mobj.read_typetree()
    tenv = UnityPy.load(h.read("footlong.base_LancasterPistol")); _, tsf = mk.bundle_parts(tenv)
    ttex = next(o for o in tsf.objects.values() if o.type.name == "Texture2D")
    ti_tex = mk.ensure_type(sf, tsf, 28)
    ti_mat = mk.ensure_type(sf, msf, 21)

    def relink(x):
        if is_pptr(x) and x["m_FileID"] != 0:
            return mk.pptr(x["m_PathID"], mk.ensure_external(sf, msf, x["m_FileID"]))
        if isinstance(x, dict): return {k: relink(v) for k, v in x.items()}
        if isinstance(x, list): return [relink(v) for v in x]
        if isinstance(x, tuple): return tuple(relink(v) for v in x)
        return x
    mtree = relink(mtree)
    tex = {}
    flat_n = mk.pack_normal(Image.new("RGB", (8, 8), (128, 128, 255)))
    orm = Image.new("RGBA", (8, 8), (255, int(0.85 * 255), 0, 255))
    for slot, img, lin in (("_BaseMap", atlas, False), ("_BumpMap", flat_n, True), ("_PbrMap", orm, True)):
        tp = pidgen()
        mk.add_object(sf, ttex, ti_tex, tp, mk.texture_tree(ttex.read_typetree(), f"{mid}{slot}", img, lin))
        tex[slot] = tp; added.append(tp)
    env_ = dict(mtree["m_SavedProperties"]["m_TexEnvs"])
    for slot, tp in tex.items():
        env_[slot]["m_Texture"] = mk.pptr(tp)
    mtree["m_SavedProperties"]["m_TexEnvs"] = list(env_.items())
    mtree["m_Name"] = mid
    matp = pidgen()
    mk.add_object(sf, mobj, ti_mat, matp, mtree)
    added.append(matp)
    pf.tree(mr)["m_Materials"] = [mk.pptr(matp)]

    # no nanite growths (infected look); rename the root
    for p in pf.of_type("MonoBehaviour"):
        if cls(p) == "SosigNaniteGrowths":
            pf.tree(p)["m_Enabled"] = 0
    root = pf.root_go()
    pf.tree(root)["m_Name"] = cfg["display"]

    # asset bundle index
    ab_pid = pf.of_type("AssetBundle")[0]; ab = pf.tree(ab_pid)
    new_guid = mk.guid(mid, "prefab")
    entry = next(v for k, v in ab["m_Container"] if k == donor_guid)
    start, size = entry["preloadIndex"], entry["preloadSize"]
    ab["m_PreloadTable"][start + size:start + size] = [mk.pptr(p) for p in added]
    for k, v in ab["m_Container"]:
        if v is entry: v["preloadSize"] += len(added)
        elif v["preloadIndex"] >= start + size: v["preloadIndex"] += len(added)
    ab["m_Container"] = sorted([(new_guid if k == donor_guid else k, v) for k, v in ab["m_Container"]], key=lambda kv: kv[0].encode())
    ab["m_Name"] = ab["m_AssetBundleName"] = bname
    pf.commit(); sf.mark_changed()
    built = bf.save(packer="original")
    open(os.path.join(out_dir, bname + ".bundle"), "wb").write(built)

    # ---- describe the bundle as edits against the donor (nothing from the game is shipped)
    import UnityPy as U2
    benv = U2.load(built); _, msf2 = mk.bundle_parts(benv)
    _, dsf, dcab = open_bundle(h, donor_bundle)
    ext_d = {i + 1: e.path for i, e in enumerate(dsf.externals)}
    ext_m = {i + 1: e.path for i, e in enumerate(msf2.externals)}
    def ref_b(ext):
        return lambda fid, pid: {"path": pid} if fid == 0 else {"ext": ext[fid], "path": pid}
    donor_classes = {t.class_id for t in dsf.types}
    types = [raw_type(msf2, t) for t in msf2.types if t.class_id not in donor_classes]
    new_objs, edits = [], []
    for pid, o in msf2.objects.items():
        if o.type.name == "AssetBundle": continue
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
            new_objs.append({"path": pid, "class": o.serialized_type.class_id,
                             "data": base64.b64encode(raw).decode(), "ext": ext})
        elif raw != bytes(dsf.objects[pid].get_raw_data()):
            a = normalize(dsf.objects[pid].read_typetree(), ref_b(ext_d), [(dcab, new_cab)])
            b = normalize(o.read_typetree(), ref_b(ext_m))
            e = diff(a, b)
            if e: edits.append({"path": pid, "edits": e})
    bundle = {"name": bname, "donor": {"key": cfg["donor_profile"], "path": ["customPrefab", "_assetGuid"]},
              "cab": new_cab, "types": types, "new": new_objs, "edit": edits,
              "rename": [{"from": {"of": {"key": cfg["donor_profile"]}, "path": ["customPrefab", "_assetGuid"]}, "to": new_guid}],
              "preload_add": {new_guid: sorted(added)}, "guids": [new_guid]}

    # ---- definitions: a sosig profile that uses the new body
    E = "extref://footlong.base/"
    prof_name = f"SProfile_{mid}"
    base_key = cfg["base_profile"]
    news = [{"as": "profile", "from": {"key": base_key}, "edits": [
        {"path": ["m_Name"], "set": prof_name},
        {"path": ["RefId", "_refId"], "set": f"{E}SosigProfile/{prof_name}"},
        {"path": ["displayName"], "set": cfg["display"]},
        {"path": ["useCustomPrefab"], "set": 1},
        {"path": ["customPrefab", "_assetGuid"], "set": new_guid},
        {"path": ["customPrefab", "_subAssetName"], "set": cfg["display"]},
        {"path": ["customPrefab", "_subAssetType"], "set": donor_prof["customPrefab"]["_subAssetType"]},
        {"path": ["outfit", "_refId"], "set": ""},          # clothes would cover him
        {"path": ["showInSosigSpawnGun"], "set": 1},
    ]}]
    container = [{"key": f"SosigProfile/{prof_name}", "asset": {"local": "profile"}, "preload": {"like": base_key}}]
    boss = "SosigStatsProfile/SS_Boss_Warehouse"
    options = [
        {"id": "tough", "name": "Ogre-sized toughness (boss stats)", "default": True,
         "core": {"new": [{"as": "stats", "from": {"key": boss}, "edits": [
             {"path": ["m_Name"], "set": f"SS_{mid}"},
             {"path": ["RefId", "_refId"], "set": f"{E}SosigStatsProfile/SS_{mid}"},
             {"path": ["_damageResistance"], "set": 0.5}]}],
                  "container": [{"key": f"SosigStatsProfile/SS_{mid}", "asset": {"local": "stats"}, "preload": {"like": boss}}],
                  "edit": [{"target": {"local": "profile"}, "edits": [
                      {"path": ["stats", "_refId"], "set": f"{E}SosigStatsProfile/SS_{mid}"}]}]}},
        {"id": "patrols", "name": "Can show up in SoSec Enforcer patrols (1 in 5)", "default": False,
         "core": {"edit": [{"target": {"where": {"script": "EnemyEncounter", "contains": f"{E}SosigProfile/SProfile_SoSecEnforcer"}},
                            "edits": [{"path": ["enemies"], "duplicate_where": {"contains": f"{E}SosigProfile/SProfile_SoSecEnforcer"},
                                       "replace": [f"{E}SosigProfile/SProfile_SoSecEnforcer", f"{E}SosigProfile/{prof_name}"],
                                       "with": {"probability": 0.2}}]}]}},
    ]
    meta = {"format": 2, "id": mid, "name": cfg["name"], "description": cfg["description"] + "\n" + cfg["credit"],
            "kind": "npc", "version": cfg["version"], "min_app": 4,
            "core": {"new": news, "container": container}, "options": options, "bundles": [bundle]}
    icon = render_icon(parts, os.path.join(out_dir, f"{mid}_icon.png"))
    path = os.path.join(out_dir, f"{mid}.h3mod")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mod.json", json.dumps(meta, separators=(",", ":")))
        z.write(icon, "icon.png")
    print(f"bundle: {len(new_objs)} new objects, {len(edits)} edited, {len(types)} new types")
    print("wrote", path, os.path.getsize(path) // 1024, "KB")


# ----------------------------------------------------------------------------- previews

def preview_weights(P, I, W, out):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    cols = np.array([[0.2, 0.4, 1.0], [0.2, 0.8, 0.3], [1.0, 0.8, 0.1], [0.9, 0.2, 0.2]])
    vc = W @ cols
    fig, axs = plt.subplots(1, 2, figsize=(10, 6))
    for ax, (a, b), title in ((axs[0], (0, 1), "front"), (axs[1], (2, 1), "side")):
        depth = P[I].mean(1)[:, 2 if a == 0 else 0]
        order = np.argsort(depth if a == 0 else -depth)
        polys = P[I][order][:, :, [a, b]]
        ax.add_collection(PolyCollection(polys, facecolors=vc[I].mean(1)[order], edgecolors="k", linewidths=0.1))
        for y in BONE_Y: ax.axhline(y, ls=":", c="gray")
        ax.set_aspect("equal"); ax.autoscale(); ax.set_title(title)
    fig.suptitle("bone weights: blue legs, green hips, yellow torso+arms, red head")
    fig.savefig(out, dpi=90); plt.close(fig)


def render_icon(parts, out, size=256):
    """Flat-shaded textured front view for the mod list."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    P, N, U, I = merge(parts)
    tex = np.asarray(Image.open(out.replace("_icon.png", "_atlas.png")).convert("RGB")).astype(float) / 255
    th, tw = tex.shape[:2]
    uvc = U[I].mean(1)
    c = tex[np.clip(((1 - uvc[:, 1]) * th).astype(int), 0, th - 1), np.clip((uvc[:, 0] * tw).astype(int), 0, tw - 1)]
    fn = np.cross(P[I[:, 1]] - P[I[:, 0]], P[I[:, 2]] - P[I[:, 0]])
    fn /= np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12
    shade = 0.45 + 0.55 * np.clip(fn @ np.array([0.3, 0.5, 0.8]) / np.linalg.norm([0.3, 0.5, 0.8]), 0, 1)
    front = (fn[:, 2] > -0.2)
    order = np.argsort(P[I].mean(1)[:, 2])
    order = order[front[order]]
    fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor((0.13, 0.15, 0.18))
    fig.patch.set_facecolor((0.13, 0.15, 0.18))
    ax.add_collection(PolyCollection(P[I][order][:, :, [0, 1]] * [-1, 1], facecolors=np.clip(c[order] * shade[order, None], 0, 1), edgecolors="none"))
    lo, hi = P.min(0), P.max(0); pad = 0.06 * (hi[1] - lo[1])
    half = max(hi[0] - lo[0], hi[1] - lo[1]) / 2 + pad
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    ax.set_xlim(-cx - half, -cx + half); ax.set_ylim(cy - half, cy + half); ax.axis("off")
    fig.savefig(out, dpi=100, facecolor=fig.get_facecolor()); plt.close(fig)
    return out


if __name__ == "__main__":
    main(*sys.argv[1:5])
