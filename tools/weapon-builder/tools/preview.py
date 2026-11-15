"""Render orthographic previews (front/side/top) of loaded parts with flat shading."""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.patches
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection


def render(parts, out, title="", marks=None, max_tris=60000, boxes=None):
    views = [("side (X right, Y up) looking -Z", 0, 1, 2), ("side (Z right, Y up) looking +X", 2, 1, 0), ("top (X right, Z up)", 0, 2, 1)]
    fig, axs = plt.subplots(1, 3, figsize=(18, 6))
    tris, cols = [], []
    for p in parts:
        f = p["idx"]
        if len(f) > max_tris:
            f = f[np.random.default_rng(0).choice(len(f), max_tris, replace=False)]
        tris.append(p["pos"][f])
        bf = np.asarray(p["mat"]["base_factor"][:3])
        cols.append(np.repeat(bf[None], len(f), 0))
    T = np.concatenate(tris); C = np.concatenate(cols)
    nrm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    for ax, (name, a, b, depth) in zip(axs, views):
        light = np.zeros(3); light[depth] = 1; light[b] = 0.5; light /= np.linalg.norm(light)
        shade = np.clip(np.abs(nrm @ light), 0.15, 1)[:, None]
        order = np.argsort(T[:, :, depth].mean(1))
        if "looking -Z" in name:
            order = order  # far (low z) first? camera at +z: draw low z first
        poly = T[order][:, :, [a, b]]
        ax.add_collection(PolyCollection(poly, facecolors=np.clip(C[order] * shade[order] * 0.85 + 0.1, 0, 1), edgecolors="none"))
        ax.autoscale(); ax.set_aspect("equal"); ax.set_title(name); ax.grid(True, alpha=.3)
        for bx in boxes or []:
            lo, hi = bx.min(0), bx.max(0)
            ax.add_patch(matplotlib.patches.Rectangle((lo[a], lo[b]), hi[a] - lo[a], hi[b] - lo[b], fill=False, ec="lime", lw=1))
        if marks:
            for lbl, pt in marks.items():
                ax.plot(pt[a], pt[b], "r+", ms=14, mew=2); ax.annotate(lbl, (pt[a], pt[b]), color="r", fontsize=7)
        ax.autoscale()
    fig.suptitle(title)
    fig.tight_layout(); fig.savefig(out, dpi=70); plt.close(fig)


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    import glbload
    parts = glbload.load(sys.argv[1])
    lo, hi = glbload.bounds(parts)
    print(sys.argv[1], "parts", len(parts), "tris", sum(len(p["idx"]) for p in parts), "verts", sum(len(p["pos"]) for p in parts))
    print("  bounds", lo.round(3), hi.round(3), "size", (hi - lo).round(3))
    for p in parts:
        m = p["mat"]
        print("   ", p["name"][:40], len(p["idx"]), "uv" if p["uv"] is not None else "nouv", m["name"], "base", None if m["base"] is None else m["base"].size, "nrm", m["normal"] is not None, "mr", m["mr"] is not None, "emis", m["emissive"] is not None, m["alpha_mode"], np.round(m["base_factor"], 2))
    render(parts, sys.argv[2], sys.argv[1].rsplit("/", 1)[-1])
