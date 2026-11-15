"""Build the H3VR2 custom-weapons mod.

Usage: build_mod.py <original footlong.base.hdog> <models dir> <out dir>
Produces:
  out/footlong.base.hdog      patched pack (for testing / direct install)
  out/mod/...                 the distributable mod payload (bundles + def patch json)
"""
import sys, os, json, copy, math
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hdog import Hdog
import UnityPy
import glbload, modkit as mk
from weapons import WEAPONS, MOD_FOLDER

UnityPy.config.FALLBACK_UNITY_VERSION = "6000.3.3f1"


# ============================================================================ model preparation

def load_model(w, models_dir):
    path = os.path.join(models_dir, w["model"])
    if not os.path.exists(path):
        path = os.path.join(models_dir, "work", "models", w["model"])
    parts = glbload.load(path)
    keep = w.get("keep")
    if keep:
        parts = [p for p in parts if keep(p)]
    if w.get("tweak"):
        seen = set()
        for p in parts:
            if id(p["mat"]) not in seen:
                seen.add(id(p["mat"])); w["tweak"](p["mat"])
    fwd = np.array(w["forward"], float); up = np.array(w["up"], float)
    right = np.cross(fwd, up)
    M = np.stack([right, up, fwd])            # glTF -> donor (det -1: handedness flip)
    assert abs(np.linalg.det(M) + 1) < 1e-6
    allv = np.concatenate([p["pos"] for p in parts]) @ M.T
    length = allv[:, 2].max() - allv[:, 2].min()
    s = w["length"] / length
    anchor = np.asarray(w["grip_model"], float) @ M.T * s
    offset = np.asarray(w["grip_target"], float) - anchor
    out = []
    for p in parts:
        pos = p["pos"] @ M.T * s + offset
        nrm = p["nrm"] @ M.T
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
        idx = p["idx"][:, ::-1].copy()        # winding flip for handedness change
        uv = p["uv"] if p["uv"] is not None else np.zeros((len(pos), 2))
        out.append(dict(p, pos=pos, nrm=nrm, idx=idx, uv=uv))
    xf = lambda q: np.asarray(q, float) @ M.T * s + offset
    for extra in w.get("extras", []):
        out.extend(extra(out, xf, s))
    return out, xf, s


def mat_key(m):
    return (m["name"], id(m["base"]), id(m["normal"]), id(m["mr"]))


def group_by_material(parts, max_tex):
    groups = {}
    for p in parts:
        groups.setdefault(mat_key(p["mat"]), []).append(p)
    out = []
    for k, ps in groups.items():
        off = 0; P, N, U, I = [], [], [], []
        for p in ps:
            P.append(p["pos"]); N.append(p["nrm"]); U.append(p["uv"]); I.append(p["idx"] + off); off += len(p["pos"])
        out.append(dict(mat=ps[0]["mat"], pos=np.concatenate(P), nrm=np.concatenate(N), uv=np.concatenate(U), idx=np.concatenate(I)))
    return out


def solid(rgba, size=4):
    return Image.new("RGBA", (size, size), tuple(int(round(c * 255)) for c in rgba))


def fit(img, max_tex):
    img = img.convert("RGBA")
    w, h = img.size
    sc = min(1.0, max_tex / max(w, h))
    if sc < 1:
        img = img.resize((max(4, int(w * sc)), max(4, int(h * sc))), Image.Resampling.LANCZOS)
    return img


