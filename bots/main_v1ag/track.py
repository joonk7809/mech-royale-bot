import math

SOUND_DIST = {"near": 35.0, "mid": 110.0, "far": 230.0}
HOSTILE_SOUNDS = {"gun", "laser", "laser_charge", "lightning", "mortar", "step", "boost", "jet", "reload"}


class Mech:
    __slots__ = ("id", "pos", "vel", "aim", "hp", "max_hp", "cubes", "weapons", "charging", "seen", "first", "charge_t0", "aggro_t", "dmg_to_me", "acc")

    def __init__(self, i, t):
        self.id = i
        self.first = t
        self.charge_t0 = None
        self.aggro_t = -1e9
        self.dmg_to_me = 0.0
        self.hp = 1400.0
        self.max_hp = 1400.0
        self.cubes = 0
        self.weapons = ("gun",)
        self.charging = False
        self.acc = 0.0
        self.vel = None

    def at(self, t):
        dt = min(t - self.seen, 3.0)
        return (self.pos[0] + self.vel[0] * dt, self.pos[1] + self.vel[1] * dt, self.pos[2])


class Tracker:
    def __init__(self, cfg, hello):
        self.cfg = cfg
        self.mechs = {}
        self.npcs = {}
        self.npc_home = {}
        self.items = {}
        self.sounds = []
        self.bearings = []
        self.dead_npcs = set()
        self.forget = 12.0 if cfg["track"] else 0.15

    def update(self, obs, me):
        t = obs["t"]
        visible = set()
        for m in obs["mechs"]:
            i = m["id"]
            if m["kind"] == "mech":
                tr = self.mechs.get(i)
                if tr is None:
                    tr = self.mechs[i] = Mech(i, t)
                tr.pos = m["pos"]
                if tr.vel is not None and t - tr.seen < 0.25:
                    dv = math.hypot(m["vel"][0] - tr.vel[0], m["vel"][1] - tr.vel[1]) / max(t - tr.seen, 0.05)
                    tr.acc = 0.5 * tr.acc + 0.5 * dv
                tr.vel = m["vel"]
                tr.aim = m["aim"]
                tr.hp = m.get("hp", tr.hp)
                tr.max_hp = m.get("max_hp", tr.max_hp)
                tr.cubes = m.get("cubes", tr.cubes)
                tr.weapons = tuple(m.get("weapons") or tr.weapons)
                ch = bool(m.get("charging"))
                if ch and not tr.charging:
                    tr.charge_t0 = t
                if not ch:
                    tr.charge_t0 = None
                tr.charging = ch
                tr.seen = t
                visible.add(i)
            else:
                self.npcs[i] = (m["pos"], m["vel"], m.get("hp", 350.0), t)
                self.npc_home.setdefault(i, m["pos"])
        for i in [k for k, v in self.mechs.items() if t - v.seen > self.forget]:
            del self.mechs[i]
        for i in [k for k, v in self.npcs.items() if t - v[3] > 20.0]:
            del self.npcs[i]
        for e in obs["events"]:
            ty = e.get("type")
            if ty == "damaged" and e.get("by") is not None:
                b = e["by"]
                if b < 16:
                    tr = self.mechs.get(b)
                    if tr is not None:
                        tr.aggro_t = t
                        tr.dmg_to_me += e["amount"]
                    if b not in visible and e.get("bearing") is not None:
                        self.bearings.append((t, e["bearing"], e["weapon"], b))
            elif ty == "kill":
                self.mechs.pop(e["target"], None)
        self.bearings = [x for x in self.bearings if t - x[0] < 4.0]
        if self.cfg["sound_track"]:
            for s in obs["sounds"]:
                self.sounds.append((t - s.get("age", 0.0), s["kind"], s["bearing"], s["dist"]))
        self.sounds = [s for s in self.sounds if t - s[0] < 5.0]
        self._items(obs, me, t)
        self.visible = visible

    def _items(self, obs, me, t):
        listed = set()
        for key in ("crates", "cubes", "pickups"):
            for it in obs[key]:
                self.items[it["id"]] = (key, it["pos"], it.get("kind"), t, it.get("hp"))
                listed.add(it["id"])
        px, py = me["pos"][0], me["pos"][1]
        for i in [k for k, v in self.items.items() if k not in listed and math.hypot(v[1][0] - px, v[1][1] - py) < 30.0]:
            del self.items[i]

    def enemies(self, t, max_age=None):
        a = self.forget if max_age is None else max_age
        return [m for m in self.mechs.values() if t - m.seen <= a]

    def sound_threats(self, t, me_pos, max_age=3.0):
        out = []
        for ts, kind, bearing, dist in self.sounds:
            if t - ts > max_age or kind not in HOSTILE_SOUNDS:
                continue
            r = SOUND_DIST[dist]
            out.append((kind, bearing, dist, (me_pos[0] + r * math.cos(bearing), me_pos[1] + r * math.sin(bearing)), ts))
        return out
