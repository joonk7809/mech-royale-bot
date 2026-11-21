import json
import math
import os

import numpy as np

from .raster import KIND_CODE, merge_intervals, rasterize_prisms

OPEN, BUILDING, STADIUM, BRIDGE = 0, KIND_CODE["building"], KIND_CODE["stadium"], KIND_CODE["bridge"]
HI_NONE = np.int16(-32768)
LO_NONE = np.int16(32767)


def find_map_dir(hint=None):
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (hint, "/arena", os.path.join(here, "..", "kit", "arena")):
        if d and os.path.exists(os.path.join(d, "v2", "world.json")):
            return d
    raise FileNotFoundError("v2/world.json not found")


class World:
    def __init__(self, map_dir=None, res=0.5, ground_tol=0.5, ds=0.5):
        map_dir = find_map_dir(map_dir)
        with open(os.path.join(map_dir, "v2", "world.json")) as f:
            w = json.load(f)
        self.prisms = w["prisms"]
        t = w["terrain"]
        self.tx0, self.ty0, self.tstep = float(t["minX"]), float(t["minY"]), float(t["step"])
        self.tnx, self.tny = int(t["nx"]), int(t["ny"])
        raw = np.fromfile(os.path.join(map_dir, "v2", t["file"]), dtype="<i2")
        self.terrain = (raw.reshape(self.tny, self.tnx).astype(np.float32) * np.float32(t.get("scale", 0.01)))
        b = w["bounds"]
        self.bounds = (float(b["minX"]), float(b["minY"]), float(b["maxX"]), float(b["maxY"]))
        self.rules = w["rules"]
        self.res = float(res)
        self.ds = float(ds)
        self.x0, self.y0 = self.tx0, self.ty0
        self.nx = int(round((self.tnx - 1) * self.tstep / res))
        self.ny = int(round((self.tny - 1) * self.tstep / res))
        self._build_solids(w["prisms"], ground_tol)
        self._build_trees(w["trees"])
        self._finish_aux()

    def ground(self, x, y):
        fx = (np.asarray(x, dtype=np.float64) - self.tx0) / self.tstep
        fy = (np.asarray(y, dtype=np.float64) - self.ty0) / self.tstep
        fx = np.clip(fx, 0.0, self.tnx - 1.000001)
        fy = np.clip(fy, 0.0, self.tny - 1.000001)
        i = fx.astype(np.int64)
        j = fy.astype(np.int64)
        u = fx - i
        v = fy - j
        T = self.terrain
        g = (T[j, i] * (1 - u) + T[j, i + 1] * u) * (1 - v) + (T[j + 1, i] * (1 - u) + T[j + 1, i + 1] * u) * v
        return float(g) if g.ndim == 0 else g

    def cell_index(self, x, y):
        i = np.clip(((np.asarray(x, dtype=np.float64) - self.x0) / self.res).astype(np.int64), 0, self.nx - 1)
        j = np.clip(((np.asarray(y, dtype=np.float64) - self.y0) / self.res).astype(np.int64), 0, self.ny - 1)
        return j * self.nx + i

    def cell_centers(self):
        xs = self.x0 + (np.arange(self.nx) + 0.5) * self.res
        ys = self.y0 + (np.arange(self.ny) + 0.5) * self.res
        return xs, ys

    def cell_ground(self):
        xs, ys = self.cell_centers()
        fx = np.clip((xs - self.tx0) / self.tstep, 0.0, self.tnx - 1.000001)
        fy = np.clip((ys - self.ty0) / self.tstep, 0.0, self.tny - 1.000001)
        i = fx.astype(np.int64)
        j = fy.astype(np.int64)
        u = (fx - i).astype(np.float32)
        v = (fy - j).astype(np.float32)[:, None]
        T = self.terrain
        rows = T[:, i] * (1 - u)
        rows += T[:, i + 1] * u
        out = rows[j]
        out *= 1 - v
        out += rows[j + 1] * v
        return out

    def _build_solids(self, prisms, ground_tol):
        nx, ny = self.nx, self.ny
        cells, base, top, kind = rasterize_prisms(prisms, self.x0, self.y0, self.res, nx, ny)
        mc, mlo, mhi, mk = merge_intervals(cells, base, top, kind, 0.25)
        first = np.ones(mc.size, dtype=bool)
        first[1:] = mc[1:] != mc[:-1]
        self.stacked_cells = int((~first).sum())
        if self.stacked_cells:
            si = np.nonzero(first)[0]
            last = np.r_[si[1:], mc.size] - 1
            mlo = np.minimum.reduceat(mlo, si)
            mhi = np.maximum.reduceat(mhi, si)
            mk = mk[last]
            mc = mc[si]
        g = np.round(self.cell_ground().ravel() * 100.0).astype(np.int16)
        self.lo = np.full(nx * ny, LO_NONE, dtype=np.int16)
        self.hi = np.full(nx * ny, HI_NONE, dtype=np.int16)
        self.kind = np.zeros(nx * ny, dtype=np.int8)
        self.lo[mc] = np.round(mlo * 100.0).astype(np.int16)
        self.hi[mc] = np.round(mhi * 100.0).astype(np.int16)
        self.kind[mc] = mk
        grounded = self.lo.astype(np.int32) <= g + int(round(ground_tol * 100))
        self.top = np.where(grounded, np.maximum(self.hi, g), g).astype(np.int16)
        over = (self.kind > 0) & ~grounded
        self.over_cells = np.nonzero(over)[0]
        self.olo = self.lo[self.over_cells]
        self.ohi = self.hi[self.over_cells]

    def _build_trees(self, trees):
        f = trees["fields"]
        d = np.asarray(trees["data"], dtype=np.float64).reshape(-1, len(f))
        col = {k: d[:, i] for i, k in enumerate(f)}
        tx, ty, tz = col["x"], col["y"], col["z"]
        cx = np.where(np.isnan(col["crownX"]), tx, col["crownX"]) if "crownX" in col else tx
        cy = np.where(np.isnan(col["crownY"]), ty, col["crownY"]) if "crownY" in col else ty
        self.tree_xy = np.stack([tx, ty], axis=1)
        self.tree_z0 = tz
        self.tree_z1 = tz + col["height"]
        self.tree_r = col["trunkR"]
        self.crown_xy = np.stack([cx, cy], axis=1)
        self.crown_r = col["crownR"]
        self.crown_z0 = tz + col["crownBase"]
        self.crown_z1 = tz + col["height"]
        res, nx, ny = self.res, self.nx, self.ny
        reach = np.sqrt(self.tree_r ** 2 + (self.ds * 0.5) ** 2) + res * math.sqrt(0.5)
        self.trunk_cell = np.full(nx * ny, -1, dtype=np.int16)
        for t in np.argsort(-self.tree_r):
            self._stamp_disk(self.trunk_cell, tx[t], ty[t], reach[t], t)
        clo = np.full(nx * ny, LO_NONE, dtype=np.int16)
        chi = np.full(nx * ny, HI_NONE, dtype=np.int16)
        xs, ys = self.cell_centers()
        zc = 0.5 * (self.crown_z0 + self.crown_z1)
        hz = 0.5 * (self.crown_z1 - self.crown_z0)
        pc, pt = [], []
        for t in range(len(tx)):
            R = self.crown_r[t]
            i0 = max(int((cx[t] - R - self.x0) / res), 0)
            i1 = min(int((cx[t] + R - self.x0) / res) + 1, nx - 1)
            j0 = max(int((cy[t] - R - self.y0) / res), 0)
            j1 = min(int((cy[t] + R - self.y0) / res) + 1, ny - 1)
            if i1 < i0 or j1 < j0:
                continue
            dx = xs[i0:i1 + 1][None, :] - cx[t]
            dy = ys[j0:j1 + 1][:, None] - cy[t]
            q = 1.0 - (dx * dx + dy * dy) / (R * R)
            m = q > 0
            h = hz[t] * np.sqrt(np.where(m, q, 0.0))
            blk = (np.arange(j0, j1 + 1)[:, None] * nx + np.arange(i0, i1 + 1)[None, :])[m]
            np.minimum.at(clo, blk, np.floor((zc[t] - h[m]) * 100.0).astype(np.int16))
            np.maximum.at(chi, blk, np.ceil((zc[t] + h[m]) * 100.0).astype(np.int16))
            pc.append(blk)
            pt.append(np.full(blk.size, t, dtype=np.int32))
        self.clo, self.chi = clo, chi
        pc = np.concatenate(pc)
        pt = np.concatenate(pt)
        order = np.argsort(pc, kind="stable")
        self.ccell = pc[order].astype(np.int32)
        self.ctree = pt[order]
        self.crown_zc = zc
        self.crown_hz = hz
        self.crown_box = np.stack([cx - self.crown_r, cx + self.crown_r, cy - self.crown_r, cy + self.crown_r], axis=1)
        self.canopy_band = 1.5
        dens = float(self.rules.get("canopyDensity", 0.35))
        blockT = float(self.rules.get("canopyBlockT", 0.25))
        self.canopy_len = math.log(1.0 / blockT) / dens

    def _stamp_disk(self, arr, x, y, r, val):
        res = self.res
        i0 = max(int(math.floor((x - r - self.x0) / res)), 0)
        i1 = min(int(math.floor((x + r - self.x0) / res)), self.nx - 1)
        j0 = max(int(math.floor((y - r - self.y0) / res)), 0)
        j1 = min(int(math.floor((y + r - self.y0) / res)), self.ny - 1)
        if i1 < i0 or j1 < j0:
            return
        ii = np.arange(i0, i1 + 1)
        jj = np.arange(j0, j1 + 1)
        dx = self.x0 + (ii + 0.5) * res - x
        dy = self.y0 + (jj + 0.5) * res - y
        m = dx[None, :] ** 2 + dy[:, None] ** 2 <= r * r
        view = arr.reshape(self.ny, self.nx)[j0:j1 + 1, i0:i1 + 1]
        view[m & (view < 0)] = val

    def _prep(self, A, B):
        A = np.asarray(A, dtype=np.float64).reshape(-1, 3).copy()
        B = np.asarray(B, dtype=np.float64).reshape(-1, 3).copy()
        lo_x, hi_x = self.x0 + 1e-3, self.x0 + self.nx * self.res - 1e-3
        lo_y, hi_y = self.y0 + 1e-3, self.y0 + self.ny * self.res - 1e-3
        for P in (A, B):
            np.clip(P[:, 0], lo_x, hi_x, out=P[:, 0])
            np.clip(P[:, 1], lo_y, hi_y, out=P[:, 1])
        return A, B

    def _samples(self, A, B):
        D = B - A
        L = np.sqrt((D * D).sum(1))
        m = np.maximum(np.ceil(L / self.ds).astype(np.int64), 1)
        starts = np.cumsum(m) - m
        n = int(starts[-1] + m[-1])
        inv = 1.0 / m
        r = 1.0 / self.res
        sx = D[:, 0] * r * inv
        sy = D[:, 1] * r * inv
        sz = D[:, 2] * inv * 100.0
        k = (np.arange(n, dtype=np.int32) - np.repeat(starts.astype(np.int32), m)).astype(np.float32)
        fx = np.repeat(((A[:, 0] - self.x0) * r + 0.5 * sx).astype(np.float32), m) + k * np.repeat(sx.astype(np.float32), m)
        fy = np.repeat(((A[:, 1] - self.y0) * r + 0.5 * sy).astype(np.float32), m) + k * np.repeat(sy.astype(np.float32), m)
        z = np.repeat((A[:, 2] * 100.0 + 0.5 * sz).astype(np.float32), m) + k * np.repeat(sz.astype(np.float32), m)
        c = fy.astype(np.int32) * np.int32(self.nx) + fx.astype(np.int32)
        return D, L, m, starts, z, c

    def _finish_aux(self):
        f = np.zeros(self.nx * self.ny, dtype=np.uint8)
        f[self.clo < LO_NONE] |= 1
        f[self.trunk_cell >= 0] |= 2
        f[self.over_cells] |= 4
        self.aux = f

    def _overhang(self, z, c, idx, seg, blocked):
        k = np.searchsorted(self.over_cells, c[idx])
        hit = (z[idx] >= self.olo[k]) & (z[idx] <= self.ohi[k])
        blocked[seg[hit]] = True

    def shot_clear_many(self, A, B):
        A, B = self._prep(A, B)
        D, L, m, starts, z, c = self._samples(A, B)
        blocked = np.logical_or.reduceat(z <= self.top[c], starts)
        if self.over_cells.size:
            h = np.nonzero(self.aux[c] & 4)[0]
            if h.size:
                self._overhang(z, c, h, np.searchsorted(starts, h, side="right") - 1, blocked)
        return ~blocked

    def los_many(self, A, B, canopy=True, trunks=True):
        if np.ndim(canopy) == 0:
            canopy = bool(canopy)
        A, B = self._prep(A, B)
        D, L, m, starts, z, c = self._samples(A, B)
        blocked = np.logical_or.reduceat(z <= self.top[c], starts)
        flags = self.aux[c]
        nz = np.nonzero(flags)[0]
        if nz.size == 0:
            return ~blocked
        fl = flags[nz]
        cz = c[nz]
        zz = z[nz]
        seg = np.searchsorted(starts, nz, side="right") - 1
        if self.over_cells.size:
            o = np.nonzero(fl & 4)[0]
            if o.size:
                self._overhang(zz, cz, o, seg[o], blocked)
        if canopy is not False:
            o = np.nonzero(fl & 1)[0]
            if canopy is not True:
                o = o[np.asarray(canopy, dtype=bool)[seg[o]]]
            if o.size:
                inside = (zz[o] >= self.clo[cz[o]]) & (zz[o] <= self.chi[cz[o]])
                est = np.bincount(seg[o][inside], minlength=blocked.size) * (L / m)
                amb = np.nonzero(~blocked & (np.abs(est - self.canopy_len) < self.canopy_band))[0]
                blocked |= est > self.canopy_len
                if amb.size:
                    isamb = np.zeros(blocked.size, dtype=bool)
                    isamb[amb] = True
                    sel = o[inside]
                    sel = sel[isamb[seg[sel]]]
                    exact = self._crown_len_cells(A, B, seg[sel], cz[sel], blocked.size)
                    blocked[amb] = exact[amb] > self.canopy_len
        if trunks:
            o = np.nonzero(fl & 2)[0]
            if o.size:
                pairs = np.unique(seg[o] * 4096 + self.trunk_cell[cz[o]])
                s = pairs // 4096
                tr = pairs % 4096
                hit = self._trunk_exact(A[s], D[s], tr)
                if hit.any():
                    blocked[s[hit]] = True
        return ~blocked

    def crown_len(self, A, B):
        A = np.asarray(A, dtype=np.float64).reshape(-1, 3)
        B = np.asarray(B, dtype=np.float64).reshape(-1, 3)
        lo = np.minimum(A, B)
        hi = np.maximum(A, B)
        cb = self.crown_box
        hit = (cb[None, :, 0] <= hi[:, None, 0]) & (cb[None, :, 1] >= lo[:, None, 0]) & (cb[None, :, 2] <= hi[:, None, 1]) & (cb[None, :, 3] >= lo[:, None, 1])
        s, t = np.nonzero(hit)
        return np.bincount(s, weights=self._ellipsoid_len(A[s], B[s], t), minlength=A.shape[0])

    def _crown_len_cells(self, A, B, segs, cells, n):
        a = np.searchsorted(self.ccell, cells, side="left")
        b = np.searchsorted(self.ccell, cells, side="right")
        cnt = b - a
        rep = np.repeat(np.arange(cells.size), cnt)
        pos = np.arange(rep.size) - np.repeat(np.cumsum(cnt) - cnt, cnt) + a[rep]
        pairs = np.unique(segs[rep].astype(np.int64) * 4096 + self.ctree[pos])
        s = pairs // 4096
        t = pairs % 4096
        L = self._ellipsoid_len(A[s], B[s], t)
        return np.bincount(s, weights=L, minlength=n)

    def _ellipsoid_len(self, A, B, t):
        R = self.crown_r[t]
        hz = self.crown_hz[t]
        d = B - A
        ox = (A[:, 0] - self.crown_xy[t, 0]) / R
        oy = (A[:, 1] - self.crown_xy[t, 1]) / R
        oz = (A[:, 2] - self.crown_zc[t]) / hz
        vx = d[:, 0] / R
        vy = d[:, 1] / R
        vz = d[:, 2] / hz
        a = vx * vx + vy * vy + vz * vz
        b = 2 * (ox * vx + oy * vy + oz * vz)
        c = ox * ox + oy * oy + oz * oz - 1
        disc = b * b - 4 * a * c
        ok = (disc > 0) & (a > 0)
        sq = np.sqrt(np.where(ok, disc, 0.0))
        a2 = np.where(ok, 2 * a, 1.0)
        t0 = np.clip((-b - sq) / a2, 0.0, 1.0)
        t1 = np.clip((-b + sq) / a2, 0.0, 1.0)
        return np.where(ok, t1 - t0, 0.0) * np.sqrt((d * d).sum(1))

    def _trunk_exact(self, A, D, tr):
        p = self.tree_xy[tr]
        d2 = D[:, 0] ** 2 + D[:, 1] ** 2
        u = np.clip(((p[:, 0] - A[:, 0]) * D[:, 0] + (p[:, 1] - A[:, 1]) * D[:, 1]) / np.maximum(d2, 1e-12), 0.0, 1.0)
        qx = A[:, 0] + D[:, 0] * u - p[:, 0]
        qy = A[:, 1] + D[:, 1] * u - p[:, 1]
        r = self.tree_r[tr]
        inside = qx * qx + qy * qy < r * r
        half = np.sqrt(np.maximum(r * r - (qx * qx + qy * qy), 0.0) / np.maximum(d2, 1e-12))
        za = A[:, 2] + D[:, 2] * np.clip(u - half, 0.0, 1.0)
        zb = A[:, 2] + D[:, 2] * np.clip(u + half, 0.0, 1.0)
        zlo = np.minimum(za, zb)
        zhi = np.maximum(za, zb)
        return inside & (zhi >= self.tree_z0[tr]) & (zlo <= self.tree_z1[tr])

    def los(self, a, b, canopy=True, trunks=True):
        return bool(self.los_many([a], [b], canopy, trunks)[0])

    def shot_clear(self, a, b):
        return bool(self.shot_clear_many([a], [b])[0])