def bake_material_images(m, max_tex):
    """Return dict base, normal(packed), orm, emission(optional), plus scalar settings."""
    bf = np.asarray(m["base_factor"], float)
    if m["base"] is not None:
        base = fit(m["base"], max_tex)
        a = np.asarray(base).astype(np.float32)
        a[..., :3] *= bf[:3]
        a[..., 3] = 255
        base = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
    else:
        base = solid((bf[0], bf[1], bf[2], 1))
    if m["normal"] is not None:
        normal = mk.pack_normal(fit(m["normal"], max_tex))
    else:
        normal = mk.pack_normal(Image.new("RGB", (4, 4), (128, 128, 255)))
    # ORM: R occlusion, G roughness, B metallic
    if m["mr"] is not None:
        mr = np.asarray(fit(m["mr"], max_tex).convert("RGB")).astype(np.float32)
        h, w = mr.shape[:2]
        if m["occ"] is not None:
            occ = np.asarray(m["occ"].convert("RGB").resize((w, h)))[..., 0].astype(np.float32)
        else:
            occ = np.full((h, w), 255.0)
        orm = np.stack([occ, mr[..., 1] * m["roughness"], mr[..., 2] * m["metallic"], np.full((h, w), 255.0)], -1)
        orm = Image.fromarray(np.clip(orm, 0, 255).astype(np.uint8), "RGBA")
    else:
        orm = solid((1, min(1, m["roughness"]), min(1, m["metallic"]), 1))
    emis = None
    ef = np.asarray(m["emissive_factor"], float)
    if m["emissive"] is not None and ef.max() > 0:
        emis = fit(m["emissive"], min(max_tex, 512))
    elif ef.max() > 0:
        emis = solid((1, 1, 1, 1))
    return dict(base=base, normal=normal, orm=orm, emission=emis, emission_color=ef)


# ============================================================================ icon rendering

def sample_colors(sm):
    """Per-triangle colour from base texture at triangle UV centroid."""
    m = sm["mat"]; bf = np.asarray(m["base_factor"][:3], float)
    idx = sm["idx"]
    if m["base"] is not None and sm["uv"] is not None:
        img = np.asarray(m["base"].convert("RGB").resize((256, 256))).astype(float) / 255
        uvc = sm["uv"][idx].mean(1) % 1.0
        px = np.clip((uvc[:, 0] * 255).astype(int), 0, 255)
        py = np.clip(((1 - uvc[:, 1]) * 255).astype(int), 0, 255)
        c = img[py, px] * bf
    else:
        c = np.repeat(bf[None], len(idx), 0)
    ef = np.asarray(m["emissive_factor"], float)
    if ef.max() > 0 and m["emissive"] is None:
        c = np.clip(c * 0.35 + ef / max(ef.max(), 1e-6) * 0.75, 0, 1)
    return c


def render_icon(submeshes, size, bg=None, pad=0.06):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    W, H = size
    T, C = [], []
    for sm in submeshes:
        T.append(sm["pos"][sm["idx"]]); C.append(sample_colors(sm))
    T = np.concatenate(T); C = np.concatenate(C)
    # view from the weapon's right side (+X): horizontal = +Z, vertical = +Y; camera looks along -X
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    light = np.array([0.6, 0.6, 0.3]); light /= np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.abs(n @ light)
    order = np.argsort(T[:, :, 0].mean(1))      # draw far (-X) first
    P = T[order][:, :, [2, 1]]
    col = np.clip(C[order] * shade[order, None], 0, 1)
    lo = P.reshape(-1, 2).min(0); hi = P.reshape(-1, 2).max(0)
    span = hi - lo; c = (lo + hi) / 2
    scale = min(W * (1 - 2 * pad) / span[0], H * (1 - 2 * pad) / span[1])
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
    ax.set_xlim(c[0] - W / 2 / scale, c[0] + W / 2 / scale)
    ax.set_ylim(c[1] - H / 2 / scale, c[1] + H / 2 / scale)
    ax.add_collection(PolyCollection(P, facecolors=col, edgecolors=col, linewidths=0.15, antialiased=True))
    if bg is None:
        fig.patch.set_alpha(0); ax.patch.set_alpha(0)
    else:
        fig.patch.set_facecolor(bg); ax.patch.set_facecolor(bg)
    buf = __import__("io").BytesIO()
    fig.savefig(buf, format="png", transparent=bg is None, dpi=100)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGBA").resize((W, H))


# ============================================================================ prefab bundle editing

