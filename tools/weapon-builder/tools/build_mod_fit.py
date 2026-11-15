"""Fitting helpers: adapt a donor prefab's gameplay points & colliders to a new model.

V is the model's vertex cloud in donor root space.
"""
import numpy as np
import modkit as mk


def _colliders(pf):
    out = []
    for kind in ("BoxCollider", "CapsuleCollider", "SphereCollider", "MeshCollider"):
        for pid in pf.of_type(kind):
            out.append((kind, pid))
    return out


def _is_trigger(pf, pid):
    return bool(pf.tree(pid).get("m_IsTrigger"))


def _under(pf, comp_pid, names):
    tr = pf.transform_of(pf.go_of(comp_pid))
    while tr:
        if pf.tree(pf.go_of(tr))["m_Name"] in names:
            return True
        tr = pf.tree(tr)["m_Father"]["m_PathID"]
    return False


def _disable_go_colliders(pf, go_name):
    try:
        go = pf.go_by_name(go_name)
    except KeyError:
        return
    for kind in ("BoxCollider", "CapsuleCollider", "SphereCollider"):
        for c in pf.comps(go, kind):
            pf.tree(c)["m_Enabled"] = False


def surface_points(V):
    return V


def fit_firearm(pf, V, xf, scripts, muzzle, moves=None, hide_mounts=(), nboxes=5,
                keep_solid_under=("_ChargingHandle", "_Interactable"), muzzle_model=None):
    from build_mod import slab_boxes, set_box
    zmax = V[:, 2].max()
    if muzzle_model is not None:
        mpt = xf(muzzle_model)
    else:
        front = V[V[:, 2] > zmax - 0.03]
        mpt = np.array([np.median(front[:, 0]), np.median(front[:, 1]), zmax + 0.005])
    for n in muzzle:
        pf.set_local_pos(n, mpt)
    for n, model_pt in (moves or {}).items():
        pf.set_local_pos(n, xf(model_pt))
    for n in hide_mounts:
        _disable_go_colliders(pf, n)
    # solid colliders -> fit the model in slabs
    boxes, others = [], []
    for kind, pid in _colliders(pf):
        if _is_trigger(pf, pid) or _under(pf, pid, keep_solid_under):
            continue
        (boxes if kind == "BoxCollider" else others).append(pid)
    slabs = slab_boxes(V, min(nboxes, len(boxes)))
    for i, b in enumerate(boxes):
        if i < len(slabs):
            set_box(pf, b, *slabs[i])
        else:
            pf.tree(b)["m_Enabled"] = False
    for o in others:
        pf.tree(o)["m_Enabled"] = False


def fit_sword(pf, V, xf, scripts, blade_start=None, blade_end=None, blade_zone_from=None, grabs=None):
    """grabs: optional dict go_name -> donor-space point (overrides automatic hilt placement)."""
    from build_mod import set_scaled_cube
    zmin, zmax = V[:, 2].min(), V[:, 2].max()
    if blade_start is None:
        blade_start = blade_zone_from
    if blade_end is None:
        blade_end = zmax
    L = blade_end - blade_start
    blade_V = V[(V[:, 2] >= blade_start) & (V[:, 2] <= blade_end)]
    hilt_V = V[V[:, 2] < blade_start]
    blo, bhi = blade_V.min(0), blade_V.max(0)
    hlo, hhi = hilt_V.min(0), hilt_V.max(0)
    blade_mb = None
    for mb in pf.of_type("MonoBehaviour"):
        if pf.mb_class(mb, scripts) == "MeleeBlade":
            blade_mb = mb
    bt = pf.tree(blade_mb)
    bt["length"] = float(L)
    blade_go = pf.go_of(blade_mb)
    pf.set_local_pos(pf.tree(blade_go)["m_Name"], np.array([(blo[0] + bhi[0]) / 2, (blo[1] + bhi[1]) / 2, blade_start]))
    blade_col = bt["colliders"][0]["m_PathID"]
    thick = max(0.008, bhi[0] - blo[0]); width = max(0.02, min(bhi[1] - blo[1], 0.2))
    set_scaled_cube(pf, blade_col, ((blo + bhi) / 2)[:2].tolist() + [blade_start + L / 2], (thick, width, L))
    # other cubes: first = hilt, the rest disabled
    used = False
    for pid in pf.of_type("BoxCollider"):
        if pid == blade_col or _is_trigger(pf, pid):
            continue
        if not used:
            set_scaled_cube(pf, pid, (hlo + hhi) / 2, np.maximum(hhi - hlo, 0.02)); used = True
        else:
            pf.tree(pid)["m_Enabled"] = False
    # grab points along the hilt centreline
    cy, cx = (hlo[1] + hhi[1]) / 2, (hlo[0] + hhi[0]) / 2
    hilt_len = hhi[2] - hlo[2]
    for go_name, frac in (("grabPt", 0.72), ("grabPt (1)", 0.30), ("grabvol", 0.5)):
        pt = np.array([cx, cy, hlo[2] + hilt_len * frac])
        if grabs and go_name in grabs:
            pt = np.asarray(grabs[go_name], float)
        try:
            pf.set_local_pos(go_name, pt)
        except KeyError:
            pass
    vol = [mb for mb in pf.of_type("MonoBehaviour") if pf.mb_class(mb, scripts) == "Volume"]
    for mb in vol:
        t = pf.tree(mb)
        t["shapeHeight"] = float(max(0.15, hilt_len))


