import math


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def dirv(yaw, pitch):
    c = math.cos(pitch)
    return (c * math.cos(yaw), c * math.sin(yaw), math.sin(pitch))


def yaw_pitch(dx, dy, dz):
    return math.atan2(dy, dx), math.atan2(dz, math.hypot(dx, dy))


def muzzle(me, height_key, yaw, pitch, lat):
    st = me["stats"]
    p = me["pos"]
    v = me["vel"]
    h = st[height_key] if height_key in st else st["height"] + 0.5
    d = dirv(yaw, pitch)
    off = st["radius"] + 0.5
    return (p[0] + v[0] * lat + d[0] * off, p[1] + v[1] * lat + d[1] * off, p[2] + h + d[2] * off)


def target_center(m, scale_per_cube=0.05):
    s = 1.0 + scale_per_cube * m.cubes
    return (m.pos[0], m.pos[1], m.pos[2] + 4.5 * s)


def lead(origin, tpos, tvel, speed, lat, use_lead=True):
    vx, vy, vz = (tvel[0], tvel[1], tvel[2]) if use_lead else (0.0, 0.0, 0.0)
    t = 0.0
    for _ in range(4):
        tt = t + lat
        dx = tpos[0] + vx * tt - origin[0]
        dy = tpos[1] + vy * tt - origin[1]
        dz = tpos[2] + vz * tt - origin[2]
        t = math.sqrt(dx * dx + dy * dy + dz * dz) / speed
    yw, pt = yaw_pitch(dx, dy, dz)
    return yw, pt, t


def mortar_pitch(d, h, v, g, high=False):
    v2 = v * v
    disc = v2 * v2 - g * (g * d * d + 2.0 * h * v2)
    if disc < 0 or d < 1e-3:
        return None
    r = math.sqrt(disc)
    th = math.atan((v2 + r) / (g * d)) if high else math.atan((v2 - r) / (g * d))
    return th


def mortar_solve(me, tpos, tvel, w, lat, high=False):
    v = w["speed"]
    g = w["gravity"]
    p = me["pos"]
    st = me["stats"]
    oz = p[0], p[1], p[2] + st["height"] + 0.5
    t = 0.0
    for _ in range(4):
        tx = tpos[0] + tvel[0] * (t + lat)
        ty = tpos[1] + tvel[1] * (t + lat)
        d = math.hypot(tx - oz[0], ty - oz[1]) - (st["radius"] + 0.5)
        h = tpos[2] - oz[2]
        th = mortar_pitch(max(d, 1.0), h, v, g, high)
        if th is None:
            return None
        t = max(d, 1.0) / (v * math.cos(th))
    return math.atan2(ty - oz[1], tx - oz[0]), th, t, (tx, ty, tpos[2])


def arc_points(me, yaw, pitch, w, t_end, n=12):
    v = w["speed"]
    g = w["gravity"]
    p = me["pos"]
    st = me["stats"]
    d = dirv(yaw, pitch)
    off = st["radius"] + 0.5
    o = (p[0] + d[0] * off, p[1] + d[1] * off, p[2] + st["height"] + 0.5 + d[2] * off)
    out = []
    for k in range(n + 1):
        tt = t_end * k / n
        out.append((o[0] + d[0] * v * tt, o[1] + d[1] * v * tt, o[2] + d[2] * v * tt - 0.5 * g * tt * tt))
    return out


def residual(me, want_yaw, want_pitch, dt=0.05):
    st = me["stats"]
    ey = abs(wrap(want_yaw - me["aim"][0]))
    ep = abs(want_pitch - me["aim"][1])
    return max(0.0, ey - st["turn_rate"] * dt), max(0.0, ep - st["pitch_rate"] * dt)


def on_target(me, want_yaw, want_pitch, dist, radius, tol):
    ey, ep = residual(me, want_yaw, want_pitch)
    lim = math.atan2(radius * tol, max(dist, 1.0))
    vlim = math.atan2(4.0 * tol, max(dist, 1.0))
    return ey <= lim and ep <= vlim