class Prefab:
    def __init__(self, data):
        self.env = UnityPy.load(data)
        self.bf, self.sf = mk.bundle_parts(self.env)
        self.objs = self.sf.objects
        self.trees = {}

    def tree(self, pid):
        if pid not in self.trees:
            self.trees[pid] = self.objs[pid].read_typetree()
        return self.trees[pid]

    def commit(self):
        for pid, t in self.trees.items():
            self.objs[pid].save_typetree(t)
        self.trees = {}

    def of_type(self, name):
        return [pid for pid, o in self.objs.items() if o.type.name == name]

    def go_by_name(self, name):
        for pid in self.of_type("GameObject"):
            if self.tree(pid)["m_Name"] == name:
                return pid
        raise KeyError(name)

    def comps(self, go_pid, type_name=None):
        out = []
        for c in self.tree(go_pid)["m_Component"]:
            cp = c["component"]["m_PathID"]
            if type_name is None or self.objs[cp].type.name == type_name:
                out.append(cp)
        return out

    def transform_of(self, go_pid):
        return self.comps(go_pid, "Transform")[0]

    def go_of(self, comp_pid):
        return self.tree(comp_pid)["m_GameObject"]["m_PathID"]

    def name_of(self, comp_pid):
        return self.tree(self.go_of(comp_pid))["m_Name"]

    def world(self, tr_pid):
        t = self.tree(tr_pid)
        M = mk.local_matrix(t)
        par = t["m_Father"]["m_PathID"]
        return (self.world(par) @ M) if par else M

    def root_go(self):
        for pid in self.of_type("Transform"):
            if self.tree(pid)["m_Father"]["m_PathID"] == 0:
                return self.go_of(pid)

    def set_local_pos(self, go_name, p):
        tr = self.transform_of(self.go_by_name(go_name))
        par = self.tree(tr)["m_Father"]["m_PathID"]
        Pm = np.linalg.inv(self.world(par)) if par else np.eye(4)
        lp = Pm @ np.append(p, 1)
        self.tree(tr)["m_LocalPosition"] = mk.v3(lp[:3])

    def mb_class(self, pid, scripts):
        return scripts.get(self.tree(pid)["m_Script"]["m_PathID"])


def slab_boxes(V, n, zlo=None, zhi=None, pad=0.003):
    if zlo is not None:
        V = V[(V[:, 2] >= zlo) & (V[:, 2] <= zhi)]
    z0, z1 = V[:, 2].min(), V[:, 2].max()
    edges = np.linspace(z0, z1, n + 1)
    out = []
    for i in range(n):
        sel = V[(V[:, 2] >= edges[i] - 1e-6) & (V[:, 2] <= edges[i + 1] + 1e-6)]
        if len(sel) < 3:
            continue
        lo, hi = sel.min(0) - pad, sel.max(0) + pad
        lo[2], hi[2] = edges[i], edges[i + 1]
        out.append(((lo + hi) / 2, np.maximum(hi - lo, 0.01)))
    return out


def set_box(pf, col_pid, center, size, reset_transform=True):
    t = pf.tree(col_pid)
    go = pf.go_of(col_pid)
    tr = pf.transform_of(go)
    W = pf.world(tr)
    if reset_transform:
        par = pf.tree(tr)["m_Father"]["m_PathID"]
        Pm = pf.world(par) if par else np.eye(4)
        # put transform at parent origin w/o rotation/scale relative to root (parents are identity in our donors)
        pf.tree(tr)["m_LocalPosition"] = mk.v3(np.linalg.inv(Pm)[:3, 3] if par else np.zeros(3))
        pf.tree(tr)["m_LocalRotation"] = dict(mk.IDENT_Q)
        pf.tree(tr)["m_LocalScale"] = mk.v3((1, 1, 1))
        W = pf.world(tr)
    Winv = np.linalg.inv(W)
    t["m_Center"] = mk.v3((Winv @ np.append(center, 1))[:3])
    sc = np.linalg.norm(W[:3, :3], axis=0)
    t["m_Size"] = mk.v3(np.asarray(size) / sc)
    t["m_Enabled"] = True


