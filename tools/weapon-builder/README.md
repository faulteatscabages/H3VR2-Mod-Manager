# H3VR2 Custom Weapons (Quest)

Adds five new items to *Hot Dogs, Horseshoes & Hand Grenades 2* on Meta Quest:

| Item | Type | Works like |
|---|---|---|
| Portal Gun | SMG | P90 Tactical (uses P90 magazines) |
| Gravity Gun | auto shotgun | USAS-12 (uses USAS-12 magazines) |
| Lightsaber | sword | Kabartana (cuts, stabs, can be thrown) |
| Monado | big sword | Kabartana |
| Tung Tung Tung Sahur | blunt club (hold him by the legs) | Short Sledgehammer |

They appear in the item spawner under a new **Modded** folder, and also in their normal category
(e.g. *Firearms → Rifle → Submachine Gun*).

## Install

You need:
- A Quest with **developer mode** on and the game installed and launched at least once.
- A USB cable, and **adb** (Android platform-tools; SideQuest includes it).
- **Python 3.10+**.

Then:
1. Plug in the headset and accept the "Allow USB debugging" prompt inside it.
2. **macOS:** double-click `install.command`. **Windows:** double-click `install.bat`.
   The first run sets up Python packages (a few minutes).
3. The installer pulls the game's content pack from your headset, saves an untouched backup in
   `cache/`, builds the patched pack on your computer (~2–3 minutes), and pushes it back (~1 minute).
4. Start the game → item spawner → **Modded**.

Needs about 8 GB free disk space (original backup + patched copy).

### After a game update
Game updates replace the content pack, so the weapons disappear. Just run the installer again.
It picks up the new original automatically.

### Uninstall
Double-click `uninstall.command` / `uninstall.bat`. It restores the original pack from `cache/`.
(If you deleted `cache/`, reinstall the game from the Meta store instead.)

## How it works

The game keeps all of its content in one file, `Android/obb/com.rustltd.h3vr2/footlong.base.hdog`:
- a `HDOG` header,
- a gzipped JSON manifest (asset GUID → bundle, bundle dependencies),
- ~2500 Unity asset bundles (one per item),
- FMOD sound banks,
- a table of contents at the end (`offset, size, name, tag` per entry, then `count, toc_offset`).

Each new weapon is made by:
1. **Cloning a real game weapon's bundle**, which keeps all of its mechanics, physics, sounds and
   hand poses. The clone gets a new name and CAB id.
2. **Adding the GLB model** as a new Unity mesh, material and ASTC textures, using the game's own
   shader. The donor's visuals are hidden.
3. **Refitting the gameplay points** to the new shape: grip and fore-grip positions, muzzle,
   blade length and edge collider, and physics colliders sliced to the model.
4. **Rendering a new icon and spawner sprite** from the model.
5. **Cloning the donor's item definitions** (`ItemDef`, `ItemSpawnerDef`, `ItemFirearmDef`, …) into
   the core bundle under new names. A `Modded` spawner folder and manifest entries are added too.

Everything happens on your own copy. No game files are included in this package.

## Adding your own weapon

1. Drop a `.glb` into `models/` (keep it under ~30k triangles; decimate in Blender if needed).
2. Add an entry to `tools/weapons.py`, copying one of the existing entries:
   - `donor`: the game item whose mechanics you want, e.g. `G17Gen3`, `AKM`, `M4A1`, `Mosin9130`,
     `Model37`, `Kukri`, `FireAxe`, `Crowbar`, `Nightstick`.
   - `forward` / `up`: which axes of *your model* point toward the muzzle and the top.
   - `length`: the item's real length in metres.
   - `grip_model`: the point on your model where the shooting hand goes, in the model's own
     coordinates. `grip_target`: where the donor's hand sits; copy it from a similar entry.
   - `fit`: `fit_firearm` (with muzzle / fore-grip points), `fit_sword` (blade start/end), or `fit_blunt`.
3. Run the installer. Look at `cache/build/<id>_fit.png` to check the alignment: red crosses are
   grips and the muzzle, green boxes are colliders.

## Making an NPC from a model

`tools/build_npc.py <original footlong.base.hdog> <model.glb> <out dir> [config.json]` turns a humanoid
GLB (standing, facing forward, about A- or T-pose) into a `.h3mod` enemy for the Mod Manager app.

A sosig's body is one mesh that the game bends across 4 physics bones (legs, hips, torso, head).
The script paints the model's vertices onto those bones, so the NPC walks, bobs, leans, crouches,
ragdolls and loses limbs like any sosig. It can't add skeletal animation (e.g. swinging arms):
the game has no animation system for sosigs, and Quest mods can't add code.
Hands stay the floating sosig hands that hold weapons.

`config.json` can override `id`, `display`, `name`, `description`, `height`, `cuts` (legs|hips,
hips|torso and torso|head boundaries as fractions of height), `arm_x`, `head_x`, `base_profile`
(whose AI/gear to copy, default the SoSec Enforcer) and `credit`. Check `<id>_weights.png` in the
output folder to see which bone each part follows. The mod needs Mod Manager 1.3 or newer.

## Notes / limits
- Moving parts (bolt, trigger, charging handle) are not animated on the custom models; the
  donor's mechanics still work (reloading, cycling, fire modes).
- Weapons from a mod can stay in your saved hub/inventory. If you uninstall, drop them first.
- The 3D models came from third-party sources (Sketchfab etc.) and depict others' IP. Check each
  model's license before redistributing, and credit the authors.
- Unofficial fan mod, not affiliated with RUST LTD. Use at your own risk; keep your backup.
