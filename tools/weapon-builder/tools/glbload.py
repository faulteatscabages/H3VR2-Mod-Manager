"""Load a GLB into flat world-space parts: (positions, normals, uvs, indices, material) per primitive.

material = dict(base=PIL.Image|None, base_factor=rgba, normal=PIL|None,
                mr=PIL|None (glTF metallicRoughness), occ=PIL|None,
                metallic=f, roughness=f, emissive=PIL|None, emissive_factor=rgb,
                alpha_mode=str, name=str)
"""
import numpy as np
import trimesh


def _img(x):
    return x if x is not None else None


def load(path):
    scene = trimesh.load(path, force="scene", process=False)
    parts = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry[gname]
        if not isinstance(g, trimesh.Trimesh) or len(g.faces) == 0:
            continue
        v = trimesh.transform_points(g.vertices, T)
        n = g.vertex_normals.copy()
        R = T[:3, :3]
        n = n @ np.linalg.inv(R).T
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        uv = None
        mat = dict(name=gname, base=None, base_factor=(1, 1, 1, 1), normal=None, mr=None, occ=None,
                   metallic=0.0, roughness=0.8, emissive=None, emissive_factor=(0, 0, 0), alpha_mode="OPAQUE")
        vis = g.visual
        if hasattr(vis, "uv") and vis.uv is not None and len(vis.uv) == len(g.vertices):
            uv = np.asarray(vis.uv, dtype=np.float64)
        m = getattr(vis, "material", None)
        if m is not None:
            mat["name"] = getattr(m, "name", None) or gname
            if isinstance(m, trimesh.visual.material.PBRMaterial):
                bc = m.baseColorFactor
                if bc is not None:
                    bc = np.asarray(bc, dtype=np.float64)
                    if bc.max() > 1.0:
                        bc = bc / 255.0
                    mat["base_factor"] = tuple(bc.tolist())
                mat["base"] = m.baseColorTexture
                mat["normal"] = m.normalTexture
                mat["mr"] = m.metallicRoughnessTexture
                mat["occ"] = m.occlusionTexture
                mat["emissive"] = m.emissiveTexture
                if m.emissiveFactor is not None:
                    mat["emissive_factor"] = tuple(np.asarray(m.emissiveFactor, dtype=float).tolist())
                mat["metallic"] = 1.0 if m.metallicFactor is None else float(m.metallicFactor)
                mat["roughness"] = 1.0 if m.roughnessFactor is None else float(m.roughnessFactor)
                mat["alpha_mode"] = m.alphaMode or "OPAQUE"
            else:
                img = getattr(m, "image", None)
                mat["base"] = img
                d = getattr(m, "diffuse", None)
                if d is not None:
                    d = np.asarray(d, dtype=float)
                    mat["base_factor"] = tuple((d / 255.0 if d.max() > 1 else d).tolist())
        elif hasattr(vis, "vertex_colors"):
            pass
        flip = np.linalg.det(R) < 0
        f = g.faces[:, ::-1] if flip else g.faces
        parts.append(dict(name=str(node), pos=v, nrm=n, uv=uv, idx=np.asarray(f, dtype=np.int64), mat=mat))
    return parts


def bounds(parts):
    allv = np.concatenate([p["pos"] for p in parts])
    return allv.min(0), allv.max(0)