def set_scaled_cube(pf, col_pid, center, size):
    """Colliders that are unit boxes on a scaled transform (melee donors)."""
    go = pf.go_of(col_pid); tr = pf.transform_of(go)
    t = pf.tree(tr)
    par = t["m_Father"]["m_PathID"]
    Pinv = np.linalg.inv(pf.world(par)) if par else np.eye(4)
    t["m_LocalPosition"] = mk.v3((Pinv @ np.append(center, 1))[:3])
    t["m_LocalRotation"] = dict(mk.IDENT_Q)
    t["m_LocalScale"] = mk.v3(size)
    c = pf.tree(col_pid)
    c["m_Center"] = mk.v3((0, 0, 0)); c["m_Size"] = mk.v3((1, 1, 1)); c["m_Enabled"] = True


def debug_preview(pf, parts, out, title):
    import preview
    marks = {}
    for pid in pf.of_type("GameObject"):
        n = pf.tree(pid)["m_Name"]
        if n.startswith("_") or "grab" in n.lower() or n in ("blade",):
            if any(k in n.lower() for k in ("grab", "muzzle", "magwell", "blade", "chamber")) and "Trigger" not in n:
                marks[n] = pf.world(pf.transform_of(pid))[:3, 3]
    boxes = []
    for b in pf.of_type("BoxCollider"):
        t = pf.tree(b)
        if not t["m_Enabled"] or t["m_IsTrigger"]:
            continue
        W = pf.world(pf.transform_of(pf.go_of(b)))
        c = np.array([t["m_Center"][k] for k in "xyz"]); sz = np.array([t["m_Size"][k] for k in "xyz"])
        corners = np.array([[i, j, k] for i in (-.5, .5) for j in (-.5, .5) for k in (-.5, .5)]) * sz + c
        boxes.append((W[:3, :3] @ corners.T).T + W[:3, 3])
    preview.render(parts, out, title, marks=marks, boxes=boxes)


# ============================================================================ main build

