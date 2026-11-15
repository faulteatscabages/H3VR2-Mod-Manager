"""Building blocks for adding new items to an H3VR2 .hdog pack.

All geometry handed to this module is already in the donor prefab's root space
(Unity, left-handed, +Z forward, +Y up, metres).
"""
import copy, hashlib, io, random
import numpy as np
from PIL import Image
import UnityPy
from UnityPy.export import Texture2DConverter as TC

ASTC6 = 50   # TextureFormat.ASTC_6x6 (what the game uses)
RGBA32 = 4

# ----------------------------------------------------------------------------- ids


def guid(*parts):
    return hashlib.md5(("h3vr2mod:" + ":".join(parts)).encode()).hexdigest()


def cab(name):
    return "CAB-" + hashlib.md5(("h3vr2mod-cab:" + name).encode()).hexdigest()


class PidGen:
    def __init__(self, seed, used):
        self.rng = random.Random(seed)
        self.used = set(used)

    def __call__(self):
        while True:
            v = self.rng.randrange(-(2**63) + 1, 2**63 - 1)
            if v and v not in self.used:
                self.used.add(v)
                return v

# ----------------------------------------------------------------------------- serialized-file surgery


def bundle_parts(env):
    bf = next(iter(env.files.values()))
    sf = next(f for f in bf.files.values() if hasattr(f, "objects"))
    return bf, sf


def ensure_type(dst_sf, src_sf, class_id):
    for i, t in enumerate(dst_sf.types):
        if t.class_id == class_id and class_id != 114:
            return i
    src = next(t for t in src_sf.types if t.class_id == class_id)
    dst_sf.types.append(copy.copy(src))
    return len(dst_sf.types) - 1


def ensure_external(dst_sf, src_sf, src_file_id):
    """Make sure dst has the external that src refers to with src_file_id; return dst file id."""
    ext = src_sf.externals[src_file_id - 1]
    for i, e in enumerate(dst_sf.externals):
        if e.path.lower() == ext.path.lower():
            return i + 1
    dst_sf.externals.append(copy.copy(ext))
    return len(dst_sf.externals)


def add_object(dst_sf, template_obj, type_index, pid, tree):
    o = copy.copy(template_obj)
    o.assets_file = dst_sf
    o.path_id = pid
    o.type_id = type_index
    o.serialized_type = dst_sf.types[type_index]
    dst_sf.objects[pid] = o
    o.save_typetree(tree)
    dst_sf.mark_changed()
    return o


def pptr(pid, fid=0):
    return {"m_FileID": fid, "m_PathID": pid}

# ----------------------------------------------------------------------------- textures


