import math
import time

import numpy as np

from .nav import shift


def ring_offsets(n_az, dists):
    a = np.arange(n_az) * (2 * math.pi / n_az)
    return np.array([[d * math.cos(t), d * math.sin(t)] for d in dists for t in a])


def build_exposure(W, nav, step=4, n_az=12, dists=(25.0, 60.0, 120.0), eye=8.0, center=4.5, top=9.0, near=45.0, log=None):
    jj, ii = np.meshgrid(np.arange(step // 2, nav.ny, step), np.arange(step // 2, nav.nx, step), indexing="ij")
    cells = (jj * nav.nx + ii).ravel()
    out = np.full(cells.size, 255, dtype=np.uint8)
    todo = np.nonzero(nav.free[cells])[0]
    offs = ring_offsets(n_az, dists)
    near_obs = np.sqrt((offs ** 2).sum(1)) <= near
    bx0, by0, bx1, by1 = W.bounds
    for s in range(0, todo.size, 1500):
        idx = todo[s:s + 1500]
        c = cells[idx]
        xy = nav.center(c)
        Sc = nav.S[c]
        obs = (xy[:, None, :] + offs[None, :, :]).reshape(-1, 2)
        valid = (obs[:, 0] > bx0) & (obs[:, 0] < bx1) & (obs[:, 1] > by0) & (obs[:, 1] < by1)
        oz = nav.S[nav.cell(obs[:, 0], obs[:, 1])] + eye
        A = np.c_[obs, oz]
        T = np.repeat(np.c_[xy, Sc], offs.shape[0], axis=0)
        isnear = np.tile(near_obs, idx.size)
        vis = np.zeros(A.shape[0], dtype=bool)
        for h in (top, center):
            Th = T + np.array([0.0, 0.0, h])
            pending = np.nonzero(valid & ~vis)[0]
            for flag in (True, False):
                q = pending[isnear[pending] == flag]
                if q.size:
                    vis[q] = W.los_many(A[q], Th[q], canopy=not flag)
        v = (vis & valid).reshape(idx.size, -1).sum(1)
        n = valid.reshape(idx.size, -1).sum(1)
        out[idx] = np.round(254.0 * v / np.maximum(n, 1)).astype(np.uint8)
        if log and (s // 1500) % 10 == 0:
            log("exposure %d/%d" % (s, todo.size))
    return out.reshape(jj.shape), step


def visible_from(W, threats, pts_xyz, heights=(9.0, 4.5), near=45.0):
    P = np.asarray(pts_xyz, dtype=np.float64).reshape(-1, 3)
    E = np.asarray(threats, dtype=np.float64).reshape(-1, 3)
    n, m = P.shape[0], E.shape[0]
    if n == 0 or m == 0:
        return np.zeros(n, dtype=np.int32)
    A = np.repeat(E, n, axis=0)
    B = np.tile(P, (m, 1))
    far = ((A[:, :2] - B[:, :2]) ** 2).sum(1) > near * near
    vis = np.zeros(A.shape[0], dtype=bool)
    for h in heights:
        q = np.nonzero(~vis)[0]
        if q.size == 0:
            break
        vis[q] = W.los_many(A[q], B[q] + np.array([0.0, 0.0, h]), canopy=far[q])
    return vis.reshape(m, n).sum(0).astype(np.int32)


def lattice_around(nav, xy, radius, step):
    k = int(math.ceil(radius / step))
    g = np.arange(-k, k + 1) * step
    gx, gy = np.meshgrid(g, g)
    m = gx * gx + gy * gy <= radius * radius
    P = np.c_[gx[m] + xy[0], gy[m] + xy[1]]
    c = nav.cell(P[:, 0], P[:, 1])
    ok = nav.free[c]
    c = np.unique(c[ok])
    return c


def cover(W, nav, me, threats, radius=40.0, step=2.0, batch=64, near=45.0, max_eval=384, budget_s=0.02):
    t0 = time.perf_counter()
    me = np.asarray(me, dtype=np.float64)[:2]
    cells = lattice_around(nav, me, radius, step)
    if cells.size == 0:
        return None
    xy = nav.center(cells)
    eu = np.sqrt(((xy - me) ** 2).sum(1))
    order = np.argsort(eu)[:max_eval]
    best = None
    least = None
    for s in range(0, order.size, batch):
        q = order[s:s + batch]
        if best is not None and eu[q[0]] >= best["dist"]:
            break
        if s > 0 and time.perf_counter() - t0 > budget_s:
            break
        P = np.c_[xy[q], nav.S[cells[q]]]
        seen = visible_from(W, threats, P, near=near)
        h = np.nonzero(seen == 0)[0]
        if h.size:
            d = nav.dist_many(me, xy[q[h]])
            k = int(np.argmin(d))
            if np.isfinite(d[k]) and (best is None or d[k] < best["dist"]):
                best = dict(xy=xy[q[h[k]]], z=float(nav.S[cells[q[h[k]]]]), dist=float(d[k]), seen=0)
        elif best is None:
            k = int(np.argmin(seen))
            if least is None or seen[k] < least["seen"]:
                d = float(nav.dist_many(me, xy[q[k]][None])[0])
                if np.isfinite(d):
                    least = dict(xy=xy[q[k]], z=float(nav.S[cells[q[k]]]), dist=d, seen=int(seen[k]))
    return best if best is not None else least


def safe_spots(W, nav, exposure, expo_step, center, radius, me=None, threats=(), margin=6.0, step=4.0,
               w_expo=1.0, w_height=0.01, w_dist=0.004, w_seen=0.5, limit=48, top=8, near=45.0):
    r = max(radius - margin, step)
    cells = lattice_around(nav, center, r, step)
    if cells.size == 0:
        return []
    main = nav.comp[cells] == 0 if me is None else nav.comp[cells] >= 0
    cells = cells[main]
    xy = nav.center(cells)
    S = nav.S[cells]
    i = np.clip((cells % nav.nx) // expo_step, 0, exposure.shape[1] - 1)
    j = np.clip((cells // nav.nx) // expo_step, 0, exposure.shape[0] - 1)
    ex = exposure[j, i].astype(np.float64) / 254.0
    score = w_expo * ex - w_height * (S - np.median(S))
    dist = np.zeros(cells.size)
    if me is not None:
        me = np.asarray(me, dtype=np.float64)[:2]
        pre = np.argsort(score + w_dist * np.sqrt(((xy - me) ** 2).sum(1)))[:limit]
        cells, xy, S, ex, score = cells[pre], xy[pre], S[pre], ex[pre], score[pre]
        dist = nav.dist_many(me, xy)
        score = score + w_dist * dist
    if len(threats):
        pre = np.argsort(score)[:limit]
        cells, xy, S, ex, score, dist = cells[pre], xy[pre], S[pre], ex[pre], score[pre], dist[pre]
        seen = visible_from(W, threats, np.c_[xy, S], near=near)
        score = score + w_seen * seen
    ok = np.isfinite(score)
    order = np.nonzero(ok)[0][np.argsort(score[ok])][:top]
    return [dict(xy=xy[k], z=float(S[k]), exposure=float(ex[k]), dist=float(dist[k]), score=float(score[k])) for k in order]


def jet_climb(config=None):
    m = (config or {}).get("mech", {})
    g = float(m.get("gravity", 22))
    acc = float(m.get("jet_accel", 34)) - g
    vmax = float(m.get("max_rise_speed", 10))
    v0 = float(m.get("jump_speed", 11))
    t = float(m.get("energy", 100)) / float(m.get("jet_drain", 15))
    if v0 >= vmax:
        return (v0 * v0 - vmax * vmax) / (2 * g) + vmax * t + vmax * vmax / (2 * g)
    ta = min((vmax - v0) / acc, t)
    v1 = v0 + acc * ta
    return v0 * ta + 0.5 * acc * ta * ta + v1 * (t - ta) + v1 * v1 / (2 * g)


def roofs(nav, config=None, min_cells=30, safety=0.85, reach=6.0):
    capacity = jet_climb(config)
    out = []
    comp = nav.comp2
    k = int(math.ceil(reach / nav.nres))
    offs = [(a, b) for a in range(-k, k + 1) for b in range(-k, k + 1) if (a * a + b * b) * nav.nres ** 2 <= reach * reach]
    for c in range(1, nav.comp_sizes.size):
        if nav.comp_sizes[c] < min_cells:
            break
        J, I = np.nonzero(comp == c)
        j0, j1 = max(J.min() - k, 0), min(J.max() + k + 1, nav.ny)
        i0, i1 = max(I.min() - k, 0), min(I.max() + k + 1, nav.nx)
        sub = comp[j0:j1, i0:i1]
        S = nav.S2[j0:j1, i0:i1]
        g = np.where(sub == 0, S, -np.inf)
        best = np.full(S.shape, -np.inf, dtype=np.float32)
        for a, b in offs:
            best = np.maximum(best, shift(g, a, b, -np.inf))
        roof = sub == c
        need = S[roof] - best[roof]
        climb = float(need.min()) if np.isfinite(need).any() else math.inf
        out.append(dict(comp=c, cells=int(nav.comp_sizes[c]), z=float(np.median(S[roof])),
                        kind=int(np.bincount(nav.kind2[j0:j1, i0:i1][roof]).argmax()),
                        xy=(float(nav.x0 + (I.mean() + 0.5) * nav.nres), float(nav.y0 + (J.mean() + 0.5) * nav.nres)),
                        climb=climb, jet_ok=climb <= safety * capacity))
    return out
