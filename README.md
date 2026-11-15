# H3VR2-Mod-Manager
This is a WIP Mod Manager to Install Mods Into H3VR2 on Quest
An app that runs on the Quest and adds mods to *Hot Dogs, Horseshoes & Hand Grenades 2*: weapons,
enemies, loot changes and more. Tick what you want, tap **Apply**, start the game.

**Download:** [latest release](https://github.com/faulteatscabages/H3VR2-Mod-Manager/releases/latest) → `H3VR2-ModManager.apk`

Mods available:

| Mod | What it is | Options |
|---|---|---|
| Juggernaut | armoured boss-level enemy, in the sosig spawner | can join SoSec Enforcer patrols |
| Portal Gun, Gravity Gun, Lightsaber, Monado, Tung Tung Tung Sahur | custom weapons | coming to the catalog once their model licences are checked |

New mods show up in the app automatically under **Available online**.

## For players

1. **Install `H3VR2-ModManager.apk`** from the [latest release](https://github.com/faulteatscabages/H3VR2-Mod-Manager/releases/latest) on your Quest once (SideQuest, or any sideloading method). The app
   then shows up under **Library → Unknown sources**.
2. **Start the game once** so it finishes downloading its content, then close it.
3. **Open H3VR2 Mod Manager** and tap **Allow access to game files**. In the settings page that opens,
   turn on **Allow from this source** and go back. The app restarts itself once.
   (Android only lets "installer" apps write into a game's data folder. The app doesn't install anything
   but its own updates, and only when you confirm.)
4. **Tick mods and their options**, then tap **Apply selection**. This takes a few seconds.
5. Start the game. Weapons are in the item spawner under **Modded**, enemies in the sosig spawner.

- **More mods:** tap **Add mod file…** and pick a `.h3mod` from Downloads or any other folder. If the app
  has an online catalog set up, new mods also show under **Available online** with a **Download** button.
- **Remove mods:** tap **Remove all mods**. Uninstalling the app does *not* remove them, so do this first.
- **Game updates:** just open the app after the game updates. It rebuilds your mods from the new game
  files. Mods are stored as instructions ("clone the P90, change these fields, add this model"), not as
  copies of game files, so they keep working unless the game removes or renames what they're based on.
  If one doesn't fit any more, the app installs the others and says which one was skipped and why.
- **Mod and app updates:** with an online catalog, the app downloads newer versions of your mods
  automatically, re-applies them, and offers its own updates (you confirm the install).

## How it works

The game loads every `.hdog` content pack in `Android/obb/com.rustltd.h3vr2/` that belongs to the
`footlong.base` module:
- a data blob is taken from the **first** pack (alphabetical) that has it;
- the manifest is taken from the **last** pack.

So the app never changes the game's own 2.5 GB `footlong.base.hdog`. It reads it and writes two packs
next to it:

| File | Contains |
|---|---|
| `footlong.aaa_mods.hdog` | the game's core bundle with the mods' definitions and edits applied, plus the bundles of modded items (built by cloning the game's own items) |
| `footlong.zzz_mods.hdog` | the game's manifest with the mods' assets added |

Both must be writable by the game (it opens packs read/write), which the app takes care of.
Nothing from the game is downloaded or shared. Everything is built on the headset from the player's own copy.

## Making mods

A `.h3mod` is a zip with `mod.json`, an optional `icon.png` and optional `bundles/` files.
`mod.json` (format 2) describes **operations against the player's game**:

```jsonc
{
  "format": 2, "id": "Mod_Juggernaut", "name": "Juggernaut (enemy)", "description": "…",
  "kind": "npc", "version": 1,                 // bump "version" to push an update through the catalog
  "core": {
    "new": [                                   // clone a game object, then edit the clone
      {"as": "stats", "from": {"key": "SosigStatsProfile/SS_Boss_Warehouse"},
       "edits": [{"path": ["m_Name"], "set": "SS_Mod_Juggernaut"},
                 {"path": ["RefId", "_refId"], "set": "extref://footlong.base/SosigStatsProfile/SS_Mod_Juggernaut"},
                 {"path": ["_damageResistance"], "set": 0.75}]}
    ],
    "container": [                             // give new objects a name the game can find
      {"key": "SosigStatsProfile/SS_Mod_Juggernaut", "asset": {"local": "stats"},
       "preload": {"like": "SosigStatsProfile/SS_Boss_Warehouse"}}
    ],
    "edit": [                                  // change existing game objects
      {"target": {"where": {"script": "EnemyEncounter", "contains": "extref://footlong.base/SosigProfile/SProfile_SoSecEnforcer"}},
       "edits": [{"path": ["enemies"], "duplicate_where": {"contains": "…SProfile_SoSecEnforcer"},
                  "replace": ["…SProfile_SoSecEnforcer", "…SProfile_Mod_Juggernaut"], "with": {"probability": 0.25}}]}
    ]
  },
  "options": [                                 // extra checkboxes under the mod; same structure as "core"
    {"id": "patrols", "name": "Can also join patrols", "core": {"edit": […]}}
  ],
  "bundles": [ … ]                             // item bundles: see below
}
```

- **Sources and targets:** `{"key": "<name>"}` is a named game object, `{"prop_of": "<item>", "script": "ItemSpawnerDef"}`
  is a sub-definition of an item, `{"local": "<as>"}` is an object this mod creates, and
  `{"where": {"script": "LootTable", "contains": "…"}}` (targets only) matches every object of that class that mentions a string.
- **Edits:** `set`, `append`, `insert` (+`index`), `remove` (index), `remove_match` (value),
  `duplicate_where` (+`replace`, `with`). Paths are lists of field names and list indexes. Values can
  reference objects with `{"$ref": {…}}` and binary data with `{"$bytes": "<base64>"}`.
- **Bundles** (custom models) are built on the headset by cloning a game item's bundle:
  `{"name", "donor": {"item": "P90_Tactical"}, "cab", "types", "new" (objects: raw data + class + external
  references), "edit" (field edits on the donor's objects), "rename" (asset GUIDs), "preload_add", "guids"}`.
  You don't write these by hand. The PC tools in `H3VR2-CustomWeapons` turn a GLB model into one.

### Tools (`tools/`, Python 3 + `pip install UnityPy pillow`)

| Script | What it does |
|---|---|
| `make_mod.py <folder> <out dir>` | packs a hand-written mod folder (`mod.json` + optional `icon.png`) into a `.h3mod`; draws a title card if there's no icon |
| `export_mods.py <original pack> <built pack> <build dir> <out dir>` | turns weapons built with `H3VR2-CustomWeapons` into `.h3mod`s |
| `make_catalog.py <mods dir> <out dir> [--apk … --app-version-code N --app-version-name X --notes "…"]` | builds an online catalog folder |

Custom weapons from GLB models: see [`tools/weapon-builder`](tools/weapon-builder) (PC, needs the game's pack pulled over USB; it never uploads it).

`examples/Mod_Juggernaut/mod.json` is a complete hand-written enemy mod to copy from.

### Publishing (online catalog)

1. Run `make_catalog.py` on your mods (and the APK, when you release a new app version).
2. Upload the output folder to any HTTPS host, for example a GitHub repository with GitHub Pages turned on.
3. Put the URL of `catalog.json` into `Catalog.DEFAULT_URL` (`app/src/com/h3vr2mods/manager/Catalog.java`; this repo's is already set to `https://faulteatscabages.github.io/H3VR2-Mod-Manager/catalog.json`, served from `docs/`),
   bump `versionCode` in `AndroidManifest.xml`, and rebuild the app once.

After that, publishing a mod update is: bump its `version`, rebuild the catalog, upload. Every player's
app picks it up the next time it's opened.

## Building the app

`app/` holds the app (plain Java, no Gradle). `buildapk.sh` builds it with the Android SDK bundled
with Unity (6000.3 with Android support): `./buildapk.sh <project dir> <out.apk>`, after copying the
`.h3mod` files you want bundled into `app/assets/mods/`. Sign with your own key at
`debug.keystore` next to the script (`keytool -genkeypair …`). Use the same key for every release,
because Android only installs updates signed with the same key.

## Notes
- Unofficial fan project, not affiliated with RUST LTD. Mods can break with game updates.
- The included models depict other companies' IP and come from third-party creators off SketchFab

## Credits
- Model credits will be listed here for each weapon mod when it's published.
