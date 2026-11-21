import numpy as np

KIND_CODE = {"building": 1, "stadium": 2, "bridge": 3}


def ring_edges(flat):
    p = np.asarray(flat, dtype=np.float64).reshape(-1, 2)
    return np.concatenate([p, np.roll(p, -1, axis=0)], axis=1)


def prism_edges(prism):
    parts = [ring_edges(prism["ring"])]
    parts += [ring_edges(h) for h in prism.get("holes") or [] if len(h) >= 6]
    return np.concatenate(parts, axis=0)


def fill_edges(edges, x0, y0, res, nx, ny):
    xs = edges[:, [0, 2]]
    ys = edges[:, [1, 3]]
    c0 = max(int(np.floor((xs.min() - x0) / res)), 0)
    c1 = min(int(np.ceil((xs.max() - x0) / res)), nx - 1)
    r0 = max(int(np.floor((ys.min() - y0) / res)), 0)
    r1 = min(int(np.ceil((ys.max() - y0) / res)), ny - 1)
    if c1 < c0 or r1 < r0:
        return None
    w = c1 - c0 + 1
    h = r1 - r0 + 1
    counts = np.zeros((h, w + 1), dtype=np.int32)
    ya, yb = edges[:, 1], edges[:, 3]
    xa, xb = edges[:, 0], edges[:, 2]
    lo = np.minimum(ya, yb)
    hi = np.maximum(ya, yb)
    ja = np.maximum(np.ceil((lo - y0) / res - 0.5).astype(np.int64), r0)
    jb = np.minimum(np.ceil((hi - y0) / res - 0.5).astype(np.int64) - 1, r1)
    n = np.maximum(jb - ja + 1, 0)
    keep = n > 0
    if not keep.any():
        return None
    e = np.repeat(np.nonzero(keep)[0], n[keep])
    start = np.repeat(ja[keep], n[keep])
    offs = np.arange(e.size) - np.repeat(np.cumsum(n[keep]) - n[keep], n[keep])
    rows = start + offs
    yc = y0 + (rows + 0.5) * res
    xi = xa[e] + (yc - ya[e]) * (xb[e] - xa[e]) / (yb[e] - ya[e])
    k = np.clip(np.ceil((xi - x0) / res - 0.5).astype(np.int64), c0, c1 + 1) - c0
    np.add.at(counts, (rows - r0, k), 1)
    inside = (np.cumsum(counts[:, ::-1], axis=1)[:, ::-1][:, 1:] & 1).astype(bool)
    jj, ii = np.nonzero(inside)
    return (jj + r0) * nx + (ii + c0)


def rasterize_prisms(prisms, x0, y0, res, nx, ny):
    cells, base, top, kind = [], [], [], []
    for p in prisms:
        idx = fill_edges(prism_edges(p), x0, y0, res, nx, ny)
        if idx is None or idx.size == 0:
            continue
        cells.append(idx)
        base.append(np.full(idx.size, p["base"], dtype=np.float32))
        top.append(np.full(idx.size, p["top"], dtype=np.float32))
        kind.append(np.full(idx.size, KIND_CODE[p["kind"]], dtype=np.int8))
    return (np.concatenate(cells), np.concatenate(base), np.concatenate(top), np.concatenate(kind))


def merge_intervals(cells, base, top, kind, tol):
    order = np.lexsort((base, cells))
    c, b, t, k = cells[order], base[order].astype(np.float64), top[order].astype(np.float64), kind[order]
    newcell = np.ones(c.size, dtype=bool)
    newcell[1:] = c[1:] != c[:-1]
    g = np.cumsum(newcell) - 1
    big = 1.0e4
    runmax = np.maximum.accumulate(t + g * big) - g * big
    prevmax = np.empty_like(runmax)
    prevmax[0] = -np.inf
    prevmax[1:] = runmax[:-1]
    start = newcell | (b > prevmax + tol)
    m = np.cumsum(start) - 1
    si = np.nonzero(start)[0]
    mlo = b[si]
    mhi = np.maximum.reduceat(t, si)
    mcell = c[si]
    best = np.lexsort((t, m))
    last = np.ones(best.size, dtype=bool)
    last[:-1] = m[best][1:] != m[best][:-1]
    mkind = np.empty(si.size, dtype=np.int8)
    mkind[m[best][last]] = k[best][last]
    return mcell, mlo.astype(np.float32), mhi.astype(np.float32), mkind
