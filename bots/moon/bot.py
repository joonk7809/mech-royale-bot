import math

import numpy as np
import random
import sys
import traceback

from . import cfg as cfgmod
from . import nav
from .aim import arc_points, lead, mortar_solve, muzzle, on_target, target_center, wrap, yaw_pitch
from .combat import loadout_dps, want_range
from .threat import laser_danger, projectile_dodge
from .track import Tracker

NAME = "moon"


def _unit(x, y):
    n = math.hypot(x, y)
    return (0.0, 0.0) if n < 1e-9 else (x / n, y / n)


class Bot:
    name = NAME

    def __init__(self, hello, **kw):
        self.cfg = cfgmod.make(kw)
        c = hello["config"]
        self.C = c
        self.W, self.F, self.navkind = nav.load(hello["map"]["dir"], self.cfg["nav"], c)
        self.rng = random.Random(int(hello.get("seed", 0)))
        self.track = Tracker(self.cfg, hello)
        self.side = 1.0
        self.side_t = 0.0
        self.hist = []
        self.stuck_until = -1.0
        self.phase_key = None
        self.phase_start = None
        self.last_dmg_t = -1e9
        self.mode = "start"
        self.rank = {u: i for i, u in enumerate(self.cfg["upgrade_rank"])}
        self.label = ""
        self.spot_key = None
        self.errors = 0
        self.nav_errors = 0
        self.stuck_n = 0
        self.stuck_t = -1e9
        self.route_t = -1e9
        self.route_goal = (1e9, 1e9)
        self.no_route = False
        self.climbing = False
        self.alt_until = -1.0
        self.escape = (0.0, 0.0)
        self.F_alt = nav.Follower(self.W.local) if hasattr(self.W, "local") else self.F
        self._warm()
        self.cover_cache = None
        self.lock = None
        self.solo_cache = None
        self.jump_t = 0.0
        self.short_until = -1.0
        self.last_ok = {}
        self.spot = None

    def _warm(self):
        try:
            a, b = (0.0, 0.0), (60.0, 40.0)
            self.W.los((0.0, 0.0, 8.0), (60.0, 40.0, 4.5))
            self.W.shot((0.0, 0.0, 8.0), (60.0, 40.0, 4.5))
            self.W.reachable(a, b)
            self.W.cover(a, [(30.0, 30.0, 8.0)], 20.0)
            self.W.line_clear(a, b)
            nav.Follower(getattr(self.W, "local", self.W)).step(a, b)
        except Exception:
            traceback.print_exc(file=sys.stderr)

    def end(self, msg):
        pass

    def act(self, obs):
        try:
            a = self._act(obs)
            self.last_ok = {k: a[k] for k in ("move", "aim", "boost") if k in a}
            return a
        except Exception:
            self.errors += 1
            if self.errors <= 3:
                traceback.print_exc(file=sys.stderr)
            return {"tick": obs["tick"], **self.last_ok}

    def _act(self, obs):
        t = obs["t"]
        me = obs["self"]
        self.t = t
        self.me = me
        self.obs = obs
        self.pos = me["pos"]
        self.xy = (me["pos"][0], me["pos"][1])
        self.track.update(obs, me)
        for e in obs["events"]:
            ty = e.get("type")
            if ty == "damaged":
                self.last_dmg_t = t
            elif ty == "effect" and e.get("effect") == "short":
                self.short_until = t + self.C["weapons"]["lightning"]["short_s"]
        self.wk = [w["kind"] if w else None for w in me["weapons"]]
        self.kinds = tuple(k for k in self.wk if k)
        self._zone()
        a = {"tick": obs["tick"]}
        if obs.get("offer"):
            a["pick"] = self._pick(obs["offer"])
        self._loot_take(a)
        enemies = self.track.enemies(t, 6.0)
        self.enemies = enemies
        aim_y, aim_p, fire = self._combat(enemies)
        mv, boost, jump = self._move(enemies)
        mv, boost = self._dodge(mv, boost, enemies)
        if self.cfg["fight_jump"]:
            jump = self._fight_jump(enemies) or jump
        if self.cfg["grounded"]:
            jump = False
            if not me["grounded"]:
                boost = False
        if aim_y is None:
            aim_y, aim_p = self._scan(mv)
        a["move"] = [round(mv[0], 4), round(mv[1], 4)]
        a["boost"] = bool(boost)
        a["jump"] = bool(jump)
        a["aim"] = [round(aim_y, 4), round(max(self.C["mech"]["min_pitch"], min(self.C["mech"]["max_pitch"], aim_p)), 4)]
        a["fire"] = fire
        if self._want_reload(enemies):
            a["reload"] = True
        if self.cfg["debug_draw"]:
            a["debug"] = {"label": f"{self.mode} {self.label}"[:78]}
        return a

    def _zone(self):
        z = self.obs["zone"]
        key = (round(z["next_center"][0], 1), round(z["next_center"][1], 1), round(z["next_radius"], 1))
        if key != self.phase_key:
            self.phase_key = key
            self.phase_start = ((z["center"][0], z["center"][1]), z["radius"])
        self.z = z
        nc = z["next_center"]
        nr = z["next_radius"]
        self.nc = (nc[0], nc[1])
        self.nr = nr
        P = self.xy
        dl = self._deadline_at(P)
        self.zone_deadline = dl
        sp = self.me["stats"]["walk_speed"]
        need = max(0.0, math.dist(P, self.nc) - nr * 0.85) * 1.35 / sp
        self.zone_need = need
        self.zone_urgent = (not self.me["in_zone"]) or (dl is not None and self.t + need + self.cfg["zone_margin_s"] >= dl)

    def _circle_at(self, tau):
        z = self.z
        (c0, r0) = self.phase_start
        ss, se = z["shrink_start"], z["shrink_end"]
        f = 0.0 if tau <= ss else (1.0 if tau >= se or se <= ss else (tau - ss) / (se - ss))
        return (c0[0] + (self.nc[0] - c0[0]) * f, c0[1] + (self.nc[1] - c0[1]) * f), r0 + (self.nr - r0) * f

    def _deadline_at(self, P, n=24):
        if math.dist(P, self.nc) <= self.nr - 4.0:
            return None
        z = self.z
        ss, se = z["shrink_start"], z["shrink_end"]
        lo = max(self.t, ss)
        for k in range(n + 1):
            tau = lo + (max(se, lo) - lo) * k / n
            c, r = self._circle_at(tau)
            if math.hypot(P[0] - c[0], P[1] - c[1]) > r - 6.0:
                return tau
        return se

    def _hold_point(self):
        nc, nr = self.nc, self.nr
        P = self.xy
        frac = self.cfg["zone_frac"]
        if nr < 30 or self.obs["alive"] <= 3:
            frac = 0.2
        d = math.dist(P, nc)
        if d <= nr * frac:
            return P
        u = _unit(P[0] - nc[0], P[1] - nc[1])
        base = (nc[0] + u[0] * nr * frac, nc[1] + u[1] * nr * frac)
        if not self.cfg["cover_hold"] or nr < 30:
            return base
        key = (self.phase_key, round(base[0] / 15), round(base[1] / 15))
        if self.spot_key != key:
            self.spot_key = key
            self.spot = self._wall_spot(base, min(30.0, nr * 0.25))
        return self.spot

    def _wall_spot(self, base, rad):
        W = getattr(self.W, "local", self.W)
        rng = self.rng
        cands = [base] + [(base[0] + r * math.cos(a), base[1] + r * math.sin(a)) for r, a in ((rng.uniform(4, rad), rng.uniform(0, 2 * math.pi)) for _ in range(40))]
        cands = [c for c in cands if W.walkable(c)]
        if not cands:
            return base
        ang = [k * math.pi / 4 for k in range(8)]
        A = []
        B = []
        for c in cands:
            z = W.ground(c[0], c[1]) + 5.0
            for a in ang:
                A.append((c[0], c[1], z))
                B.append((c[0] + 9.0 * math.cos(a), c[1] + 9.0 * math.sin(a), z))
        clear = W.los_many(A, B)
        best = base
        bs = -1e9
        for k, c in enumerate(cands):
            out = math.atan2(c[1] - self.nc[1], c[0] - self.nc[0])
            sc = 0.0
            for q, a in enumerate(ang):
                if not clear[k * 8 + q]:
                    sc += 1.0 + 1.5 * max(0.0, math.cos(a - out))
            sc -= math.dist(c, base) / 15.0
            if sc > bs:
                bs, best = sc, c
        return best

    def _in_safe(self, xy, slack=0.0):
        if math.dist(xy, self.nc) <= self.nr * 0.9 + slack:
            return True
        dl = self._deadline_at(xy, 12)
        if dl is None:
            return True
        sp = self.me["stats"]["walk_speed"]
        trip = (math.dist(self.xy, xy) + max(0.0, math.dist(xy, self.nc) - self.nr * 0.85)) * 1.35 / sp
        return self.t + trip + self.cfg["zone_margin_s"] + 4.0 < dl

    def _in_live(self, xy, margin=8.0):
        c, r = self._circle_at(self.t + 2.0)
        return math.dist(xy, c) < r - margin

    def _pick(self, offer):
        best = 0
        bv = 1e9
        for i, ch in enumerate(offer["choices"]):
            v = self.rank.get(ch["id"], 500 + i)
            if v < bv:
                bv, best = v, i
        return best

    def _pref(self, k):
        return self.cfg["weapon_pref"].get(k, 0.0) if k else 0.0

    def _loot_take(self, a):
        reach = self.C["loot"]["pickup_radius"]
        best = None
        for p in self.obs["pickups"]:
            if math.hypot(p["pos"][0] - self.xy[0], p["pos"][1] - self.xy[1]) > reach - 0.3 or abs(p["pos"][2] - self.pos[2]) > 3.8:
                continue
            k = p["kind"]
            if k in self.kinds or self._pref(k) <= 0:
                continue
            slot = self._slot_for(k)
            if slot is None:
                continue
            g = self._pref(k) - (self._pref(self.wk[slot]) if self.wk[slot] else 0.0)
            if best is None or g > best[0]:
                best = (g, p["id"], slot)
        if best is not None:
            a["take"] = best[1]
            if self.wk[best[2]] is not None:
                a["drop"] = best[2]

    def _slot_for(self, k):
        if None in self.wk:
            return self.wk.index(None)
        worst = None
        for i, w in enumerate(self.wk):
            if w == "gun" and k not in self.cfg["drop_gun_for"]:
                continue
            ws = self.me["weapons"][i]
            if w == "laser" and ws.get("charge", 0) > 0:
                continue
            if self._pref(k) > self._pref(w) + 0.25 and (worst is None or self._pref(w) < self._pref(self.wk[worst])):
                worst = i
        return worst

    def _wants_pickup(self, k):
        if k in self.kinds or self._pref(k) <= 0:
            return False
        return self._slot_for(k) is not None

    def _threat_rank(self, m):
        d = math.dist(self.xy, (m.pos[0], m.pos[1]))
        aggro = self.t - m.aggro_t < 3.0
        aiming = abs(wrap(math.atan2(self.xy[1] - m.pos[1], self.xy[0] - m.pos[0]) - m.aim[0])) < 0.2
        s = d
        if aggro:
            s -= 120
        if aiming:
            s -= 40
        if m.charging and aiming:
            s -= 60
        s += m.hp / 40.0
        return s

    def _aims_at_me(self, m, tol):
        return abs(wrap(math.atan2(self.xy[1] - m.pos[1], self.xy[0] - m.pos[0]) - m.aim[0])) < tol

    def _odds(self, m):
        d = math.dist(self.xy, (m.pos[0], m.pos[1]))
        wc = self.C["weapons"]
        my = loadout_dps(self.kinds, d, wc, self.me["cubes"], m.weapons) + 1e-3
        th = loadout_dps(m.weapons, d, wc, m.cubes, self.kinds) + 1e-3
        armor = self.me["stats"].get("armor", 0.0)
        t_me = self.me["hp"] / (th * (1.0 - armor))
        t_them = m.hp / my
        return t_me / t_them

    def _combat(self, enemies):
        me = self.me
        t = self.t
        fire = [False, False]
        self.pve = None
        self.engaged = None
        self.fight = False
        self.threats = []
        vis = [m for m in enemies if t - m.seen < 0.15]
        for m in enemies:
            d = math.dist(self.xy, (m.pos[0], m.pos[1]))
            aggro = t - m.aggro_t < 4.0
            close = d < 130 or (d < 290 and "laser" in m.weapons)
            if aggro or close:
                self.threats.append(m)
        target = None
        if self.cfg["finish_low"] and self.lock is not None and me["hp"] > self.cfg["finish_min_hp"] * me["max_hp"]:
            m = next((m for m in enemies if m.id == self.lock and t - m.seen < 1.5), None)
            if m is not None and m.hp < self.cfg["finish_frac"] * m.max_hp:
                target = m
                self.fight = True
                vis = []
        if target is None and self.cfg["squad_press"]:
            near = [(m, math.dist(self.xy, (m.pos[0], m.pos[1]))) for m in vis]
            near = [(m, d) for m, d in near if d < self.cfg["press_r"]]
            if near:
                m, d = min(near, key=lambda q: q[0].hp + 2.0 * q[1])
                target = m
                self.fight = me["hp"] > self.cfg["press_min_hp"] * me["max_hp"] or d < 25
                vis = []
        if vis:
            cand = sorted(vis, key=self._threat_rank)
            for m in cand:
                d = math.dist(self.xy, (m.pos[0], m.pos[1]))
                aggro = t - m.aggro_t < 4.0
                others = sum(1 for o in enemies if o is not m and math.dist((o.pos[0], o.pos[1]), self.xy) < self.cfg["third_party_radius"] and (t - o.aggro_t < 6.0 or self._aims_at_me(o, 0.35)))
                odds = self._odds(m)
                if aggro or (d < 60 and not self.cfg["squad_avoid"]):
                    target = m
                    self.fight = odds >= self.cfg["engage_ratio"] * (1.0 + 0.5 * others) or d < 25
                    break
                if self.cfg["squad_avoid"] and not aggro:
                    continue
                if m.hp < self.cfg["opportunist_hp"] * me["hp"] and others == 0 and odds >= 1.6 and d < 200:
                    target = m
                    self.fight = True
                    break
                if m.charging and self._aims_at_me(m, 0.3):
                    target = m
                    self.fight = odds >= self.cfg["engage_ratio"]
                    break
        if target is None and self.threats:
            m = min(self.threats, key=self._threat_rank)
            if t - m.seen < 3.0 and t - m.aggro_t < 4.0:
                target = m
        self.engaged = target
        self.lock = target.id if target is not None else None
        if target is not None:
            return self._shoot_mech(target, fire)
        nt = self._pve_target()
        if nt is not None:
            return self._shoot_static(nt, fire)
        return None, 0.0, fire

    def _near_passive(self, p, r):
        return any(self.t - m.aggro_t >= 4.0 and math.dist((m.pos[0], m.pos[1]), (p[0], p[1])) < r for m in self.enemies)

    def _avoid_dir(self):
        r = self.cfg["avoid_r"]
        near = [(m, math.dist(self.xy, (m.pos[0], m.pos[1]))) for m in self.enemies]
        near = [(m, d) for m, d in near if d < r]
        passive = [m for m, d in near if self.t - m.aggro_t >= 4.0]
        if not passive and len(near) < 2:
            return None
        ax = ay = 0.0
        for m, d in near:
            u = _unit(self.xy[0] - m.pos[0], self.xy[1] - m.pos[1])
            w = (r - d) / r + 0.2
            ax += u[0] * w
            ay += u[1] * w
        return _unit(ax, ay)

    def _pve_target(self):
        if not self.cfg["loot"] or self.t > self.cfg["loot_until"] or self.zone_urgent:
            return None
        if self.threats:
            return None
        best = None
        if self.cfg["npc_hunt"] and self.me["hp"] > 0.6 * self.me["max_hp"]:
            for i, (p, v, hp, ts) in self.track.npcs.items():
                if self.t - ts > 0.15:
                    continue
                d = math.dist(self.xy, (p[0], p[1]))
                if d > 150 or not self._in_safe((p[0], p[1]), 30):
                    continue
                if self.cfg["squad_avoid"] and self._near_passive(p, self.cfg["avoid_r"]):
                    continue
                s = d + hp / 10.0
                if best is None or s < best[0]:
                    best = (s, ("npc", i, p, v))
        if self.cfg["crates"]:
            for i, (key, p, k, ts, hp) in self.track.items.items():
                if key != "crates" or self.t - ts > 0.15:
                    continue
                d = math.dist(self.xy, (p[0], p[1]))
                if d > 110 or not self._in_safe((p[0], p[1]), 20):
                    continue
                if self.cfg["squad_avoid"] and self._near_passive(p, self.cfg["avoid_r"]):
                    continue
                s = d + 30
                if best is None or s < best[0]:
                    best = (s, ("crate", i, p, (0.0, 0.0, 0.0)))
        return best[1] if best else None

    def _gun_slot(self):
        return self.wk.index("gun") if "gun" in self.wk else None

    def _shoot_static(self, tgt, fire):
        kind, i, p, v = tgt
        me = self.me
        zc = p[2] + (1.75 if kind == "npc" else 1.2)
        gs = self._gun_slot()
        self.pve = tgt
        if gs is None:
            return None, 0.0, fire
        w = me["weapons"][gs]
        y0, p0 = yaw_pitch(p[0] - self.pos[0], p[1] - self.pos[1], zc - self.pos[2] - me["stats"]["muzzle_height"])
        org = muzzle(me, "muzzle_height", y0, p0, self.cfg["lead_latency"])
        yw, pt, _ = lead(org, (p[0], p[1], zc), v, w["stats"]["speed"], self.cfg["lead_latency"], self.cfg["lead"])
        d = math.dist(org, (p[0], p[1], zc))
        if d > w["stats"]["range"] * 0.95:
            return yw, pt, fire
        if not self.W.shot(org, (p[0], p[1], zc)):
            return yw, pt, fire
        if w.get("ammo", 1) > 0 and w.get("reload", 0) <= 0 and on_target(me, yw, pt, d, 1.2, self.cfg["gun_fire_tol"]):
            fire[gs] = True
        return yw, pt, fire

    def _shoot_mech(self, m, fire):
        me = self.me
        t = self.t
        lat = self.cfg["lead_latency"]
        tc = target_center(m)
        visible = t - m.seen < 0.15
        tvel = m.vel if visible else (0.0, 0.0, 0.0)
        tpos = tc if visible else (m.at(t)[0], m.at(t)[1], tc[2])
        d = math.dist(self.xy, (tpos[0], tpos[1]))
        R = 2.5 * (1 + 0.05 * m.cubes)
        eye = (self.pos[0], self.pos[1], self.pos[2] + me["stats"]["eye_height"])
        los = visible and self.W.shot(eye, tpos)
        ay, ap, _ = lead(eye, tpos, (0, 0, 0), 1e9, 0.0, False)
        chosen = None
        for s, w in enumerate(me["weapons"]):
            if not w:
                continue
            k = w["kind"]
            st = w["stats"]
            if k == "laser":
                ch = w.get("charge", 0.0)
                full = st["charge"]
                yw, pt, _ = lead(muzzle(me, "muzzle_height", ay, ap, lat), tpos, tvel, 1e9, lat * 0.7, self.cfg["lead"])
                in_range = d < st["range"] * 0.97
                if ch > 0:
                    if not los:
                        hold_left = full + st["hold_s"] - ch
                        fire[s] = hold_left > 0.25
                        chosen = chosen or (yw, pt)
                        continue
                    ready = ch >= full * self.cfg["laser_min_frac"]
                    tol = self.cfg["laser_fire_tol"]
                    if not self.cfg["laser_release_on_align"]:
                        fire[s] = not ready
                    elif ready and on_target(me, yw, pt, d, R, tol) and (m.acc < self.cfg["laser_max_acc"] or ch > full + st["hold_s"] - 0.4):
                        fire[s] = False
                    else:
                        fire[s] = True
                    chosen = (yw, pt)
                elif w["cooldown"] <= 0.1 and los and in_range and t >= self.short_until:
                    fire[s] = True
                    chosen = chosen or (yw, pt)
            elif k == "lightning" and self.cfg["lightning_use"]:
                if los and d < st["range"] * 0.95 and me["energy"] >= st["energy"] + 4:
                    yw = math.atan2(tpos[1] - self.pos[1], tpos[0] - self.pos[0])
                    if abs(wrap(yw - me["aim"][0])) < math.radians(st["cone_deg"]) * 0.8:
                        fire[s] = True
                    chosen = chosen or (yw, ap)
        gs = self._gun_slot()
        if gs is not None:
            w = me["weapons"][gs]
            st = w["stats"]
            org = muzzle(me, "muzzle_height", ay, ap, lat)
            yw, pt, _ = lead(org, tpos, tvel, st["speed"], lat, self.cfg["lead"])
            gaim = (yw, pt)
            laser_busy = chosen is not None and any(fire[i] or (self.me["weapons"][i] and self.me["weapons"][i].get("charge", 0) > 0) for i in range(2) if self.wk[i] == "laser")
            aim = chosen if laser_busy else gaim
            dd = math.dist(org, tpos)
            if los and dd < st["range"] and w.get("ammo", 1) > 0 and w.get("reload", 0) <= 0:
                if on_target(me, gaim[0], gaim[1], dd, R, self.cfg["gun_fire_tol"]) and (not laser_busy or on_target(me, aim[0], aim[1], dd, R, 1.0)):
                    fire[gs] = True
            chosen = aim
        for s, w in enumerate(me["weapons"]):
            if w and w["kind"] == "mortar" and self.cfg["mortar_use"] and w["cooldown"] <= 0.0 and 25 < d < 230:
                sol = mortar_solve(me, (tpos[0], tpos[1], m.pos[2]), tvel, w["stats"], lat)
                if sol is not None:
                    pts = arc_points(me, sol[0], sol[1], w["stats"], sol[2])
                    if not all(self.W.los(pts[i], pts[i + 1]) for i in range(len(pts) - 2)):
                        sol = mortar_solve(me, (tpos[0], tpos[1], m.pos[2]), tvel, w["stats"], lat, True)
                if sol is not None and (chosen is None or not any(fire)):
                    chosen = (sol[0], sol[1])
                    if on_target(me, sol[0], sol[1], d, 3.0, 1.0):
                        fire[s] = True
        if chosen is None:
            return ay, ap, fire
        return chosen[0], chosen[1], fire

    def _want_reload(self, enemies):
        gs = self._gun_slot()
        if gs is None:
            return False
        w = self.me["weapons"][gs]
        return w.get("ammo", 12) < w["stats"]["mag"] * 0.4 and w.get("reload", 0) <= 0 and self.engaged is None and not any(self.t - m.seen < 1.0 for m in enemies)

    def _nav_to(self, goal):
        try:
            mv = (self.F_alt if self.t < self.alt_until else self.F).step(self.xy, goal)
        except Exception:
            self.nav_errors += 1
            if self.nav_errors <= 2:
                traceback.print_exc(file=sys.stderr)
            mv = _unit(goal[0] - self.xy[0], goal[1] - self.xy[1])
        return _unit(mv[0], mv[1])

    def _loot_goal(self):
        if not self.cfg["loot"] or self.t > self.cfg["loot_until"]:
            return None
        best = None
        hp_ok = self.me["hp"] > 0.35 * self.me["max_hp"]
        for i, (key, p, k, ts, hp) in self.track.items.items():
            d = math.dist(self.xy, (p[0], p[1]))
            if d > self.cfg["loot_radius"] or not self._in_safe((p[0], p[1]), 15):
                continue
            dz = p[2] - self.pos[2]
            if dz > 40:
                continue
            if key == "pickups":
                if not self._wants_pickup(k):
                    continue
                v = 60.0 if None in self.wk else 25.0 * (self._pref(k) - max(self._pref(w) for w in self.wk if w != "gun"))
            elif key == "cubes":
                v = 45.0 if self.me["cubes"] < 10 else 8.0
            else:
                continue
            if dz > 3:
                v *= 0.6
            if any(math.dist((m.pos[0], m.pos[1]), (p[0], p[1])) < 70 for m in self.enemies):
                v *= 0.25
            if self.cfg["squad_avoid"] and self._near_passive(p, self.cfg["avoid_r"]):
                continue
            if not hp_ok:
                v *= 0.3
            s = v / (d + 25.0)
            if best is None or s > best[0]:
                best = (s, (p[0], p[1], p[2]), key)
        return best

    def _drop_goal(self):
        if not self.cfg["drops"]:
            return None
        best = None
        for dr in self.obs["drops"]:
            p = dr["pos"]
            d = math.dist(self.xy, (p[0], p[1]))
            if d > self.cfg["drop_max_dist"]:
                continue
            if dr["holder"] is not None and dr["holder"] != self.me["id"]:
                continue
            travel = d / self.me["stats"]["walk_speed"]
            if travel > dr["lands_in"] + 20:
                continue
            near = [m for m in self.enemies if math.dist((m.pos[0], m.pos[1]), (p[0], p[1])) < (self.cfg["avoid_r"] if self.cfg["squad_avoid"] else self.cfg["drop_enemy_clear"])]
            if near:
                continue
            if best is None or d < best[0]:
                best = (d, (p[0], p[1], p[2]), dr)
        return best

    def _move(self, enemies):
        me = self.me
        t = self.t
        boost = False
        jump = False
        speed = 1.0
        goal = None
        label = ""
        hp_frac = me["hp"] / me["max_hp"]
        e = self.engaged
        cover_from = [((m.pos[0], m.pos[1], m.pos[2] + 7.5)) for m in self.threats if t - m.seen < 3.0]
        av = self._avoid_dir() if self.cfg["squad_avoid"] and not self.zone_urgent else None
        mk = self._medkit(hp_frac) if self.cfg["medkit"] else None
        if mk is not None:
            return self._medkit_move(mk, e)
        if av is not None:
            self.mode = "avoid"
            hp_ = self._hold_point()
            tz = _unit(hp_[0] - self.xy[0], hp_[1] - self.xy[1])
            u = _unit(av[0] + 0.4 * tz[0], av[1] + 0.4 * tz[1])
            goal = (self.xy[0] + u[0] * 30.0, self.xy[1] + u[1] * 30.0)
            if not self._in_live(goal, 4.0):
                goal = hp_
            boost = me["energy"] > 30
        elif self.zone_urgent:
            self.mode = "rotate"
            goal = self._hold_point()
            boost = (not me["in_zone"] or (self.zone_deadline is not None and self.t + self.zone_need * 0.8 + 4 > self.zone_deadline)) and (me["energy"] > self.cfg["boost_reserve"] or self.nr < 80)
        elif e is not None and not self.fight:
            self.mode = "evade"
            c = self._cover(cover_from, 32.0)
            if c is not None and not self._in_live(c, 4.0):
                c = None
            if c is None and self.nr < 80:
                self.mode = "fight"
            elif c is not None:
                goal = c
            else:
                away = _unit(self.xy[0] - e.pos[0], self.xy[1] - e.pos[1])
                hp_ = self._hold_point()
                tz = _unit(hp_[0] - self.xy[0], hp_[1] - self.xy[1])
                goal = (self.xy[0] + (away[0] + 0.5 * tz[0]) * 30, self.xy[1] + (away[1] + 0.5 * tz[1]) * 30)
                if not self._in_live(goal):
                    goal = hp_
            boost = me["energy"] > 30
        elif e is not None:
            self.mode = "fight"
            goal = None
        elif hp_frac < self.cfg["retreat_hp"] and self.cfg["regen_hide"] and t - self.last_dmg_t < 12:
            self.mode = "heal"
            c = self._cover(cover_from, 30.0)
            goal = c if c is not None else self.xy
            speed = self.cfg["silent_frac"] if self.cfg["silent"] else 1.0
        else:
            dg = self._drop_goal()
            lg = self._loot_goal()
            if dg is not None and (lg is None or dg[0] < 120 or hp_frac < 0.8):
                self.mode = "drop"
                goal = dg[1]
                boost = dg[2]["lands_in"] < dg[0] / me["stats"]["walk_speed"] and me["energy"] > 40
                if math.dist(self.xy, goal[:2]) < dg[2]["radius"] - 3:
                    goal = None
                    speed = 0.0
            elif lg is not None:
                self.mode = "loot"
                goal = lg[1]
                label = lg[2]
            elif self.pve is not None:
                self.mode = "pve"
                p = self.pve[2]
                d = math.dist(self.xy, (p[0], p[1]))
                want = 70.0 if self.pve[0] == "npc" else 25.0
                if d > want + 15.0:
                    goal = (p[0], p[1])
                elif self.pve[0] == "npc":
                    self.label = "npc"
                    mv = self._strafe(p, d, want)
                    mv, j2, b2 = self._unstick(mv)
                    return mv, b2, j2
                else:
                    goal = None
                    speed = 0.0
            else:
                self.mode = "hold"
                hp_ = self._hold_point()
                if math.dist(self.xy, hp_) > 6.0:
                    goal = hp_
                else:
                    goal = None
                    speed = 0.0
        self.label = label
        if self.mode == "fight":
            mv = self._fight_move(e)
            charging = any(w and w.get("charge", 0) > 0 for w in me["weapons"])
            fb = self.cfg["fight_boost"] and not charging and me["energy"] > self.cfg["fight_boost_energy"]
            return mv, fb, False
        if goal is not None and self.cfg["climb_out"] and not self.cfg["grounded"] and self._no_route(goal[:2]):
            self.mode += "+climb"
            return self._climb(goal[:2])
        if goal is None:
            mv = (0.0, 0.0)
        else:
            mv = self._nav_to(goal[:2])
            if not self.cfg["grounded"] and len(goal) > 2 and goal[2] - self.pos[2] > 2.5 and math.dist(self.xy, goal[:2]) < 14 and me["energy"] > 25:
                jump = me["grounded"]
                boost = True
            if self.mode == "hold" and self.cfg["silent"] and not self.zone_urgent:
                speed = 1.0 if math.dist(self.xy, goal[:2]) > 40 else self.cfg["silent_frac"]
        mv = (mv[0] * speed, mv[1] * speed)
        mv, j2, b2 = self._unstick(mv)
        return mv, boost or b2, jump or j2

    def _medkit(self, hp_frac):
        me = self.me
        sp = me["stats"]["walk_speed"]
        best = None
        for dr in self.obs["drops"]:
            p = dr["pos"]
            if dr["holder"] is not None and dr["holder"] != me["id"]:
                continue
            d = math.dist(self.xy, (p[0], p[1]))
            if d > self.cfg["medkit_r"] or not self._in_live((p[0], p[1]), 4.0):
                continue
            rr = dr["radius"] + 3.0
            if any(math.dist((m.pos[0], m.pos[1]), (p[0], p[1])) < rr and self.t - m.seen < 1.0 for m in self.enemies):
                continue
            travel = d / sp
            if dr["lands_in"] > 0:
                if hp_frac >= self.cfg["medkit_pre_hp"] or travel + 3.0 < dr["lands_in"] - 6.0:
                    continue
            elif not (hp_frac < self.cfg["medkit_hp"] or (d < self.cfg["medkit_near_r"] and hp_frac < self.cfg["medkit_near_hp"]) or dr["holder"] == me["id"]):
                continue
            if best is None or d < best[0]:
                best = (d, p, dr)
        return best

    def _medkit_move(self, mk, e):
        d, p, dr = mk
        self.mode = "medkit"
        c = (p[0], p[1])
        ring = self.cfg["medkit_ring"]
        if d > ring:
            mv = self._nav_to(c)
            mv, j2, b2 = self._unstick(mv)
            return mv, (d > 20 and self.me["energy"] > 25) or b2, j2
        if e is not None:
            mv = self._fight_move(e)
        else:
            mv = (0.0, 0.0)
        nx, ny = self.xy[0] + mv[0] * 3.0, self.xy[1] + mv[1] * 3.0
        if math.dist((nx, ny), c) > ring:
            tc = _unit(c[0] - self.xy[0], c[1] - self.xy[1])
            mv = _unit(mv[0] * 0.3 + tc[0], mv[1] * 0.3 + tc[1])
        return mv, False, False

    def _cover(self, threats, radius):
        if not threats:
            return None
        ck = self.cover_cache
        if ck is not None and self.t - ck[0] < self.cfg["cover_every"] and ck[1] == radius and math.dist(ck[2], self.xy) < 4.0 and len(ck[3]) == len(threats) and all(math.dist(a, b) < 6.0 for a, b in zip(ck[3], threats)):
            return ck[4]
        f = getattr(self.W, "geo_cover", None) if self.cfg["cover_impl"] == "geo" else None
        c = (f or self.W.cover)(self.xy, threats, radius)
        self.cover_cache = (self.t, radius, self.xy, list(threats), c)
        return c

    def _solo_spot(self, e):
        G = getattr(self.W, "G", None)
        if G is None:
            return None
        t = self.t
        others = [m for m in self.enemies if m is not e and t - m.seen < self.cfg["solo_mem"]]
        if not others:
            return None
        ck = self.solo_cache
        if ck is not None and t - ck[0] < self.cfg["solo_every"] and ck[1] == e.id and len(ck[2]) == len(others):
            return ck[3]
        from geo.query import lattice_around, visible_from
        nav = G.nav
        cells = lattice_around(nav, self.xy, self.cfg["solo_r"], self.cfg["solo_step"])
        if cells.size == 0:
            return None
        xy = nav.center(cells)
        dm = np.hypot(xy[:, 0] - self.xy[0], xy[:, 1] - self.xy[1])
        keep = np.argsort(dm)[:72]
        cells, xy, dm = cells[keep], xy[keep], dm[keep]
        z = nav.S[cells]
        P = np.c_[xy, z]
        others = sorted(others, key=lambda m: math.dist(self.xy, (m.pos[0], m.pos[1])))[:5]
        E = np.array([(m.pos[0], m.pos[1], m.pos[2] + 8.0) for m in others], float)
        seen = visible_from(G.world, E, P)
        tc = np.array([[e.pos[0], e.pos[1], e.pos[2] + 4.5]] * len(P), float)
        eye = P + np.array([0.0, 0.0, 8.0])
        ok = np.asarray(G.world.shot_clear_many(eye, tc), bool)
        dt = np.hypot(xy[:, 0] - e.pos[0], xy[:, 1] - e.pos[1])
        zc, zr = self._circle_at(self.t + 2.0)
        live = np.hypot(xy[:, 0] - zc[0], xy[:, 1] - zc[1]) < zr - 4.0
        score = 10.0 * seen + np.where(ok, 0.0, 6.0) + dm / 12.0 + np.where(dt < 20.0, 3.0, 0.0) + np.where(live, 0.0, 50.0)
        k = int(np.argmin(score))
        here = visible_from(G.world, E, np.array([[self.xy[0], self.xy[1], self.pos[2]]]))[0]
        res = (float(xy[k][0]), float(xy[k][1])) if score[k] + 2.0 < 10.0 * here else None
        self.solo_cache = (t, e.id, [m.id for m in others], res)
        return res

    def _fight_move(self, e):
        if self.cfg["solo"]:
            sp = self._solo_spot(e)
            if sp is not None and math.dist(sp, self.xy) > 2.0:
                self.mode = "solo"
                return self._nav_to(sp)
        d = math.dist(self.xy, (e.pos[0], e.pos[1]))
        return self._strafe(e.pos, d, want_range(self.kinds, e.weapons, self.C["weapons"]) * self.cfg["fight_range_scale"])

    def _strafe(self, tp, d, want):
        t = self.t
        dx, dy = tp[0] - self.xy[0], tp[1] - self.xy[1]
        if t > self.side_t:
            lo, hi = self.cfg["strafe_period"]
            if self.cfg["strafe_mode"] == "flight":
                per = min(hi, max(lo, d / self.C["weapons"]["gun"]["speed"] * self.rng.uniform(0.8, 1.4)))
            else:
                per = self.rng.uniform(lo, hi)
            self.side_t = t + per
            self.side = -self.side if self.rng.random() < 0.8 else self.side
        u = _unit(dx, dy)
        perp = (-u[1] * self.side, u[0] * self.side)
        radial = max(-1.0, min(1.0, (d - want) / 25.0))
        if not self.cfg["strafe"]:
            perp = (0.0, 0.0)
        mx = perp[0] + u[0] * radial
        my = perp[1] + u[1] * radial
        mv = _unit(mx, my)
        ahead = (self.xy[0] + mv[0] * 6.0, self.xy[1] + mv[1] * 6.0)
        if not self.W.line_clear(self.xy, ahead) or not self._in_live(ahead):
            self.side = -self.side
            perp = (-u[1] * self.side, u[0] * self.side)
            mv = _unit(perp[0] + u[0] * radial, perp[1] + u[1] * radial)
        return mv

    def _no_route(self, goal):
        if self.t - self.route_t > 1.0 or math.dist(goal, self.route_goal) > 25.0:
            self.route_t = self.t
            self.route_goal = goal
            ok = True
            try:
                ok = self.W.reachable(self.xy, goal)
            except Exception:
                ok = True
            self.no_route = (not ok) or self.stuck_n >= 3
            if ok:
                self.stuck_n = max(0, self.stuck_n - 1) if self.t - self.stuck_t > 8.0 else self.stuck_n
        return self.no_route

    def _climb(self, goal):
        me = self.me
        u = _unit(goal[0] - self.xy[0], goal[1] - self.xy[1])
        if me["grounded"] and me["energy"] < self.cfg["climb_energy"] and not self.climbing:
            return (0.0, 0.0), False, False
        self.climbing = not me["grounded"] or me["energy"] >= self.cfg["climb_energy"]
        if me["grounded"] and me["energy"] < 5:
            self.climbing = False
        return u, me["energy"] > 1, me["grounded"]

    def _unstick(self, mv):
        t = self.t
        me = self.me
        self.hist.append((t, self.xy))
        while self.hist and t - self.hist[0][0] > 1.2:
            self.hist.pop(0)
        jet = me["energy"] > 20
        if t < self.stuck_until:
            return self.escape, jet and me["grounded"], jet
        if math.hypot(*mv) > 0.5 and len(self.hist) > 8 and t - self.hist[0][0] > 1.0 and math.dist(self.hist[0][1], self.xy) < 1.5:
            self.stuck_n += 1
            self.stuck_t = t
            self.stuck_until = t + 0.8
            self.alt_until = t + 4.0
            ang = math.atan2(mv[1], mv[0]) + math.pi + self.rng.uniform(-1.2, 1.2)
            self.escape = (math.cos(ang), math.sin(ang))
            for f in (self.F, self.F_alt):
                if hasattr(f, "reset"):
                    f.reset()
                if hasattr(f, "stuck_t"):
                    f.stuck_t = 9.0
            self.hist.clear()
            return self.escape, jet and me["grounded"], jet
        return mv, False, False

    def _fight_jump(self, enemies):
        me = self.me
        t = self.t
        if not me["grounded"] or me["energy"] < self.cfg["jump_energy"] or t < self.jump_t:
            return False
        r = self.cfg["jump_r"]
        hot = [m for m in enemies if t - m.seen < 0.5 and math.dist(self.xy, (m.pos[0], m.pos[1])) < r and (t - m.aggro_t < 4.0 or self._aims_at_me(m, 0.25))]
        if not hot:
            return False
        lo, hi = self.cfg["jump_gap"]
        self.jump_t = t + self.rng.uniform(lo, hi)
        return True

    def _dodge(self, mv, boost, enemies):
        me = self.me
        if self.cfg["dodge"]:
            d, urg = projectile_dodge(me, self.obs["projectiles"], self.W, self.C["weapons"]["mortar"], self.side)
            if d is not None:
                k = min(3.0, urg)
                mv = _unit(mv[0] + d[0] * k, mv[1] + d[1] * k)
                boost = boost or (urg > 2.0 and me["energy"] > 20)
        if self.cfg["dodge_laser"]:
            ld = laser_danger(me, enemies, self.t, self.W, self.C["weapons"]["laser"], self.cfg["laser_dodge_deg"])
            if ld is not None:
                m, left, dist = ld
                u = _unit(self.xy[0] - m.pos[0], self.xy[1] - m.pos[1])
                if self.t > self.side_t - 0.1 and left < 0.3:
                    self.side = -self.side
                    self.side_t = self.t + 0.4
                perp = (-u[1] * self.side, u[0] * self.side)
                c = self._cover([(m.pos[0], m.pos[1], m.pos[2] + 7.5)], 14.0)
                if c is not None:
                    mv = self._nav_to(c)
                else:
                    mv = _unit(perp[0] * 2.0 + mv[0] * 0.3, perp[1] * 2.0 + mv[1] * 0.3)
                boost = me["energy"] > 15
        return mv, boost

    def _scan(self, mv):
        me = self.me
        t = self.t
        if self.cfg["face_threat"]:
            for (ts, b, w, by) in reversed(self.track.bearings):
                if t - ts < 2.0:
                    m = self.track.mechs.get(by)
                    if m is not None and t - m.seen < 5.0:
                        p = m.at(t)
                        return math.atan2(p[1] - self.xy[1], p[0] - self.xy[0]), 0.0
                    return b, 0.0
            mem = [m for m in self.enemies if t - m.seen < 6.0]
            if mem:
                m = min(mem, key=lambda m: math.dist(self.xy, (m.pos[0], m.pos[1])))
                if math.dist(self.xy, (m.pos[0], m.pos[1])) < 220:
                    p = m.at(t)
                    return math.atan2(p[1] - self.xy[1], p[0] - self.xy[0]), 0.0
            snd = [s for s in self.track.sound_threats(t, self.pos, 2.0) if s[2] != "far"]
            if snd:
                s = max(snd, key=lambda s: s[4])
                return s[1], 0.0
        if self.mode == "pve" and self.pve is not None:
            p = self.pve[2]
            return math.atan2(p[1] - self.xy[1], p[0] - self.xy[0]), 0.0
        if not self.cfg["scan"]:
            if math.hypot(*mv) > 0.1:
                return math.atan2(mv[1], mv[0]), 0.0
            return me["aim"][0], 0.0
        if math.hypot(*mv) > 0.5:
            base = math.atan2(mv[1], mv[0])
            amp = 0.9
        else:
            base = math.atan2(self.nc[1] - self.xy[1], self.nc[0] - self.xy[0]) if math.dist(self.xy, self.nc) > 5 else me["aim"][0]
            amp = 2.2
        return wrap(base + amp * math.sin(t * 2 * math.pi / 3.2)), 0.0