def astc_size(w, h):
    return ((w + 5) // 6) * ((h + 5) // 6) * 16


def encode_texture(img, fmt=ASTC6, mips=True):
    """Return (bytes, mipcount) with a full mip chain down to 1x1 (Unity layout)."""
    img = img.convert("RGBA")
    w, h = img.size
    data = b""
    n = 0
    while True:
        lvl = img if n == 0 else img.resize((w, h), Image.Resampling.LANCZOS)
        enc, _ = TC.image_to_texture2d(lvl, fmt)
        if fmt == ASTC6:
            assert len(enc) == astc_size(w, h), (len(enc), w, h)
        data += enc
        n += 1
        if not mips or (w == 1 and h == 1):
            break
        w, h = max(1, w // 2), max(1, h // 2)
    return data, n


def texture_tree(template_tree, name, img, linear, fmt=ASTC6, mips=True):
    t = copy.deepcopy(template_tree)
    data, n = encode_texture(img, fmt, mips)
    t["m_Name"] = name
    t["m_Width"], t["m_Height"] = img.size
    t["m_CompleteImageSize"] = len(data)
    t["m_TextureFormat"] = fmt
    t["m_MipCount"] = n
    t["m_ColorSpace"] = 0 if linear else 1
    t["m_IsReadable"] = False
    t["image data"] = data
    t["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
    return t


def pack_normal(img):
    """glTF (OpenGL, RGB) normal map -> Unity mobile XY encoding: RGB=y, A=x."""
    a = np.asarray(img.convert("RGB"))
    x, y = a[..., 0], a[..., 1]
    out = np.stack([y, y, y, x], -1)
    return Image.fromarray(out, "RGBA")

# ----------------------------------------------------------------------------- meshes


def compute_tangents(pos, nrm, uv, idx):
    n = len(pos)
    tan = np.zeros((n, 3)); bit = np.zeros((n, 3))
    v0, v1, v2 = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
    w0, w1, w2 = uv[idx[:, 0]], uv[idx[:, 1]], uv[idx[:, 2]]
    e1, e2 = v1 - v0, v2 - v0
    d1, d2 = w1 - w0, w2 - w0
    r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(r) < 1e-12, 1e-12, r)
    sdir = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / r[:, None]
    tdir = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) / r[:, None]
    for k in range(3):
        np.add.at(tan, idx[:, k], sdir)
        np.add.at(bit, idx[:, k], tdir)
    t = tan - nrm * np.sum(nrm * tan, 1, keepdims=True)
    ln = np.linalg.norm(t, axis=1, keepdims=True)
    fallback = np.cross(nrm, np.array([0.0, 1.0, 0.0]))
    fallback[np.linalg.norm(fallback, axis=1) < 1e-6] = [1, 0, 0]
    t = np.where(ln > 1e-9, t / np.maximum(ln, 1e-12), fallback / np.linalg.norm(fallback, axis=1, keepdims=True))
    # Unity: binormal = cross(normal, tangent) * w
    w = np.where(np.sum(np.cross(nrm, t) * bit, 1) < 0, -1.0, 1.0)
    return np.concatenate([t, w[:, None]], 1)


def mesh_tree(template_tree, name, submeshes):
    """submeshes: list of dict(pos, nrm, uv, idx) in final space. Returns typetree dict."""
    t = copy.deepcopy(template_tree)
    allpos, allnrm, alltan, alluv, sm_out, ib = [], [], [], [], [], []
    vbase = 0
    for sm in submeshes:
        pos = sm["pos"].astype(np.float32); nrm = sm["nrm"].astype(np.float32)
        uv = sm["uv"].astype(np.float32); idx = sm["idx"].astype(np.int64)
        tan = compute_tangents(pos.astype(np.float64), nrm.astype(np.float64), uv.astype(np.float64), idx).astype(np.float32)
        lo, hi = pos.min(0), pos.max(0)
        sm_out.append(dict(first_index=sum(len(i) for i in ib), count=idx.size, first_vertex=vbase,
                           vcount=len(pos), center=(lo + hi) / 2, extent=(hi - lo) / 2))
        ib.append((idx + vbase).reshape(-1))
        allpos.append(pos); allnrm.append(nrm); alltan.append(tan); alluv.append(uv)
        vbase += len(pos)
    P = np.concatenate(allpos); N = np.concatenate(allnrm); T = np.concatenate(alltan); U = np.concatenate(alluv)
    I = np.concatenate(ib)
    use32 = vbase > 65535
    ibytes = I.astype(np.uint32 if use32 else np.uint16).tobytes()
    stride = 48
    vb = np.zeros((vbase, 12), np.float32)
    vb[:, 0:3] = P; vb[:, 3:6] = N; vb[:, 6:10] = T; vb[:, 10:12] = U
    ch = [{"stream": 0, "offset": 0, "format": 0, "dimension": 0} for _ in range(14)]
    ch[0] = {"stream": 0, "offset": 0, "format": 0, "dimension": 3}
    ch[1] = {"stream": 0, "offset": 12, "format": 0, "dimension": 3}
    ch[2] = {"stream": 0, "offset": 24, "format": 0, "dimension": 4}
    ch[4] = {"stream": 0, "offset": 40, "format": 0, "dimension": 2}
    esz = 4 if use32 else 2
    t["m_Name"] = name
    t["m_SubMeshes"] = [{
        "firstByte": s["first_index"] * esz, "indexCount": s["count"], "topology": 0, "baseVertex": 0,
        "firstVertex": s["first_vertex"], "vertexCount": s["vcount"],
        "localAABB": {"m_Center": dict(zip("xyz", map(float, s["center"]))), "m_Extent": dict(zip("xyz", map(float, s["extent"])))},
    } for s in sm_out]
    t["m_IndexFormat"] = 1 if use32 else 0
    t["m_IndexBuffer"] = list(ibytes)
    t["m_VertexData"]["m_VertexCount"] = vbase
    t["m_VertexData"]["m_Channels"] = ch
    t["m_VertexData"]["m_DataSize"] = vb.tobytes()
    lo, hi = P.min(0), P.max(0)
    t["m_LocalAABB"] = {"m_Center": dict(zip("xyz", map(float, (lo + hi) / 2))), "m_Extent": dict(zip("xyz", map(float, (hi - lo) / 2)))}
    t["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
    t["m_IsReadable"] = False
    t["m_KeepVertices"] = False
    t["m_KeepIndices"] = False
    t["m_MeshCompression"] = 0
    t["m_BakedConvexCollisionMesh"] = []
    t["m_BakedTriangleCollisionMesh"] = []
    t["m_MeshLodInfo"]["m_NumLevels"] = 1
    t["m_MeshLodInfo"]["m_SubMeshes"] = [{"m_Levels": [{"m_IndexStart": 0, "m_IndexCount": 0}]} for _ in sm_out]
    assert stride == 48
    return t, (lo, hi)

# ----------------------------------------------------------------------------- transforms


def quat_to_mat(q):
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def local_matrix(tr):
    M = np.eye(4)
    S = np.diag([tr["m_LocalScale"][k] for k in "xyz"])
    M[:3, :3] = quat_to_mat(tr["m_LocalRotation"]) @ S
    M[:3, 3] = [tr["m_LocalPosition"][k] for k in "xyz"]
    return M


def v3(p):
    return {"x": float(p[0]), "y": float(p[1]), "z": float(p[2])}


IDENT_Q = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
