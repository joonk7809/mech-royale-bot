import math

from .aim import wrap


def _perp_away(ux, uy, mx, my, fallback):
    n = math.hypot(ux, uy)
    if n < 1e-6:
        return None
    px, py = -uy / n, ux / n
    s = px * mx + py * my
    if abs(s) < 0.3:
        s = fallback
    return (px, py) if s > 0 else (-px, -py)


def projectile_dodge(me, projectiles, W, mortar_w, side):
    st = me["stats"]
    R = st["radius"]
    Hh = st["height"]
    p = me["pos"]
    v = me["vel"]
    cx, cy, cz = p[0], p[1], p[2] + Hh * 0.5
    ax = ay = 0.0
    urg = 0.0
    for pr in projectiles:
        b = pr["pos"]
        u = pr["vel"]
        if pr["kind"] == "mortar":
            g = mortar_w["gravity"]
            x, y, z = b
            vx, vy, vz = u
            ti = None
            for k in range(1, 90):
                tt = k * 0.05
                zz = z + vz * tt - 0.5 * g * tt * tt
                xx = x + vx * tt
                yy = y + vy * tt
                if zz < W.surface(xx, yy) + 0.3:
                    ti = tt
                    break
            if ti is None:
                continue
            ix, iy = x + vx * ti, y + vy * ti
            fx, fy = cx + v[0] * ti, cy + v[1] * ti
            d = math.hypot(fx - ix, fy - iy)
            lim = mortar_w["splash_radius"] + R + 3.0
            if d < lim:
                dx, dy = fx - ix, fy - iy
                n = math.hypot(dx, dy)
                if n < 0.5:
                    dx, dy, n = -vy, vx, math.hypot(vx, vy) or 1.0
                w = (lim - d) / lim / (ti + 0.3)
                ax += dx / n * w
                ay += dy / n * w
                urg = max(urg, w)
            continue
        rx, ry, rz = b[0] - cx, b[1] - cy, b[2] - cz
        ux, uy, uz = u[0] - v[0], u[1] - v[1], u[2] - v[2]
        uu = ux * ux + uy * uy + uz * uz
        if uu < 1.0:
            continue
        ts = -(rx * ux + ry * uy + rz * uz) / uu
        if ts < 0.0 or ts > 1.2:
            continue
        mx, my, mz = rx + ux * ts, ry + uy * ts, rz + uz * ts
        if abs(mz) > Hh * 0.5 + 1.0:
            continue
        mh = math.hypot(mx, my)
        if mh > R + 1.2:
            continue
        d = _perp_away(u[0], u[1], -mx, -my, side)
        if d is None:
            continue
        w = 1.0 / (ts + 0.15)
        ax += d[0] * w
        ay += d[1] * w
        urg = max(urg, w)
    n = math.hypot(ax, ay)
    if n < 1e-6:
        return None, 0.0
    return (ax / n, ay / n), urg


def laser_danger(me, enemies, t, W, laser_cfg, tol_deg=6.0):
    p = me["pos"]
    R = me["stats"]["radius"]
    eye = (p[0], p[1], p[2] + me["stats"]["height"] * 0.5)
    worst = None
    for m in enemies:
        if not m.charging or t - m.seen > 0.15:
            continue
        dx, dy = p[0] - m.pos[0], p[1] - m.pos[1]
        d = math.hypot(dx, dy)
        if d > laser_cfg["range"] + 10:
            continue
        err = abs(wrap(math.atan2(dy, dx) - m.aim[0]))
        if err > math.atan2(R, d) + math.radians(tol_deg):
            continue
        if not W.los((m.pos[0], m.pos[1], m.pos[2] + 7.0), eye):
            continue
        left = laser_cfg["charge"] - (t - m.charge_t0 if m.charge_t0 is not None else 0.0)
        if worst is None or left < worst[1]:
            worst = (m, left, d)
    return worst