def main(src_pack, models_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    h = Hdog(src_pack)
    manifest = h.manifest()
    a2b = manifest["AssetToBundleMap"]; deps = manifest["BundleDependencyMap"]

    base_env = UnityPy.load(h.read("footlong.base"))
    base_bf, base_sf = mk.bundle_parts(base_env)
    scripts = {o.path_id: o.read().m_ClassName for o in base_sf.objects.values() if o.type.name == "MonoScript"}
    base_ab_pid = next(pid for pid, o in base_sf.objects.items() if o.type.name == "AssetBundle")
    base_ab = base_sf.objects[base_ab_pid].read_typetree()
    defs_by_name = {}
    for pid, o in base_sf.objects.items():
        if o.type.name == "MonoBehaviour":
            n = o.peek_name()
            if n:
                defs_by_name.setdefault(n, []).append(pid)

    def find_def(name, cls):
        for pid in defs_by_name.get(name, []):
            t = base_sf.objects[pid].read_typetree()
            if scripts.get(t["m_Script"]["m_PathID"]) == cls:
                return pid, t
        raise KeyError(name)

    # Template objects for mesh / material / texture come from the Lancaster pistol bundle
    tmpl_env = UnityPy.load(h.read("footlong.base_LancasterPistol"))
    _, tmpl_sf = mk.bundle_parts(tmpl_env)
    T = {}
    for pid, o in tmpl_sf.objects.items():
        tn = o.type.name
        if tn == "Mesh" and o.read_typetree()["m_Name"] == "Frame":
            T["Mesh"] = (o, o.read_typetree())
        elif tn == "Material":
            T["Material"] = (o, o.read_typetree())
        elif tn == "Texture2D" and o.read_typetree()["m_Name"].endswith("_B"):
            T["Texture2D"] = (o, o.read_typetree())

    new_container = []
    new_preload = []
    report = []
    pidgen_base = mk.PidGen("base", base_sf.objects.keys())

    # ---- "Modded" spawner folder
    root_folder_ref = "extref://footlong.base/ItemSpawnerFolder/Root"
    fold_tmpl_pid = None
    for pid in base_sf.objects:
        o = base_sf.objects[pid]
        if o.type.name != "MonoBehaviour":
            continue
        t = o.read_typetree()
        if scripts.get(t["m_Script"]["m_PathID"]) == "ItemSpawnerFolder" and t["_parent"]["_refId"] == root_folder_ref:
            fold_tmpl_pid = pid; fold_tmpl = t; break
    folder_ref = f"extref://footlong.base/ItemSpawnerFolder/{MOD_FOLDER}"
    ft = copy.deepcopy(fold_tmpl)
    ft["m_Name"] = MOD_FOLDER
    ft["RefId"]["_refId"] = folder_ref
    ft["_name"] = MOD_FOLDER
    ft["_parent"]["_refId"] = root_folder_ref
    fpid = pidgen_base()
    mk.add_object(base_sf, base_sf.objects[fold_tmpl_pid], base_sf.objects[fold_tmpl_pid].type_id, fpid, ft)
    folder_preload = [p for p in base_ab["m_PreloadTable"][0:0]]
    # find the template folder's preload range to copy its script deps
    for k, v in base_ab["m_Container"]:
        if v["asset"]["m_PathID"] == fold_tmpl_pid:
            rng = base_ab["m_PreloadTable"][v["preloadIndex"]:v["preloadIndex"] + v["preloadSize"]]
            folder_preload = [p if p["m_PathID"] != fold_tmpl_pid else mk.pptr(fpid) for p in rng]
    new_container.append((f"ItemSpawnerFolder/{MOD_FOLDER}", fpid, folder_preload))

    for w in WEAPONS:
        wid = w["id"]
        bundle_name = f"footlong.base_{wid}"
        print(f"\n===== {wid}  (donor {w['donor']})")
        donor_pid, donor_def = find_def(w["donor"], "ItemDef")
        donor_bundle = a2b[donor_def["_prefab"]["_assetGuid"]]

        # ---------------- model
        parts, xf, s = load_model(w, models_dir)
        sms = group_by_material(parts, w.get("max_tex", 1024))
        V = np.concatenate([p["pos"] for p in parts])
        lo, hi = V.min(0), V.max(0)
        print(f"  model scale {s:.4f}  bounds {lo.round(3)} {hi.round(3)}  tris {sum(len(x['idx']) for x in sms)}  materials {len(sms)}")

        # ---------------- prefab bundle
        pf = Prefab(h.read(donor_bundle))
        bf, sf = pf.bf, pf.sf
        old_cab = sf.name if hasattr(sf, "name") else None
        old_names = list(bf.files.keys())
        old_cab = next(n for n in old_names if not n.endswith(".resS"))
        new_cab = mk.cab(bundle_name)
        bf.files = {k.replace(old_cab, new_cab): v for k, v in bf.files.items()}
        for f in bf.files.values():
            if hasattr(f, "name"):
                try:
                    f.name = f.name.replace(old_cab, new_cab)
                except Exception:
                    pass
        pidgen = mk.PidGen(wid, sf.objects.keys())

        # fix any stream paths that point at the old CAB (textures/meshes kept from donor)
        for pid, o in list(sf.objects.items()):
            if o.type.name in ("Texture2D", "Mesh"):
                t = pf.tree(pid)
                sd = t.get("m_StreamData")
                if sd and sd["path"]:
                    sd["path"] = sd["path"].replace(old_cab, new_cab)

        ti_mesh = mk.ensure_type(sf, tmpl_sf, 43)
        ti_mat = mk.ensure_type(sf, tmpl_sf, 21)
        ti_tex = mk.ensure_type(sf, tmpl_sf, 28)
        shader_fid = mk.ensure_external(sf, tmpl_sf, T["Material"][1]["m_Shader"]["m_FileID"])

        added = []
        mat_pids = []
        for i, sm in enumerate(sms):
            imgs = bake_material_images(sm["mat"], w.get("max_tex", 1024))
            tex_pids = {}
            for slot, img, lin in (("base", imgs["base"], False), ("normal", imgs["normal"], True), ("orm", imgs["orm"], True), ("emission", imgs["emission"], False)):
                if img is None:
                    continue
                tp = pidgen()
                mk.add_object(sf, T["Texture2D"][0], ti_tex, tp, mk.texture_tree(T["Texture2D"][1], f"{wid}_{i}_{slot}", img, lin))
                tex_pids[slot] = tp; added.append(tp)
            mt = copy.deepcopy(T["Material"][1])
            mt["m_Name"] = f"{wid}_{i}"
            mt["m_Shader"] = mk.pptr(T["Material"][1]["m_Shader"]["m_PathID"], shader_fid)
            texenv = dict(mt["m_SavedProperties"]["m_TexEnvs"])
            texenv["_BaseMap"]["m_Texture"] = mk.pptr(tex_pids["base"])
            texenv["_BumpMap"]["m_Texture"] = mk.pptr(tex_pids["normal"])
            texenv["_PbrMap"]["m_Texture"] = mk.pptr(tex_pids["orm"])
            if "emission" in tex_pids:
                texenv["_EmissionMap"]["m_Texture"] = mk.pptr(tex_pids["emission"])
                kws = list(mt.get("m_ValidKeywords", []))
                if "_EMISSION" not in kws:
                    kws.append("_EMISSION")
                mt["m_ValidKeywords"] = kws
                mt["m_LightmapFlags"] = 2  # realtime emissive
                ec = imgs["emission_color"] * w.get("emission_boost", 1.0)
                cols = dict(mt["m_SavedProperties"]["m_Colors"])
                cols["_EmissionColor"] = {"r": float(ec[0]), "g": float(ec[1]), "b": float(ec[2]), "a": 1.0}
                mt["m_SavedProperties"]["m_Colors"] = list(cols.items())
                fl = dict(mt["m_SavedProperties"]["m_Floats"])
                fl["_EMISSION"] = 1.0; fl["_EmissionIntensity"] = 1.0
                mt["m_SavedProperties"]["m_Floats"] = list(fl.items())
            fl = dict(mt["m_SavedProperties"]["m_Floats"])
            fl["_Cull"] = 0.0 if w.get("two_sided") else 2.0
            mt["m_SavedProperties"]["m_Floats"] = list(fl.items())
            mt["m_SavedProperties"]["m_TexEnvs"] = list(texenv.items())
            mp = pidgen()
            mk.add_object(sf, T["Material"][0], ti_mat, mp, mt)
            mat_pids.append(mp); added.append(mp)

        # host renderer: mesh vertices must be expressed in the host transform's space
        if w.get("host"):
            cands = [g for g in pf.of_type("GameObject") if pf.tree(g)["m_Name"] == w["host"] and pf.comps(g, "MeshFilter")]
            host_go = cands[0]
        else:
            host_go = pf.root_go()
        host_W = pf.world(pf.transform_of(host_go))
        inv = np.linalg.inv(host_W)
        msms = []
        for sm in sms:
            P = (inv[:3, :3] @ sm["pos"].T).T + inv[:3, 3]
            Nn = (np.linalg.inv(host_W[:3, :3]).T @ sm["nrm"].T).T
            Nn /= np.linalg.norm(Nn, axis=1, keepdims=True) + 1e-12
            msms.append(dict(pos=P, nrm=Nn, uv=sm["uv"], idx=sm["idx"]))
        mesh_t, _ = mk.mesh_tree(T["Mesh"][1], wid, msms)
        mesh_pid = pidgen()
        mk.add_object(sf, T["Mesh"][0], ti_mesh, mesh_pid, mesh_t)
        added.append(mesh_pid)

        # hide every donor renderer, then attach ours
        for rp in pf.of_type("MeshRenderer") + pf.of_type("SkinnedMeshRenderer"):
            pf.tree(rp)["m_Enabled"] = False
        mfs = pf.comps(host_go, "MeshFilter")
        mrs = pf.comps(host_go, "MeshRenderer")
        assert mfs and mrs, "host has no renderer"
        pf.tree(mfs[0])["m_Mesh"] = mk.pptr(mesh_pid)
        r = pf.tree(mrs[0])
        r["m_Enabled"] = True
        r["m_Materials"] = [mk.pptr(m) for m in mat_pids]
        r["m_StaticBatchInfo"] = {"firstSubMesh": 0, "subMeshCount": 0}

        # rename root, retarget item def reference
        root = pf.root_go()
        pf.tree(root)["m_Name"] = wid
        for mb in pf.of_type("MonoBehaviour"):
            cls = pf.mb_class(mb, scripts)
            if cls == "SerializableObjectRoot":
                pf.tree(mb)["_itemDef"]["_refId"] = f"extref://footlong.base/{wid}"

        # weapon-specific fitting (muzzle, blades, grips, colliders)
        w["fit"](pf, V, xf, scripts, s)
        debug_preview(pf, parts, os.path.join(out_dir, f"{wid}_fit.png"), wid)

        # icon + sprite: re-render into donor's icon/sprite textures (same dims)
        ab_pid = pf.of_type("AssetBundle")[0]
        ab = pf.tree(ab_pid)
        sprite_tex = icon_tex = sprite_pid = None
        for k, v in ab["m_Container"]:
            o = sf.objects.get(v["asset"]["m_PathID"])
            if o is None:
                continue
            if o.type.name == "Sprite":
                sprite_pid = o.path_id
        if sprite_pid:
            sprite_tex = pf.tree(sprite_pid)["m_RD"]["texture"]["m_PathID"]
        for k, v in ab["m_Container"]:
            o = sf.objects.get(v["asset"]["m_PathID"])
            if o is not None and o.type.name == "Texture2D" and o.path_id != sprite_tex:
                icon_tex = o.path_id
        icon_parts = [dict(sm, pos=sm["pos"]) for sm in sms]
        for tex_pid, kind in ((sprite_tex, "sprite"), (icon_tex, "icon")):
            if not tex_pid:
                continue
            tt = pf.tree(tex_pid)
            W_, H_ = tt["m_Width"], tt["m_Height"]
            img = render_icon(icon_parts, (W_, H_), bg=None)
            img.save(os.path.join(out_dir, f"{wid}_{kind}.png"))
            fmt = tt["m_TextureFormat"]
            new = mk.texture_tree(tt, wid, img, linear=(tt["m_ColorSpace"] == 0), fmt=fmt if fmt in (mk.ASTC6, mk.RGBA32) else mk.RGBA32,
                                  mips=tt["m_MipCount"] > 1)
            pf.trees[tex_pid] = new
        if sprite_pid:
            pf.tree(sprite_pid)["m_Name"] = wid

        # container: new guids
        g_prefab, g_icon, g_sprite = mk.guid(wid, "prefab"), mk.guid(wid, "icon"), mk.guid(wid, "sprite")
        donor_icon_guid = donor_def["_icon"]["_assetGuid"]
        donor_spawner = None
        for p in donor_def["_propertiesList"]:
            t = base_sf.objects[p["m_PathID"]].read_typetree()
            if scripts.get(t["m_Script"]["m_PathID"]) == "ItemSpawnerDef":
                donor_spawner = t
        donor_sprite_guid = donor_spawner["_spriteRef"]["_assetGuid"]
        gmap = {donor_def["_prefab"]["_assetGuid"]: g_prefab, donor_icon_guid: g_icon, donor_sprite_guid: g_sprite}
        cont = []
        for k, v in ab["m_Container"]:
            cont.append((gmap.get(k, k), v))
        # register new objects in the prefab's preload range
        prefab_entry = next(v for k, v in cont if k == g_prefab)
        start, size = prefab_entry["preloadIndex"], prefab_entry["preloadSize"]
        ins = [mk.pptr(p) for p in added]
        ab["m_PreloadTable"][start + size:start + size] = ins
        for k, v in cont:
            if v is prefab_entry:
                v["preloadSize"] += len(ins)
            elif v["preloadIndex"] >= start + size:
                v["preloadIndex"] += len(ins)
        cont.sort(key=lambda kv: kv[0].encode())
        ab["m_Container"] = cont
        ab["m_Name"] = bundle_name
        ab["m_AssetBundleName"] = bundle_name
        pf.commit()
        sf.mark_changed()
        bundle_bytes = bf.save(packer="original")
        h.set(bundle_name, "UABR", bundle_bytes)
        a2b[g_prefab] = a2b[g_icon] = a2b[g_sprite] = bundle_name
        deps[bundle_name] = list(deps.get(donor_bundle, []))
        print(f"  bundle {bundle_name}: {len(bundle_bytes)/1e6:.2f} MB, added {len(added)} objects")

        # ---------------- definitions in base bundle
        new_props = []
        pid_map = {}
        for p in donor_def["_propertiesList"]:
            o = base_sf.objects[p["m_PathID"]]
            t = o.read_typetree()
            cls = scripts.get(t["m_Script"]["m_PathID"])
            if cls in w.get("drop_props", ("ItemLootDef", "ItemWorkOrderMetadataDef")):
                continue
            t = copy.deepcopy(t)
            if cls == "ItemSpawnerDef":
                t["_itemName"] = w["name"]
                t["_description"] = w.get("description", "")
                t["_isHidden"] = 0
                t["_spriteRef"]["_assetGuid"] = g_sprite
                t["_spriteRef"]["_subAssetName"] = wid
                t["_folders"] = [{"_refId": folder_ref}] + [{"_refId": f"extref://footlong.base/ItemSpawnerFolder/{f}"} for f in w.get("folders", [])]
                t["_relatedItems"] = []
            for key, val in w.get("prop_overrides", {}).get(cls, {}).items():
                t[key] = val
            np_ = pidgen_base()
            mk.add_object(base_sf, o, o.type_id, np_, t)
            pid_map[p["m_PathID"]] = np_
            new_props.append(mk.pptr(np_))
        d = copy.deepcopy(donor_def)
        d["m_Name"] = wid
        d["RefId"]["_refId"] = f"extref://footlong.base/{wid}"
        d["_prefab"]["_assetGuid"] = g_prefab
        d["_prefab"]["_subAssetName"] = wid
        d["_icon"]["_assetGuid"] = g_icon
        d["_icon"]["_subAssetName"] = wid
        d["_massGrams"] = float(w.get("mass_g", d["_massGrams"]))
        d["_bounds"] = {"m_Center": mk.v3((lo + hi) / 2), "m_Extent": mk.v3((hi - lo) / 2)}
        d["_propertiesList"] = new_props
        dpid = pidgen_base()
        mk.add_object(base_sf, base_sf.objects[donor_pid], base_sf.objects[donor_pid].type_id, dpid, d)
        pid_map[donor_pid] = dpid
        # preload: mirror donor's (scripts + subdefs + def)
        for k, v in base_ab["m_Container"]:
            if v["asset"]["m_PathID"] == donor_pid:
                rng = base_ab["m_PreloadTable"][v["preloadIndex"]:v["preloadIndex"] + v["preloadSize"]]
                pre = []
                for pp in rng:
                    if pp["m_FileID"] == 0 and pp["m_PathID"] in pid_map:
                        pre.append(mk.pptr(pid_map[pp["m_PathID"]]))
                    elif pp["m_FileID"] == 0 and base_sf.objects[pp["m_PathID"]].type.name == "MonoScript":
                        pre.append(pp)
                    elif pp["m_FileID"] != 0:
                        pre.append(pp)
                break
        new_container.append((wid, dpid, pre))
        report.append(dict(id=wid, name=w["name"], donor=w["donor"], bundle=bundle_name, scale=s,
                           bounds=[lo.tolist(), hi.tolist()]))

    # ---- write base container
    for key, pid, pre in new_container:
        idx = len(base_ab["m_PreloadTable"])
        base_ab["m_PreloadTable"].extend(pre)
        base_ab["m_Container"].append((key, {"preloadIndex": idx, "preloadSize": len(pre), "asset": mk.pptr(pid)}))
    base_ab["m_Container"].sort(key=lambda kv: kv[0].encode())
    base_sf.objects[base_ab_pid].save_typetree(base_ab)
    base_sf.mark_changed()
    h.set("footlong.base", "UABP", base_bf.save(packer="original"))
    h.set_manifest(manifest)
    out_pack = os.path.join(out_dir, "footlong.base.hdog")
    h.write(out_pack)
    json.dump(report, open(os.path.join(out_dir, "report.json"), "w"), indent=1)
    print("\nwrote", out_pack)


if __name__ == "__main__":
    main(*sys.argv[1:4])
