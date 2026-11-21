import math

import numpy as np


class Follower:
    def __init__(self, nav, replan_every=10, goal_tol=2.0, goal_frac=0.1, reach=1.5, blend=5.0, probe=3.0):
        self.nav = nav
        self.replan_every = replan_every
        self.goal_tol = goal_tol
        self.goal_frac = goal_frac
        self.reach = reach
        self.blend = blend
        self.probe = probe
        self.wps = None
        self.goal = None
        self.age = 0

    def reset(self):
        self.wps = None
        self.goal = None

    def needs_plan(self, pos, goal):
        if self.wps is None or self.goal is None:
            return True
        if self.age >= self.replan_every:
            return True
        moved = math.hypot(goal[0] - self.goal[0], goal[1] - self.goal[1])
        far = math.hypot(goal[0] - pos[0], goal[1] - pos[1])
        if moved > max(self.goal_tol, self.goal_frac * far):
            return True
        return not self.wps or not self.nav.walk(pos, self.wps[0])

    def step(self, pos, goal):
        pos = np.asarray(pos[:2], dtype=np.float64)
        goal = np.asarray(goal[:2], dtype=np.float64)
        if self.needs_plan(pos, goal):
            p = self.nav.path(pos, goal)
            self.wps = [np.asarray(w, dtype=np.float64) for w in p] if p else None
            self.goal = goal
            self.age = 0
        self.age += 1
        if not self.wps:
            return unit(goal - pos)
        while len(self.wps) > 1 and (np.hypot(*(self.wps[0] - pos)) < self.reach or self.nav.walk(pos, self.wps[1])):
            self.wps.pop(0)
        d0 = self.wps[0] - pos
        r0 = float(np.hypot(*d0))
        u = unit(d0)
        if len(self.wps) > 1 and r0 < self.blend:
            w = 1.0 - r0 / self.blend
            v = unit((1.0 - w) * u + w * unit(self.wps[1] - self.wps[0]))
            if self.nav.walk(pos, pos + v * self.probe):
                u = v
        return u


def unit(v):
    n = float(np.hypot(v[0], v[1]))
    if n < 1e-9:
        return np.zeros(2)
    return np.asarray(v, dtype=np.float64) / n
