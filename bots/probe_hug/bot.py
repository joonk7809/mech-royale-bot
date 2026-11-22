import math

from bots.main import bot as main_bot

NAME = "hug"


class Bot:
    def __init__(self, hello, **kw):
        self.m = main_bot.Bot(hello, grounded=False)
        self.navkind = self.m.navkind

    def end(self, msg):
        pass

    def act(self, obs):
        a = self.m.act(obs)
        a["fire"] = [False, False]
        a.pop("reload", None)
        me = obs["self"]
        px, py = me["pos"][0], me["pos"][1]
        foes = [m for m in obs["mechs"] if m.get("kind") == "mech"]
        if not foes:
            return a
        foes.sort(key=lambda m: math.hypot(m["pos"][0] - px, m["pos"][1] - py))
        h = foes[0]
        hx, hy = h["pos"][0], h["pos"][1]
        rest = foes[1:]
        if rest:
            cx = sum(m["pos"][0] for m in rest) / len(rest)
            cy = sum(m["pos"][1] for m in rest) / len(rest)
        else:
            cx, cy = hx + (hx - px), hy + (hy - py)
        ux, uy = hx - cx, hy - cy
        n = math.hypot(ux, uy) or 1.0
        gx, gy = hx + 5.5 * ux / n, hy + 5.5 * uy / n
        d = math.hypot(gx - px, gy - py)
        try:
            mv = self.m.F.step((px, py), (gx, gy))
        except Exception:
            mv = ((gx - px) / max(d, 1e-6), (gy - py) / max(d, 1e-6))
        s = min(1.0, d / 4.0)
        a["move"] = [round(mv[0] * s, 4), round(mv[1] * s, 4)]
        a["boost"] = d > 12 and me["energy"] > 20
        a["aim"] = [round(math.atan2(hy - py, hx - px), 4), 0.0]
        return a
