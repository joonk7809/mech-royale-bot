import os
import time

from .cache import build, cache_key, load_into
from .follow import Follower
from .nav import Nav, nav_params
from .query import cover, jet_climb, roofs, safe_spots
from .world import World, find_map_dir


class Geo:
    def __init__(self, map_dir=None, config=None, build_if_missing=True, log=None):
        t0 = time.perf_counter()
        self.config = config or {}
        map_dir = find_map_dir(map_dir)
        self.params = nav_params(config)
        self.world = World(map_dir)
        self.nav = Nav(self.world, self.params)
        got = load_into(self.nav, cache_key(map_dir, self.params))
        if got is None and build_if_missing:
            self.nav.build_roadmap()
            from .query import build_exposure
            got = build_exposure(self.world, self.nav)
        self.exposure, self.expo_step = got if got is not None else (None, 4)
        self.cached = got is not None
        self.vision = self.config.get("vision", {})
        self.load_s = time.perf_counter() - t0
        if log:
            log("geo loaded in %.2fs" % self.load_s)

    def ground(self, x, y):
        return self.world.ground(x, y)

    def surface(self, x, y):
        return self.nav.S[self.nav.cell(x, y)]

    def los(self, a, b, canopy=True):
        return self.world.los(a, b, canopy)

    def los_many(self, A, B, canopy=True):
        return self.world.los_many(A, B, canopy)

    def shot_clear(self, a, b):
        return self.world.shot_clear(a, b)

    def shot_clear_many(self, A, B):
        return self.world.shot_clear_many(A, B)

    def walkable(self, xy):
        return bool(self.nav.free[self.nav.cell(xy[0], xy[1])])

    def walk(self, a, b):
        return self.nav.walk(a, b)

    def path(self, start, goal):
        return self.nav.path(start, goal)

    def dist_many(self, start, targets):
        return self.nav.dist_many(start, targets)

    def follower(self, **kw):
        return Follower(self.nav, **kw)

    def cover(self, me, threats, radius=40.0, **kw):
        return cover(self.world, self.nav, me, threats, radius=radius, near=self.vision.get("near_range", 45.0), **kw)

    def safe_spots(self, center, radius, me=None, threats=(), **kw):
        return safe_spots(self.world, self.nav, self.exposure, self.expo_step, center, radius, me=me, threats=threats,
                          near=self.vision.get("near_range", 45.0), **kw)

    def roofs(self):
        return roofs(self.nav, self.config)


def load(map_dir=None, config=None, log=None):
    return Geo(map_dir, config, log=log)


_SHARED = {}


def shared(map_dir=None, config=None, log=None):
    key = (os.path.abspath(find_map_dir(map_dir)), tuple(sorted(nav_params(config).items())))
    if key not in _SHARED:
        _SHARED[key] = Geo(map_dir, config, log=log)
    return _SHARED[key]
