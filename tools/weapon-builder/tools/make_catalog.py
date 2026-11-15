"""Build an online catalog folder for the mod manager.

  python make_catalog.py <mods dir with .h3mod files> <out dir> [--apk H3VR2-ModManager.apk --app-version-code N --app-version-name X --notes "..."]

Upload the whole out dir anywhere that serves files over HTTPS (GitHub Pages, a GitHub repo's raw
files, a release, any web host) and put the URL of catalog.json into Catalog.DEFAULT_URL in the app.
To publish an update, bump "version" in the mod's mod.json, rebuild the catalog and upload again:
players' apps download it automatically and re-apply it.
"""
import argparse, json, os, shutil, zipfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mods"); ap.add_argument("out")
    ap.add_argument("--apk"); ap.add_argument("--app-version-code", type=int); ap.add_argument("--app-version-name"); ap.add_argument("--notes")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "mods"), exist_ok=True)
    cat = {"mods": []}
    for n in sorted(os.listdir(a.mods)):
        if not n.endswith(".h3mod"): continue
        src = os.path.join(a.mods, n)
        m = json.loads(zipfile.ZipFile(src).read("mod.json"))
        shutil.copy(src, os.path.join(a.out, "mods", n))
        cat["mods"].append({"id": m["id"], "name": m["name"], "description": m.get("description", ""), "kind": m.get("kind", "mod"),
                            "version": m.get("version", 1), "url": "mods/" + n, "size": os.path.getsize(src)})
    if a.apk:
        shutil.copy(a.apk, os.path.join(a.out, "H3VR2-ModManager.apk"))
        cat["app"] = {"versionCode": a.app_version_code, "versionName": a.app_version_name, "url": "H3VR2-ModManager.apk", "notes": a.notes}
    json.dump(cat, open(os.path.join(a.out, "catalog.json"), "w"), indent=1)
    print(f"catalog with {len(cat['mods'])} mods -> {a.out}/catalog.json")


if __name__ == "__main__":
    main()
