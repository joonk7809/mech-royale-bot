import math

import numpy as np


class Follower:
    def __init__(self, nav, replan_every=10, goal_tol=2.0, goal_frac=0.1, reach=1.5, blend=5.0, probe=3.0,
                 stuck_steps=8, stuck_dist=1.0, unstick_steps=6):
        self.nav = nav
        self.replan_every = replan_every
        self.goal_tol = goal_tol
        self.goal_frac = goal_frac
        self.reach = reach
        self.blend = blend
        self.probe = probe
        self.wps = None
        self.goal = None
        self.exit = None
        self.age = 0
        self.stuck_steps = stuck_steps
        self.stuck_dist = stuck_dist
        self.unstick_steps = unstick_steps
        self.trail = []
        self.unstick = 0
        self.side = 1.0

    def reset(self):
        self.wps = None
        self.goal = None
        self.exit = None

    def needs_plan(self, pos, goal):
        if self.goal is None:
            return True
        if self.age >= self.replan_every:
            return True
        moved = math.hypot(goal[0] - self.goal[0], goal[1] - self.goal[1])
        far = math.hypot(goal[0] - pos[0], goal[1] - pos[1])
        if moved > max(self.goal_tol, self.goal_frac * far):
            return True
        return bool(self.wps) and not self.nav.walk(pos, self.wps[0])

    def step(self, pos, goal):
        pos = np.asarray(pos[:2], dtype=np.float64)
        goal = np.asarray(goal[:2], dtype=np.float64)
        u = self.plan_step(pos, goal)
        self.trail.append(pos)
        if len(self.trail) > self.stuck_steps:
            self.trail.pop(0)
        if self.unstick > 0:
            self.unstick -= 1
            return unit(self.side * np.array([-u[1], u[0]]) * 0.7 + u * 0.3)
        if len(self.trail) == self.stuck_steps and np.hypot(*(pos - self.trail[0])) < self.stuck_dist and np.hypot(*(goal - pos)) > 3.0:
            self.unstick = self.unstick_steps
            self.side = -self.side
            self.trail = []
            self.age = self.replan_every
        return u

    def plan_step(self, pos, goal):
        if self.needs_plan(pos, goal):
            p = self.nav.path(pos, goal)
            self.wps = [np.asarray(w, dtype=np.float64) for w in p] if p else None
            self.exit = None
            if p is None:
                c = self.nav.comp[self.nav.cell(pos[0], pos[1])]
                gc = self.nav.comp[self.nav.cell(goal[0], goal[1])]
                if c != gc:
                    self.exit = self.nav.nearest_in_comp(pos, 0 if gc < 0 else gc)
            self.goal = goal
            self.age = 0
        self.age += 1
        if not self.wps:
            return unit((goal if self.exit is None else self.exit) - pos)
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
