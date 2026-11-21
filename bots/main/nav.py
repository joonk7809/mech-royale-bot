import heapq
import json
import math
import os

import numpy as np

RES = 2.0
RISE = 1.6
SQ2 = math.sqrt(2.0)
NB = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2))


def _pip(px, py, ring):
    xs = ring[0::2]
    ys = ring[1::2]
    n = len(xs)
    inside = np.zeros(px.shape, bool)
    j = n - 1
    for i in range(n):
        xi, yi, xj, yj = xs[i], ys[i], xs[j], ys[j]
        if yi != yj:
            c = ((yi > py) != (yj > py)) & (px < (xj - xi) * (py - yi) / (yj - yi) + xi)
            inside ^= c
        j = i
    return inside


class World:
    def __init__(self, map_dir, mech_height=9.0):
        with open(os.path.join(map_dir, "v2", "world.json")) as f:
            w = json.load(f)
        t = w["terrain"]
        T = np.fromfile(os.path.join(map_dir, "v2", t["file"]), "<i2").astype(np.float32).reshape(t["ny"], t["nx"]) * t.get("scale", 0.01)
        self.T = T
        self.tx0 = t["minX"]
        self.ty0 = t["minY"]
        self.tstep = t["step"]
        k = int(round(RES / t["step"]))
        G = T[::k, ::k].copy()
        self.ny, self.nx = G.shape
        self.x0 = self.tx0
        self.y0 = self.ty0
        H = G.copy()
        xs = self.x0 + np.arange(self.nx) * RES
        ys = self.y0 + np.arange(self.ny) * RES
        for p in w["prisms"]:
            r = p["ring"]
            bx0, bx1 = min(r[0::2]), max(r[0::2])
            by0, by1 = min(r[1::2]), max(r[1::2])
            i0 = max(0, int((bx0 - self.x0) / RES))
            i1 = min(self.nx, int((bx1 - self.x0) / RES) + 2)
            j0 = max(0, int((by0 - self.y0) / RES))
            j1 = min(self.ny, int((by1 - self.y0) / RES) + 2)
            if i0 >= i1 or j0 >= j1:
                continue
            px, py = np.meshgrid(xs[i0:i1], ys[j0:j1])
            m = _pip(px, py, r)
            for hole in p.get("holes") or []:
                m &= ~_pip(px, py, hole)
            if not m.any():
                continue
            sub = H[j0:j1, i0:i1]
            g = G[j0:j1, i0:i1]
            hit = m & (p["base"] < g + mech_height) & (p["top"] > sub)
            sub[hit] = p["top"]
        self.H = H
        P = np.pad(H, 1, mode="edge")
        Hm = H.copy()
        for dj in (0, 1, 2):
            for di in (0, 1, 2):
                np.maximum(Hm, P[dj:dj + self.ny, di:di + self.nx], out=Hm)
        self.Hm = Hm
        self.Hl = H.ravel().tolist()
        self.Hml = Hm.ravel().tolist()
        self.bounds = (w["bounds"]["minX"] + 3, w["bounds"]["maxX"] - 3, w["bounds"]["minY"] + 3, w["bounds"]["maxY"] - 3)

    def cell(self, x, y):
        i = min(self.nx - 1, max(0, int(round((x - self.x0) / RES))))
        j = min(self.ny - 1, max(0, int(round((y - self.y0) / RES))))
        return i, j

    def ground(self, x, y):
        fx = (x - self.tx0) / self.tstep
        fy = (y - self.ty0) / self.tstep
        i = int(min(max(fx, 0), self.T.shape[1] - 2))
        j = int(min(max(fy, 0), self.T.shape[0] - 2))
        ax = min(max(fx - i, 0.0), 1.0)
        ay = min(max(fy - j, 0.0), 1.0)
        T = self.T
        return float((T[j, i] * (1 - ax) + T[j, i + 1] * ax) * (1 - ay) + (T[j + 1, i] * (1 - ax) + T[j + 1, i + 1] * ax) * ay)

    def surface(self, x, y):
        i, j = self.cell(x, y)
        return float(self.H[j, i])

    def los_many(self, A, B):
        A = np.asarray(A, float).reshape(-1, 3)
        B = np.asarray(B, float).reshape(-1, 3)
        d = np.hypot(B[:, 0] - A[:, 0], B[:, 1] - A[:, 1])
        k = int(min(240, max(2, math.ceil(float(d.max(initial=0.0)) / 1.5))))
        s = np.linspace(0.0, 1.0, k + 2)[1:-1]
        P = A[:, None, :] + (B - A)[:, None, :] * s[None, :, None]
        i = np.clip(np.rint((P[..., 0] - self.x0) / RES).astype(np.int64), 0, self.nx - 1)
        j = np.clip(np.rint((P[..., 1] - self.y0) / RES).astype(np.int64), 0, self.ny - 1)
        return ~(P[..., 2] < self.H[j, i]).any(axis=1)

    def los(self, a, b):
        return bool(self.los_many([a], [b])[0])

    def shot(self, a, b):
        return bool(self.los_many([a], [b])[0])

    def walkable(self, xy):
        i, j = self.cell(xy[0], xy[1])
        return self.Hm[j, i] - self.H[j, i] <= RISE

    def line_clear(self, a, b):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(2, int(d / 1.0) + 1)
        s = np.linspace(0.0, 1.0, n)
        x = a[0] + (b[0] - a[0]) * s
        y = a[1] + (b[1] - a[1]) * s
        i = np.clip(np.rint((x - self.x0) / RES).astype(np.int64), 0, self.nx - 1)
        j = np.clip(np.rint((y - self.y0) / RES).astype(np.int64), 0, self.ny - 1)
        h = self.H[j, i]
        hm = self.Hm[j, i]
        return bool((hm[1:] - h[:-1] <= RISE).all())

    def reachable(self, a, b):
        return True

    def path(self, start, goal, budget=60000):
        s = Search(self, start, goal)
        s.run(budget)
        return s.result()

    def cover(self, me_xy, threats_xyz, radius=30.0):
        if not threats_xyz:
            return None
        ang = np.linspace(0, 2 * math.pi, 16, endpoint=False)
        rr = np.array([5.0, 10.0, 16.0, 24.0, radius])
        X = (me_xy[0] + np.outer(rr, np.cos(ang))).ravel()
        Y = (me_xy[1] + np.outer(rr, np.sin(ang))).ravel()
        D = np.repeat(rr, len(ang))
        i = np.clip(np.rint((X - self.x0) / RES).astype(np.int64), 0, self.nx - 1)
        j = np.clip(np.rint((Y - self.y0) / RES).astype(np.int64), 0, self.ny - 1)
        mi, mj = self.cell(me_xy[0], me_xy[1])
        h0 = self.H[mj, mi]
        ok = (self.Hm[j, i] - self.H[j, i] <= RISE) & (np.abs(self.H[j, i] - h0) < 3.0)
        Z = self.H[j, i] + 6.0
        cov = ok.copy()
        for t in threats_xyz:
            A = np.tile(np.asarray(t, float), (len(X), 1))
            B = np.stack([X, Y, Z], 1)
            cov &= ~self.los_many(A, B)
        if not cov.any():
            return None
        idx = np.flatnonzero(cov)
        best = None
        for q in idx[np.argsort(D[idx])][:6]:
            if self.line_clear(me_xy, (X[q], Y[q])):
                best = (float(X[q]), float(Y[q]))
                break
        return best


