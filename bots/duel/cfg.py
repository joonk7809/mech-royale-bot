import json
import os

DEFAULT = {
    "nav": "auto",
    "track": True,
    "sound_track": True,
    "lead": True,
    "lead_latency": 0.075,
    "dodge": True,
    "dodge_laser": True,
    "face_threat": True,
    "strafe": True,
    "strafe_period": (0.3, 0.9),
    "strafe_mode": "flight",
    "fight_boost": True,
    "fight_boost_energy": 45.0,
    "silent": True,
    "silent_frac": 0.4,
    "loot": True,
    "loot_until": 150.0,
    "loot_radius": 40.0,
    "npc_hunt": False,
    "npc_max_hp_frac_loss": 0.35,
    "crates": True,
    "drops": False,
    "drop_max_dist": 170.0,
    "drop_enemy_clear": 90.0,
    "zone_margin_s": 12.0,
    "zone_frac": 0.55,
    "cover_hold": True,
    "climb_out": True,
    "climb_energy": 90.0,
    "boost_reserve": 40.0,
    "cover_every": 0.5,
    "cover_impl": "local",
    "fight_range_scale": 1.0,
    "engage_ratio": 1.25,
    "opportunist_hp": 0.45,
    "third_party_radius": 160.0,
    "squad_avoid": False,
    "avoid_r": 115.0,
    "squad_press": True,
    "duelist": True,
    "grounded": False,
    "den_r": 120.0,
    "den_leash": 30.0,
    "heal_to": 0.9,
    "peek_hp": 0.45,
    "duel_engage_r": 120.0,
    "pve_r": 40.0,
    "press_r": 150.0,
    "press_min_hp": 0.35,
    "retreat_hp": 0.45,
    "regen_hide": True,
    "scan": True,
    "weapon_pref": {"laser": 3.0, "lightning": 2.0, "gun": 1.5, "mortar": 0.5},
    "drop_gun_for": [],
    "upgrade_rank": [
        "plating", "armor", "nanites", "laser_damage", "laser_charge", "sensors", "servos",
        "gyros", "gun_damage", "gun_rate", "gun_mag", "lightning_efficiency", "lightning_range",
        "lightning_chain", "capacitor", "reactor", "jets", "gun_velocity", "laser_pierce",
        "mortar_reload", "mortar_velocity", "mortar_splash",
    ],
    "gun_fire_tol": 0.8,
    "laser_fire_tol": 0.7,
    "laser_min_frac": 0.98,
    "laser_release_on_align": True,
    "laser_max_acc": 25.0,
    "laser_dodge_deg": 6.0,
    "mortar_use": True,
    "lightning_use": True,
    "debug_draw": False,
}


def make(overrides=None):
    c = dict(DEFAULT)
    env = os.environ.get("MECH_SQUAD_CFG")
    if env:
        c.update(json.loads(env))
    if overrides:
        c.update(overrides)
    return c
