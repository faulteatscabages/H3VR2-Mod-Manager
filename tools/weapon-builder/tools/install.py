"""H3VR2 Custom Weapons — installer / uninstaller for Quest (via adb).

  python install.py              install (or re-install after a game update)
  python install.py --uninstall  restore the original game content
  python install.py --build-only build the patched pack locally, don't touch the headset

The script never ships or uploads game files: it pulls *your* footlong.base.hdog from
the headset, keeps an untouched backup on this computer, patches a copy, and pushes it back.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

PKG = "com.rustltd.h3vr2"
REMOTE = f"/sdcard/Android/obb/{PKG}/footlong.base.hdog"
CACHE = os.path.join(ROOT, "cache")
ORIG = os.path.join(CACHE, "footlong.base.original.hdog")
OUT = os.path.join(CACHE, "build")


def adb(*args, check=True, capture=True):
    exe = shutil.which("adb") or "adb"
    r = subprocess.run([exe, *args], capture_output=capture, text=True)
    if check and r.returncode != 0:
        sys.exit(f"adb {' '.join(args)} failed:\n{r.stderr or r.stdout}")
    return (r.stdout or "").strip()


def remote_size():
    out = adb("shell", f"stat -c %s {REMOTE}", check=False)
    return int(out) if out.isdigit() else None


def is_modded(path):
    from hdog import Hdog
    from weapons import WEAPONS
    h = Hdog(path)
    names = {e.name for e in h.entries}
    return any(f"footlong.base_{w['id']}" in names for w in WEAPONS)


def ensure_device():
    if not shutil.which("adb"):
        sys.exit("adb not found. Install Android platform-tools (or SideQuest) and make sure 'adb' is on your PATH.")
    devs = [l for l in adb("devices").splitlines()[1:] if l.strip().endswith("device")]
    if not devs:
        sys.exit("No headset found. Plug in the Quest, enable developer mode, and accept the USB debugging prompt in the headset.")
    if PKG not in adb("shell", "pm list packages"):
        sys.exit("Hot Dogs, Horseshoes & Hand Grenades 2 is not installed on this headset.")


def pull_original():
    os.makedirs(CACHE, exist_ok=True)
    size = remote_size()
    if size is None:
        sys.exit(f"Could not find {REMOTE}. Launch the game once so it finishes downloading its content.")
    tmp = os.path.join(CACHE, "pulled.hdog")
    print(f"Pulling game content from headset ({size/1e9:.2f} GB)…")
    adb("pull", REMOTE, tmp, capture=False)
    if is_modded(tmp):
        os.remove(tmp)
        if not os.path.exists(ORIG):
            sys.exit("The headset already has a modded pack and no original backup exists here. "
                     "Reinstall the game (or verify files) to get a clean copy, then run this again.")
        print("Headset already has the mod; rebuilding from the saved original backup.")
        return
    os.replace(tmp, ORIG)
    print("Saved original backup:", ORIG)


def build():
    import build_mod
    os.makedirs(OUT, exist_ok=True)
    build_mod.main(ORIG, os.path.join(ROOT, "models"), OUT)
    return os.path.join(OUT, "footlong.base.hdog")


def push(path):
    print("Stopping game and pushing patched content (about a minute)…")
    adb("shell", "am", "force-stop", PKG)
    adb("push", path, REMOTE, capture=False)
    # A pushed file is owned by adb's shell user; the game opens the pack read/write,
    # so without this it fails with "Access ... is denied" and hangs on the logo.
    adb("shell", "chmod", "666", REMOTE)
    if remote_size() != os.path.getsize(path):
        sys.exit("Push size mismatch — please run again.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--build-only", action="store_true")
    a = ap.parse_args()
    if a.uninstall:
        ensure_device()
        if not os.path.exists(ORIG):
            sys.exit("No original backup found in ./cache — reinstall the game from the Meta store to restore it.")
        push(ORIG)
        print("Original game content restored.")
        return
    if not a.build_only:
        ensure_device()
        pull_original()
    elif not os.path.exists(ORIG):
        sys.exit(f"Put an original footlong.base.hdog at {ORIG} first.")
    patched = build()
    if a.build_only:
        print("Built:", patched)
        return
    push(patched)
    print("\nDone! Start the game and open the item spawner → 'Modded' folder.")
    print("After any game update, run this installer again.")


if __name__ == "__main__":
    main()