class Search:
    def __init__(self, W, start, goal):
        self.W = W
        si, sj = W.cell(*start)
        gi, gj = W.cell(*goal)
        self.nx = W.nx
        self.s = sj * W.nx + si
        self.g = gj * W.nx + gi
        self.gi, self.gj = gi, gj
        self.goal = goal
        self.cost = {self.s: 0.0}
        self.par = {self.s: -1}
        self.open = [(self._h(si, sj), self.s)]
        self.best = self.s
        self.besth = self._h(si, sj)
        self.done = False

    def _h(self, i, j):
        dx = abs(i - self.gi)
        dy = abs(j - self.gj)
        return 1.25 * (max(dx, dy) + (SQ2 - 1) * min(dx, dy))

    def run(self, budget):
        if self.done:
            return True
        nx = self.nx
        ny = self.W.ny
        H = self.W.Hl
        Hm = self.W.Hml
        cost = self.cost
        par = self.par
        op = self.open
        g = self.g
        gi = self.gi
        gj = self.gj
        push = heapq.heappush
        pop = heapq.heappop
        n = 0
        while op and n < budget:
            f, c = pop(op)
            if c == g:
                self.best = c
                self.done = True
                return True
            n += 1
            ci = c % nx
            cj = c // nx
            cc = cost[c]
            hc = H[c]
            hh = f - cc
            if hh < self.besth:
                self.besth = hh
                self.best = c
            for di, dj, w in NB:
                i = ci + di
                j = cj + dj
                if i < 0 or j < 0 or i >= nx or j >= ny:
                    continue
                q = j * nx + i
                if Hm[q] - hc > RISE:
                    continue
                nc = cc + w + (0.6 if Hm[q] - H[q] > RISE else 0.0)
                if nc < cost.get(q, 1e18):
                    cost[q] = nc
                    par[q] = c
                    ex = i - gi if i > gi else gi - i
                    ey = j - gj if j > gj else gj - j
                    push(op, (nc + (1.25 * ex + 0.5178 * ey if ex > ey else 1.25 * ey + 0.5178 * ex), q))
        if not op:
            self.done = True
        return self.done

    def result(self):
        c = self.g if self.g in self.par else self.best
        out = []
        while c != -1:
            out.append(((c % self.nx) * RES + self.W.x0, (c // self.nx) * RES + self.W.y0))
            c = self.par[c]
        out.reverse()
        if c == self.g or (self.g in self.par):
            out[-1] = tuple(self.goal)
        return out


class Follower:
    def __init__(self, W, budget=1200):
        self.W = W
        self.budget = budget
        self.goal = None
        self.wps = []
        self.k = 0
        self.search = None
        self.stuck_t = 0.0

    def reset(self):
        self.goal = None

    def step(self, pos, goal):
        W = self.W
        if self.goal is None or math.dist(goal, self.goal) > max(6.0, 0.2 * math.dist(pos, goal)) or self.stuck_t > 1.2:
            self.goal = tuple(goal)
            self.search = Search(W, pos, goal)
            self.stuck_t = 0.0
            if W.line_clear(pos, goal) and math.dist(pos, goal) < 60:
                self.wps = [tuple(goal)]
                self.k = 0
                self.search = None
        if self.search is not None:
            if self.search.run(self.budget):
                self.wps = self.search.result()
                self.k = 0
                self.search = None
        if not self.wps:
            return _unit(goal[0] - pos[0], goal[1] - pos[1])
        while self.k < len(self.wps) - 1 and math.dist(pos, self.wps[self.k]) < 3.0:
            self.k += 1
        best = self.k
        for q in range(min(len(self.wps) - 1, self.k + 10), self.k, -1):
            if W.line_clear(pos, self.wps[q]):
                best = q
                break
        self.k = best
        w = self.wps[best]
        if math.dist(pos, w) > 25 and not W.line_clear(pos, w):
            self.goal = None
        return _unit(w[0] - pos[0], w[1] - pos[1])


def _unit(dx, dy):
    n = math.hypot(dx, dy)
    if n < 1e-6:
        return (0.0, 0.0)
    return (dx / n, dy / n)


class GeoNav:
    def __init__(self, G, local):
        self.G = G
        self.local = local
        self.ground = G.ground
        self.surface = local.surface
        self.walkable = G.walkable

    def los(self, a, b):
        return bool(self.G.los(a, b, True))

    def los_many(self, A, B):
        return np.asarray(self.G.los_many(np.asarray(A, float), np.asarray(B, float), True), bool)

    def shot(self, a, b):
        return bool(self.G.shot_clear(a, b))

    def line_clear(self, a, b):
        return bool(self.G.walk(a, b))

    def dist_many(self, a, B):
        return self.G.dist_many(a, np.asarray(B, float))

    def reachable(self, a, b):
        nv = self.G.nav
        c = nv.snap(a, 6.0)
        if c < 0 or nv.comp.flat[c] == 0:
            return True
        return self.G.path(a, b) is not None

    def cover(self, me_xy, threats_xyz, radius=30.0):
        return self.local.cover(me_xy, threats_xyz, radius)

    def geo_cover(self, me_xy, threats_xyz, radius=30.0):
        if not threats_xyz:
            return None
        r = self.G.cover(me_xy, list(threats_xyz), radius=radius)
        if not r or r.get("seen", 1) > 0:
            return None
        return (float(r["xy"][0]), float(r["xy"][1]))


class GeoFollower:
    def __init__(self, f):
        self.f = f

    def reset(self):
        self.f.reset()

    def step(self, pos, goal):
        return self.f.step(pos, goal)


_LOCAL = {}


def load(map_dir, mode="auto", config=None):
    key = os.path.abspath(map_dir)
    if key not in _LOCAL:
        _LOCAL[key] = World(map_dir)
    local = _LOCAL[key]
    if mode in ("auto", "geo"):
        try:
            import geo
            G = geo.shared(map_dir=map_dir, config=config) if hasattr(geo, "shared") else geo.load(map_dir=map_dir, config=config)
            return GeoNav(G, local), GeoFollower(G.follower()), "geo"
        except Exception:
            if mode == "geo":
                raise
    return local, Follower(local), "local"
