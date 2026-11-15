"""Per-weapon configuration for the H3VR2 custom weapon mod.

Coordinates:
  *_model points are in the source GLB's own (glTF) coordinates.
  forward/up are glTF axes that become the item's +Z (forward) and +Y (up).
  grip_target and all fitting happen in the donor prefab's root space (metres).
"""
import numpy as np
import modkit as mk
from build_mod_fit import fit_firearm, fit_sword, fit_blunt, saber_blade

MOD_FOLDER = "Modded"


def drop_mats(*names):
    return lambda p: p["mat"]["name"] not in names


def keep_mats(*names):
    return lambda p: p["mat"]["name"] in names


WEAPONS = [
    dict(
        id="Mod_PortalGun", name="Portal Gun", description="Aperture handheld device. Fires 5.7mm (P90 magazines).",
        model="portal_gun.glb", donor="P90_Tactical", host="P90_Receiver",
        forward=(1, 0, 0), up=(0, 1, 0), length=0.56,
        grip_model=(-0.0395, -0.0065, 0.0), grip_target=(0.0, -0.034, -0.008),
        folders=["Firearms/Rifle/SubmachineGun"],
        fit=lambda pf, V, xf, scripts, s: fit_firearm(
            pf, V, xf, scripts,
            muzzle=["_Muzzle", "_MuzzleMount"], muzzle_model=(0.047, -0.006, 0.0),
            moves={"_ForeGrip": (0.024, -0.019, 0.0)},
            hide_mounts=["_RailMountRight", "_RailMountLeft", "_TopRail", "_MuzzleMount"]),
    ),
    dict(
        id="Mod_GravityGun", name="Gravity Gun", description="Zero-point energy field manipulator. Fires 12ga (USAS-12 magazines).",
        model="gravity_gun.glb", donor="USAS12", host="USAS12_Receiver",
        keep=keep_mats("view_body", "view_barrel", "xen2", "gauge_glow"),
        forward=(0, 0, 1), up=(0, 1, 0), length=0.72,
        grip_model=(0.0, -0.065, -0.17), grip_target=(0.0, -0.037, -0.017),
        folders=["Firearms/Shotgun/SelectFireShotgun"],
        emission_boost=2.0,
        fit=lambda pf, V, xf, scripts, s: fit_firearm(
            pf, V, xf, scripts,
            muzzle=["_Muzzle", "_MuzzleAttach"], muzzle_model=(0.0, 0.0, 0.38),
            moves={"_ForeGrab": (0.0, -0.075, 0.10)},
            hide_mounts=["_CarryHandleMount", "_MuzzleAttach"]),
    ),
    dict(
        id="Mod_Lightsaber", name="Lightsaber", description="An elegant weapon for a more civilized age.",
        model="light-saber.glb", donor="Kabartana", host=None,
        keep=lambda p: p["name"] != "Object_33",
        forward=(-1, 0, 0), up=(0, 1, 0), length=0.28,
        grip_model=(-2.026, 0.84, 3.708), grip_target=(0.0, 0.0, 0.03),
        folders=["MeleeWeapons/Tactical"],
        extras=[saber_blade(length=0.95, radius=0.0135, color=(0.35, 0.65, 1.0))],
        emission_boost=3.0,
        mass_g=900,
        fit=lambda pf, V, xf, scripts, s: fit_sword(pf, V, xf, scripts, blade_start=0.03, blade_end=0.98),
    ),
    dict(
        id="Mod_Monado", name="Monado", description="The blade that sees the future.",
        model="monado_from_xenoblade_chronicles.glb", donor="Kabartana", host=None,
        forward=(0, 0, -1), up=(-1, 0, 0), length=1.25,
        grip_model=(0.146, 0.1255, 0.55), grip_target=(0.0, 0.0, -0.08),
        folders=["MeleeWeapons/Tactical"],
        tweak=lambda m: m.update(emissive_factor=(0.1, 0.55, 1.4), roughness=0.35) if m["name"] == "bloom_blue" else m.update(roughness=0.45, metallic=0.6),
        mass_g=2600,
        fit=lambda pf, V, xf, scripts, s: fit_sword(
            pf, V, xf, scripts, blade_start=None, blade_end=None, blade_zone_from=xf((0.146, 0.1255, 0.0))[2],
            grabs={"grabPt": xf((0.146, 0.1255, 0.47)), "grabPt (1)": xf((0.146, 0.1255, 0.66)), "grabvol": xf((0.146, 0.1255, 0.57))}),
    ),
    dict(
        id="Mod_TungTungSahur", name="Tung Tung Tung Sahur", description="Grab him by the legs. Bonk.",
        model="tung_25k.glb", donor="ShortSledge", host="ShortSledge",
        forward=(0, 1, 0), up=(1, 0, 0), length=0.78,
        grip_model=(-0.05, -0.38, 0.0), grip_target=(0.0, 0.0, -0.026),
        folders=["MeleeWeapons/Improvised"],
        mass_g=3500,
        fit=lambda pf, V, xf, scripts, s: fit_blunt(pf, V, xf, scripts, head_from=xf((0, -0.18, 0))[2]),
    ),
]
