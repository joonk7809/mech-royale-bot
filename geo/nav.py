import heapq
import math

import numpy as np

from .world import HI_NONE, LO_NONE, OPEN

UNDER = 4
DIRS = ((1, 0), (0, 1), (1, 1), (-1, 1))


def nav_params(config=None):
    m = (config or {}).get("mech", {})
    return dict(radius=float(m.get("radius", 2.5)), height=float(m.get("height", 9.0)),
                step_up=float(m.get("step_up", 1.2)), max_slope_deg=float(m.get("max_slope_deg", 50.0)))


def shift(a, dx, dy, fill):
    out = np.full_like(a, fill)
    ny, nx = a.shape
    ys = slice(max(dy, 0), ny + min(dy, 0))
    yd = slice(max(-dy, 0), ny + min(-dy, 0))
    xs = slice(max(dx, 0), nx + min(dx, 0))
    xd = slice(max(-dx, 0), nx + min(-dx, 0))
    out[yd, xd] = a[ys, xs]
    return out


def build_surface(W, p):
    k = int(round(1.0 / W.res))
    nres = W.res * k
    nx, ny = W.nx // k, W.ny // k
    T = W.terrain
    ti = int(round((W.x0 - W.tx0) / W.tstep))
    tj = int(round((W.y0 - W.ty0) / W.tstep))
    T00 = T[tj:tj + ny, ti:ti + nx]
    T10 = T[tj:tj + ny, ti + 1:ti + nx + 1]
    T01 = T[tj + 1:tj + ny + 1, ti:ti + nx]
    T11 = T[tj + 1:tj + ny + 1, ti + 1:ti + nx + 1]
    g = 0.25 * (T00 + T10 + T01 + T11)
    gx = 0.5 * ((T10 - T00) + (T11 - T01)) / W.tstep
    gy = 0.5 * ((T01 - T00) + (T11 - T10)) / W.tstep
    slope_ok = np.hypot(gx, gy) <= math.tan(math.radians(p["max_slope_deg"]))
    lo2 = W.lo.reshape(W.ny, W.nx)
    hi2 = W.hi.reshape(W.ny, W.nx)
    kd2 = W.kind.reshape(W.ny, W.nx)
    lo = lo2[k // 2::k, k // 2::k][:ny, :nx].astype(np.float32) * np.float32(0.01)
    hi = hi2[k // 2::k, k // 2::k][:ny, :nx].astype(np.float32) * np.float32(0.01)
    kd = kd2[k // 2::k, k // 2::k][:ny, :nx]
    has = kd > 0
    under = has & (lo - g >= p["height"])
    on_top = has & ~under & (hi > g)
    S = np.where(on_top, hi, g).astype(np.float32)
    kind = np.where(on_top, kd, np.where(under, UNDER, OPEN)).astype(np.int8)
    return nres, nx, ny, S, kind, slope_ok, lo2, hi2, k


def build_free(W, p, nres, nx, ny, S, kind, slope_ok, lo2, hi2, k):
    r = p["radius"]
    half = W.res * 0.5
    blocked = np.zeros((ny, nx), dtype=bool)
    reach = int(math.ceil((r + half) / W.res)) + 1
    up = (S + p["step_up"]) * np.float32(100.0)
    head = (S + p["height"]) * np.float32(100.0)
    pad = reach + k
    lop = np.pad(lo2, pad, constant_values=LO_NONE)
    hip = np.pad(hi2, pad, constant_values=HI_NONE)
    for b in range(-reach, reach + 1):
        for a in range(-reach, reach + 1):
            dx = (a - 0.5 * (k - 1)) * W.res
            dy = (b - 0.5 * (k - 1)) * W.res
            ex = max(abs(dx) - half, 0.0)
            ey = max(abs(dy) - half, 0.0)
            if ex * ex + ey * ey > r * r:
                continue
            lo_s = lop[pad + b::k, pad + a::k][:ny, :nx]
            hi_s = hip[pad + b::k, pad + a::k][:ny, :nx]
            blocked |= (lo_s < head) & (hi_s > up)
    xs = W.x0 + (np.arange(nx) + 0.5) * nres
    ys = W.y0 + (np.arange(ny) + 0.5) * nres
    bx0, by0, bx1, by1 = W.bounds
    inx = (xs >= bx0 + r) & (xs <= bx1 - r)
    iny = (ys >= by0 + r) & (ys <= by1 - r)
    terrain_surface = (kind == OPEN) | (kind == UNDER)
    free = ~blocked & iny[:, None] & inx[None, :] & (slope_ok | ~terrain_surface)
    return free


def mutual_edges(free, S, step_up):
    edges = []
    for dx, dy in DIRS:
        f2 = shift(free, dx, dy, False)
        s2 = shift(S, dx, dy, 0.0)
        m = free & f2 & (np.abs(s2 - S) <= step_up)
        edges.append(m)
    return edges


def components(free, S, step_up):
    ny, nx = free.shape
    n = nx * ny
    idx = np.arange(n, dtype=np.int32).reshape(ny, nx)
    A, B = [], []
    for (dx, dy), m in zip(DIRS, mutual_edges(free, S, step_up)):
        a = idx[m]
        A.append(a)
        B.append(a + np.int32(dy * nx + dx))
    A = np.concatenate(A)
    B = np.concatenate(B)
    L = np.arange(n, dtype=np.int32)
    while True:
        la, lb = L[A], L[B]
        diff = la != lb
        if not diff.any():
            break
        A, B, la, lb = A[diff], B[diff], la[diff], lb[diff]
        np.minimum.at(L, np.maximum(la, lb), np.minimum(la, lb))
        while True:
            L2 = L[L]
            if np.array_equal(L2, L):
                break
            L = L2
    fr = free.ravel()
    lab = L[fr]
    uniq, inv, cnt = np.unique(lab, return_inverse=True, return_counts=True)
    order = np.argsort(-cnt, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(order.size)
    comp = np.full(n, -1, dtype=np.int32)
    comp[fr] = rank[inv]
    return comp.reshape(ny, nx), cnt[order]


def corner_nodes(free, comp, sizes, min_comp, frac_r, frac_max, spacing):
    ny, nx = free.shape
    c = np.zeros_like(free)
    for sx in (1, -1):
        for sy in (1, -1):
            c |= free & ~shift(free, sx, sy, False) & shift(free, sx, 0, False) & shift(free, 0, sy, False)
    w = 2 * frac_r + 1
    cs = np.cumsum(np.cumsum(np.pad((~free).astype(np.int32), ((frac_r + 1, frac_r), (frac_r + 1, frac_r))), 0), 1)
    box = cs[w:w + ny, w:w + nx] - cs[0:ny, w:w + nx] - cs[w:w + ny, 0:nx] + cs[0:ny, 0:nx]
    frac = box / float(w * w)
    big = np.zeros(sizes.size + 1, dtype=bool)
    big[:-1] = sizes >= min_comp
    c &= (frac < frac_max) & big[comp]
    j, i = np.nonzero(c)
    order = np.argsort(frac[j, i], kind="stable")
    return thin(i[order], j[order], spacing, [])


def thin(i, j, spacing, seed):
    grid = {}
    out = []
    s2 = spacing * spacing
    for x, y in seed:
        grid.setdefault((x // spacing, y // spacing), []).append((x, y))
    for x, y in zip(i.tolist(), j.tolist()):
        gx, gy = x // spacing, y // spacing
        ok = True
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                for px, py in grid.get((gx + ddx, gy + ddy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < s2:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                break
        if ok:
            grid.setdefault((gx, gy), []).append((x, y))
            out.append((x, y))
    return out


def lattice_nodes(free, comp, sizes, min_comp, step, existing, spacing):
    ny, nx = free.shape
    big = np.zeros(sizes.size + 1, dtype=bool)
    big[:-1] = sizes >= min_comp
    jj, ii = np.meshgrid(np.arange(step // 2, ny, step), np.arange(step // 2, nx, step), indexing="ij")
    ok = free[jj, ii] & big[comp[jj, ii]]
    return thin(ii[ok], jj[ok], spacing, existing)


def floyd(Wm):
    D = Wm.copy()
    for k in range(D.shape[0]):
        np.minimum(D, D[:, k:k + 1] + D[k:k + 1, :], out=D)
    return D


class Nav:
    def __init__(self, W, params=None, ds=0.5, ledge_margin=0.25):
        p = dict(nav_params())
        p.update(params or {})
        self.p = p
        self.W = W
        self.ds = ds
        nres, nx, ny, S, kind, slope_ok, lo2, hi2, k = build_surface(W, p)
        self.nres, self.nx, self.ny = nres, nx, ny
        self.x0, self.y0 = W.x0, W.y0
        self.S2 = S
        self.kind2 = kind
        self.free2 = build_free(W, p, nres, nx, ny, S, kind, slope_ok, lo2, hi2, k)
        self.comp2, self.comp_sizes = components(self.free2, S, p["step_up"])
        self.S = S.ravel()
        self.free = self.free2.ravel()
        self.comp = self.comp2.ravel()
        self.kind = kind.ravel()
        self.prism_surface = (self.kind > 0) & (self.kind != UNDER)
        self.ledge_margin = ledge_margin

    def cell(self, x, y):
        i = np.clip(((np.asarray(x, dtype=np.float64) - self.x0) / self.nres).astype(np.int64), 0, self.nx - 1)
        j = np.clip(((np.asarray(y, dtype=np.float64) - self.y0) / self.nres).astype(np.int64), 0, self.ny - 1)
        return j * self.nx + i

    def center(self, c):
        c = np.asarray(c)
        return np.stack([self.x0 + (c % self.nx + 0.5) * self.nres, self.y0 + (c // self.nx + 0.5) * self.nres], axis=-1)

    def walk_many(self, P, Q, both=False):
        P = np.asarray(P, dtype=np.float64).reshape(-1, 2)
        Q = np.asarray(Q, dtype=np.float64).reshape(-1, 2)
        D = Q - P
        L = np.sqrt((D * D).sum(1))
        m = np.ceil(L / self.ds).astype(np.int64) + 1
        starts = np.cumsum(m) - m
        n = int(starts[-1] + m[-1])
        k = (np.arange(n, dtype=np.int64) - np.repeat(starts, m)).astype(np.float64)
        inv = 1.0 / np.maximum(m - 1, 1)
        t = k * np.repeat(inv, m)
        x = np.repeat(P[:, 0], m) + t * np.repeat(D[:, 0], m)
        y = np.repeat(P[:, 1], m) + t * np.repeat(D[:, 1], m)
        c = self.cell(x, y)
        ok = np.logical_and.reduceat(self.free[c], starts)
        s = self.S[c]
        rise = np.empty(n, dtype=np.float32)
        rise[:-1] = s[1:] - s[:-1]
        rise[starts[1:] - 1] = 0.0
        rise[-1] = 0.0
        ledge = np.zeros(n, dtype=np.float32)
        pk = self.prism_surface[c]
        ledge[:-1] = (pk[1:] | pk[:-1]) * np.float32(self.ledge_margin)
        step = self.p["step_up"]
        fwd = ok & (np.maximum.reduceat(rise + ledge, starts) <= step)
        if not both:
            return fwd
        bwd = ok & (np.maximum.reduceat(ledge - rise, starts) <= step)
        return fwd, bwd

    def walk(self, a, b):
        return bool(self.walk_many([a[:2]], [b[:2]])[0])

    def snap(self, xy, r=4.0):
        c = int(self.cell(xy[0], xy[1]))
        if self.free[c]:
            return c
        i0, j0 = c % self.nx, c // self.nx
        k = int(math.ceil(r / self.nres))
        ii = np.arange(max(i0 - k, 0), min(i0 + k + 1, self.nx))
        jj = np.arange(max(j0 - k, 0), min(j0 + k + 1, self.ny))
        sub = self.free2[jj[0]:jj[-1] + 1, ii[0]:ii[-1] + 1]
        if not sub.any():
            return -1
        J, I = np.nonzero(sub)
        cx = self.x0 + (ii[I] + 0.5) * self.nres - xy[0]
        cy = self.y0 + (jj[J] + 0.5) * self.nres - xy[1]
        q = int(np.argmin(cx * cx + cy * cy))
        return int(jj[J[q]] * self.nx + ii[I[q]])

    def build_roadmap(self, min_comp=20000, frac_r=3, frac_max=0.35, spacing=8, lattice=40, max_edge=120.0,
                      probe=4, k_probe=8, rounds=4, opt_sources=32, opt_rounds=1, opt_tol=1.03, opt_per_source=3, log=None):
        pts = corner_nodes(self.free2, self.comp2, self.comp_sizes, min_comp, frac_r, frac_max, spacing)
        pts += lattice_nodes(self.free2, self.comp2, self.comp_sizes, min_comp, lattice, pts, lattice // 2)
        cells = np.array([y * self.nx + x for x, y in pts], dtype=np.int64)
        big = np.zeros(self.comp_sizes.size + 1, dtype=bool)
        big[:-1] = self.comp_sizes >= min_comp
        jj, ii = np.meshgrid(np.arange(probe // 2, self.ny, probe), np.arange(probe // 2, self.nx, probe), indexing="ij")
        pc = (jj * self.nx + ii).ravel()
        pc = pc[self.free[pc] & big[self.comp[pc]]]
        for r in range(rounds):
            miss = self.uncovered(cells, pc, k_probe)
            if log:
                log("round %d nodes %d uncovered %d" % (r, cells.size, miss.size))
            if miss.size == 0:
                break
            add = thin(miss % self.nx, miss // self.nx, probe * 2, [(int(c % self.nx), int(c // self.nx)) for c in cells])
            cells = np.concatenate([cells, np.array([y * self.nx + x for x, y in add], dtype=np.int64)])
        for r in range(rounds):
            Wm, D = self.graph(cells, max_edge)
            add = self.repair(cells, D)
            if log:
                log("repair %d nodes %d added %d" % (r, cells.size, len(add)))
            if not add:
                break
            cells = np.concatenate([cells, np.array(add, dtype=np.int64)])
        else:
            Wm, D = self.graph(cells, max_edge)
        rng = np.random.default_rng(0)
        for r in range(opt_rounds):
            add = self.optimality(cells, D, opt_sources, opt_tol, opt_per_source, rng)
            if log:
                log("optimality %d nodes %d added %d" % (r, cells.size, len(add)))
            if not add:
                break
            cells = np.concatenate([cells, np.array(add, dtype=np.int64)])
            Wm, D = self.graph(cells, max_edge)
        self.set_roadmap(cells, Wm, D)

    def grid_dijkstra(self, start):
        nx = self.nx
        free = self.free.tolist()
        S = self.S.tolist()
        step = self.p["step_up"]
        r2 = math.sqrt(2.0)
        offs = ((1, 1.0), (-1, 1.0), (nx, 1.0), (-nx, 1.0), (nx + 1, r2), (nx - 1, r2), (-nx + 1, r2), (-nx - 1, r2))
        n = len(free)
        dist = [math.inf] * n
        par = [-1] * n
        dist[start] = 0.0
        h = [(0.0, start)]
        pop, push = heapq.heappop, heapq.heappush
        while h:
            d, c = pop(h)
            if d > dist[c]:
                continue
            sc = S[c]
            for o, w in offs:
                m = c + o
                if 0 <= m < n and free[m] and S[m] - sc <= step:
                    nd = d + w
                    if nd < dist[m]:
                        dist[m] = nd
                        par[m] = c
                        push(h, (nd, m))
        return np.array(dist), par

    def optimality(self, cells, D, n_src, tol, per_source, rng):
        comp = self.comp[cells]
        src = rng.choice(cells.size, size=min(n_src, cells.size), replace=False)
        add = []
        have = set(cells.tolist())
        for u in src:
            dist, par = self.grid_dijkstra(int(cells[u]))
            g = dist[cells]
            same = (comp == comp[u]) & np.isfinite(g) & (g > 0) & np.isfinite(D[u])
            excess = np.full(g.size, -np.inf)
            excess[same] = D[u][same] - tol * g[same] - 1.0
            for t in np.argsort(-excess)[:per_source]:
                if not excess[t] > 0:
                    break
                path = []
                c = int(cells[t])
                while c != -1:
                    path.append(c)
                    c = par[c]
                for q in self.turning_points(path):
                    if q not in have:
                        have.add(q)
                        add.append(q)
        return add

    def graph(self, cells, max_edge):
        xy = self.center(cells)
        n = xy.shape[0]
        d = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
        iu, ju = np.nonzero(np.triu(d <= max_edge, 1))
        fwd, bwd = self.walk_chunks(xy[iu], xy[ju])
        Wm = np.full((n, n), np.inf, dtype=np.float32)
        np.fill_diagonal(Wm, 0.0)
        Wm[iu[fwd], ju[fwd]] = d[iu[fwd], ju[fwd]]
        Wm[ju[bwd], iu[bwd]] = d[ju[bwd], iu[bwd]]
        return Wm, floyd(Wm)

    def repair(self, cells, D):
        comp = self.comp[cells]
        add = []
        for c in np.unique(comp):
            idx = np.nonzero(comp == c)[0]
            sub = np.isfinite(D[np.ix_(idx, idx)])
            mutual = sub & sub.T
            hub = int(np.argmax(mutual.sum(1)))
            core = mutual[hub]
            if core.all():
                continue
            targets = set(cells[idx[core]].tolist())
            done = set()
            for u in idx[~core]:
                if int(cells[u]) in done:
                    continue
                path = self.grid_path(int(cells[u]), targets)
                if path is None:
                    continue
                done.update(path)
                add += self.turning_points(path)
        return sorted(set(add) - set(cells.tolist()))

    def grid_path(self, start, targets):
        nx = self.nx
        free = self.free
        S = self.S
        step = self.p["step_up"]
        prev = {start: -1}
        q = [start]
        h = 0
        offs = (1, -1, nx, -nx, nx + 1, nx - 1, -nx + 1, -nx - 1)
        while h < len(q):
            c = q[h]
            h += 1
            if c in targets:
                out = []
                while c != -1:
                    out.append(c)
                    c = prev[c]
                return out[::-1]
            sc = S[c]
            for o in offs:
                n = c + o
                if n in prev or n < 0 or n >= free.size or not free[n] or abs(S[n] - sc) > step:
                    continue
                prev[n] = c
                q.append(n)
        return None

    def turning_points(self, path):
        pts = self.center(np.array(path))
        out = []
        a = 0
        while a < len(path) - 1:
            hi = len(path) - 1
            ok_f, ok_b = self.walk_many(np.repeat(pts[a:a + 1], hi - a, axis=0), pts[a + 1:], both=True)
            good = np.nonzero(ok_f & ok_b)[0]
            b = a + 1 + (int(good.max()) if good.size else 0)
            if good.size == 0 or int(good.max()) == 0:
                b = a + 1
            out.append(path[b])
            a = b
        return out[:-1]

    def walk_chunks(self, P, Q, chunk=20000):
        fwd = np.zeros(P.shape[0], dtype=bool)
        bwd = np.zeros(P.shape[0], dtype=bool)
        for s in range(0, P.shape[0], chunk):
            f, b = self.walk_many(P[s:s + chunk], Q[s:s + chunk], both=True)
            fwd[s:s + chunk] = f
            bwd[s:s + chunk] = b
        return fwd, bwd

    def uncovered(self, cells, pc, k):
        nxy = self.center(cells)
        pxy = self.center(pc)
        ncomp = self.comp[cells]
        pcomp = self.comp[pc]
        ok = np.zeros(pc.size, dtype=bool)
        for s in range(0, pc.size, 2000):
            q = pxy[s:s + 2000]
            d2 = ((q[:, None, :] - nxy[None, :, :]) ** 2).sum(-1)
            d2[pcomp[s:s + 2000, None] != ncomp[None, :]] = np.inf
            kk = min(k, cells.size)
            near = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
            P = np.repeat(q, kk, axis=0)
            Q = nxy[near.ravel()]
            f, b = self.walk_many(P, Q, both=True)
            fin = np.isfinite(d2[np.arange(q.shape[0])[:, None], near]).ravel()
            ok[s:s + 2000] = ((f & fin).reshape(-1, kk).any(1)) & ((b & fin).reshape(-1, kk).any(1))
        return pc[~ok]

    def set_roadmap(self, cells, Wm, D):
        src, dst = np.nonzero(np.isfinite(Wm) & (Wm > 0))
        self.load_roadmap(cells, src, dst, D)

    def load_roadmap(self, cells, src, dst, D):
        order = np.lexsort((dst, src))
        src, dst = np.asarray(src)[order], np.asarray(dst)[order]
        self.node_cell = np.asarray(cells, dtype=np.int64)
        self.node_xy = self.center(self.node_cell)
        self.node_comp = self.comp[self.node_cell]
        self.D = np.asarray(D, dtype=np.float32)
        self.adj_ptr = np.searchsorted(src, np.arange(self.node_cell.size + 1))
        self.adj_dst = dst.astype(np.int64)
        self.adj_w = np.sqrt(((self.node_xy[src] - self.node_xy[dst]) ** 2).sum(1)).astype(np.float32)

    def roadmap_arrays(self):
        src = np.repeat(np.arange(self.node_cell.size), np.diff(self.adj_ptr))
        return self.node_cell, src, self.adj_dst, self.D

    def near_nodes(self, xy, k, radius):
        d2 = ((self.node_xy - np.asarray(xy, dtype=np.float64)[None, :2]) ** 2).sum(1)
        cand = np.nonzero(d2 <= radius * radius)[0]
        if cand.size > k:
            cand = cand[np.argpartition(d2[cand], k - 1)[:k]]
        return cand[np.argsort(d2[cand])]

    def attach(self, xy, outbound, k=20, radius=150.0):
        for kk, rr in ((k, radius), (4 * k, 3 * radius)):
            cand = self.near_nodes(xy, kk, rr)
            if cand.size == 0:
                continue
            P = np.repeat(np.asarray(xy, dtype=np.float64)[None, :2], cand.size, axis=0)
            ok = self.walk_many(P, self.node_xy[cand]) if outbound else self.walk_many(self.node_xy[cand], P)
            if ok.any():
                c = cand[ok]
                return c, np.sqrt(((self.node_xy[c] - P[ok]) ** 2).sum(1))
        return np.zeros(0, dtype=np.int64), np.zeros(0)

    def free_point(self, xy):
        c = self.snap(xy)
        if c < 0:
            return None
        if c == int(self.cell(xy[0], xy[1])):
            return np.array([float(xy[0]), float(xy[1])])
        return self.center(c)

    def node_route(self, u, t):
        out = [u]
        D = self.D
        while u != t:
            a, b = self.adj_ptr[u], self.adj_ptr[u + 1]
            nb = self.adj_dst[a:b]
            dn = D[nb, t]
            cost = np.where(dn < D[u, t], self.adj_w[a:b] + dn, np.inf)
            q = int(np.argmin(cost))
            if not np.isfinite(cost[q]):
                return None
            u = int(nb[q])
            out.append(u)
        return out

    def path(self, start, goal):
        s = self.free_point(start)
        g = self.free_point(goal)
        if s is None or g is None:
            return None
        if self.walk_many(s[None], g[None])[0]:
            return [g]
        if not hasattr(self, "D"):
            return None
        a, da = self.attach(s, True)
        b, db = self.attach(g, False)
        if a.size == 0 or b.size == 0:
            return None
        cost = da[:, None] + self.D[np.ix_(a, b)] + db[None, :]
        q = int(np.argmin(cost))
        if not np.isfinite(cost.flat[q]):
            return None
        u, t = a[q // b.size], b[q % b.size]
        route = self.node_route(int(u), int(t))
        if route is None:
            return None
        pts = np.concatenate([self.node_xy[route], g[None]], axis=0)
        return self.smooth(s, pts)

    def nearest_in_comp(self, xy, comp=0, radius=80.0):
        k = int(math.ceil(radius / self.nres))
        i0, j0 = int((xy[0] - self.x0) / self.nres), int((xy[1] - self.y0) / self.nres)
        ia, ib = max(i0 - k, 0), min(i0 + k + 1, self.nx)
        ja, jb = max(j0 - k, 0), min(j0 + k + 1, self.ny)
        J, I = np.nonzero(self.comp2[ja:jb, ia:ib] == comp)
        if J.size == 0:
            return None
        cx = self.x0 + (I + ia + 0.5) * self.nres
        cy = self.y0 + (J + ja + 0.5) * self.nres
        q = int(np.argmin((cx - xy[0]) ** 2 + (cy - xy[1]) ** 2))
        return np.array([cx[q], cy[q]])

    def smooth(self, s, pts):
        out = []
        cur = s
        i = 0
        while i < len(pts):
            rest = pts[i:]
            ok = self.walk_many(np.repeat(cur[None], len(rest), axis=0), rest)
            good = np.nonzero(ok)[0]
            j = i + (int(good.max()) if good.size else 0)
            out.append(pts[j])
            cur = pts[j]
            i = j + 1
        return out

    def dist_many(self, start, targets, k=6, radius=120.0):
        s = self.free_point(start)
        T = np.asarray(targets, dtype=np.float64).reshape(-1, 2)
        out = np.full(T.shape[0], np.inf)
        if s is None or T.shape[0] == 0:
            return out
        direct = self.walk_many(np.repeat(s[None], T.shape[0], axis=0), T)
        out[direct] = np.sqrt(((T[direct] - s) ** 2).sum(1))
        rest = np.nonzero(~direct)[0]
        if rest.size == 0 or not hasattr(self, "D"):
            return out
        a, da = self.attach(s, True)
        if a.size == 0:
            return out
        Tr = T[rest]
        d2 = ((Tr[:, None, :] - self.node_xy[None, :, :]) ** 2).sum(-1)
        kk = min(k, self.node_xy.shape[0])
        near = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
        dn = np.sqrt(np.take_along_axis(d2, near, 1))
        ok = self.walk_many(self.node_xy[near.ravel()], np.repeat(Tr, kk, axis=0)).reshape(-1, kk) & (dn <= radius)
        via = (da[:, None] + self.D[a][:, near.ravel()]).min(0).reshape(-1, kk)
        tot = np.where(ok, via + dn, np.inf).min(1)
        out[rest] = tot
        return out