def fit_blunt(pf, V, xf, scripts, head_from):
    from build_mod import set_scaled_cube, slab_boxes
    blunt = next(mb for mb in pf.of_type("MonoBehaviour") if pf.mb_class(mb, scripts) == "MeleeBlunt")
    cols = [c["m_PathID"] for c in pf.tree(blunt)["colliders"]]
    zmax = V[:, 2].max()
    slabs = slab_boxes(V, 3, head_from, zmax, pad=0.0)
    for i, c in enumerate(cols):
        if i < len(slabs):
            set_scaled_cube(pf, c, *slabs[i])
        else:
            pf.tree(c)["m_Enabled"] = False
    # handle capsule -> legs
    legs = V[V[:, 2] < head_from]
    lo, hi = legs.min(0), legs.max(0)
    for cap in pf.of_type("CapsuleCollider"):
        tr = pf.transform_of(pf.go_of(cap))
        t = pf.tree(tr)
        t["m_LocalPosition"] = mk.v3((lo + hi) / 2)
        t["m_LocalRotation"] = dict(mk.IDENT_Q)
        t["m_LocalScale"] = mk.v3((1, 1, 1))
        c = pf.tree(cap)
        c["m_Center"] = mk.v3((0, 0, 0))
        c["m_Direction"] = 2
        c["m_Radius"] = float(max(0.02, min(hi[0] - lo[0], hi[1] - lo[1]) / 2))
        c["m_Height"] = float(hi[2] - lo[2])


def saber_blade(length, radius, color, segs=24, rings=24):
    """Extra part: a glowing capsule blade starting at the hilt's front, along +Z."""
    def make(parts, xf, s):
        V = np.concatenate([p["pos"] for p in parts])
        zf = V[:, 2].max()
        front = V[V[:, 2] > zf - 0.01]
        cx, cy = np.median(front[:, 0]), np.median(front[:, 1])
        z0 = zf - 0.005
        pos, nrm, uv = [], [], []
        ang = np.linspace(0, 2 * np.pi, segs + 1)
        zs = np.linspace(0, 1, rings + 1)
        for zi, t in enumerate(zs):
            # taper the last 4% into a rounded tip
            tip = max(0.0, (t - 0.96) / 0.04)
            r = radius * np.sqrt(max(0.0, 1 - tip * tip))
            for a in ang:
                pos.append((cx + r * np.cos(a), cy + r * np.sin(a), z0 + t * length))
                nrm.append((np.cos(a), np.sin(a), tip))
                uv.append((a / (2 * np.pi), t))
        pos = np.array(pos); nrm = np.array(nrm); nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
        idx = []
        W = segs + 1
        for zi in range(rings):
            for i in range(segs):
                a, b, c, d = zi * W + i, zi * W + i + 1, (zi + 1) * W + i, (zi + 1) * W + i + 1
                idx += [(a, c, b), (b, c, d)]
        # cap at tip
        tip_i = len(pos)
        pos = np.vstack([pos, (cx, cy, z0 + length)]); nrm = np.vstack([nrm, (0, 0, 1)]); uv = np.vstack([uv, (0.5, 1)])
        last = rings * W
        for i in range(segs):
            idx.append((last + i, tip_i, last + i + 1))
        idx = np.array(idx)
        # winding: Unity front face <=> cross(b-a, c-a) points outward (same as our converted GLB parts)
        T = pos[idx[0]]
        if np.dot(np.cross(T[1] - T[0], T[2] - T[0]), nrm[idx[0][0]]) < 0:
            idx = idx[:, ::-1]
        mat = dict(name="saber_blade", base=None, base_factor=(0.85, 0.93, 1.0, 1.0), normal=None, mr=None, occ=None,
                   metallic=0.0, roughness=0.2, emissive=None, emissive_factor=tuple(color), alpha_mode="OPAQUE")
        return [dict(name="saber_blade", pos=pos, nrm=nrm, uv=np.asarray(uv, float), idx=idx, mat=mat)]
    return make
