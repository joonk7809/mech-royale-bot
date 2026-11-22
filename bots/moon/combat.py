import math


def p_gun(d):
    return 1.0 / (1.0 + (d / 85.0) ** 2)


def weapon_dps(kind, d, wcfg):
    if kind == "gun":
        w = wcfg["gun"]
        if d > w["range"]:
            return 0.0
        cyc = w["mag"] * w["cooldown"] + w["reload"]
        return w["damage"] * w["mag"] / cyc * p_gun(d)
    if kind == "laser":
        w = wcfg["laser"]
        if d > w["range"]:
            return 0.0
        return w["damage"] / (w["charge"] + w["cooldown"]) * (0.75 if d < 150 else 0.5)
    if kind == "lightning":
        w = wcfg["lightning"]
        if d > w["range"]:
            return 0.0
        return w["damage"] / w["cooldown"] * 0.85
    if kind == "mortar":
        w = wcfg["mortar"]
        if d > 230 or d < 12:
            return 0.0
        return (w["damage"] * 0.3 + w["splash"] * 0.5) / w["cooldown"] * (0.6 if d < 100 else 0.35)
    return 0.0


def loadout_dps(kinds, d, wcfg, cubes, vs=()):
    best = 0.0
    tot = 0.0
    for k in kinds:
        x = weapon_dps(k, d, wcfg)
        if k == "laser" and "mortar" in vs:
            x *= 1.0 + wcfg["laser"].get("cookoff", 0.6)
        if k == "laser" and "lightning" in vs and d < wcfg["lightning"]["range"]:
            x *= 0.4
        tot += x
        best = max(best, x)
    return (0.6 * tot + 0.4 * best) * (1.0 + 0.04 * min(cubes, 10))


def want_range(my_kinds, their_kinds, wcfg):
    lr = wcfg["lightning"]["range"]
    if "lightning" in my_kinds and "mortar" not in their_kinds and "lightning" not in their_kinds:
        return lr * 0.6
    if "lightning" in their_kinds:
        return max(lr + 25.0, 75.0)
    if "laser" in my_kinds:
        return 95.0
    return 70.0
