import os
import sys
import traceback

from bots.main import bot as main_bot
from bots.main_v1 import bot as v1_bot
from bots.main_v1 import nav as v1_nav

NAME = "main"

_v1_load = v1_nav.load
_V1_LOCAL = {}


def _shared_load(map_dir, mode="auto", config=None):
    if mode not in ("auto", "geo"):
        return _v1_load(map_dir, mode, config)
    try:
        import geo
        G = geo.shared(map_dir=map_dir, config=config)
        key = os.path.abspath(map_dir)
        if key not in _V1_LOCAL:
            _V1_LOCAL[key] = v1_nav.World(map_dir)
        return v1_nav.GeoNav(G, _V1_LOCAL[key]), v1_nav.GeoFollower(G.follower()), "geo"
    except Exception:
        return _v1_load(map_dir, mode, config)


v1_nav.load = _shared_load


def _log():
    print(traceback.format_exc(), file=sys.stderr, flush=True)


class Bot:
    def __init__(self, hello, seed_mode=None, main_kw=None, v1_kw=None, **kw):
        mode = seed_mode or os.environ.get("MECH_DUAL_SEED", "hello")
        if mode == "urandom":
            hello = dict(hello, seed=int.from_bytes(os.urandom(4), "little"))
        self.main = self.v1 = None
        try:
            self.main = main_bot.Bot(hello, **dict(kw, **(main_kw or {})))
        except Exception:
            _log()
        try:
            self.v1 = v1_bot.Bot(hello, **(v1_kw or {}))
        except Exception:
            _log()
        self.navkind = getattr(self.main, "navkind", None)
        self.use_v1 = False
        self.switches = []

    def _call(self, b, obs):
        if b is None:
            return None
        try:
            return b.act(obs)
        except Exception:
            _log()
            return None

    def act(self, obs):
        am = self._call(self.main, obs)
        av = self._call(self.v1, obs)
        sq = getattr(self.main, "squad", None) is True
        if sq != self.use_v1:
            self.use_v1 = sq
            self.switches.append((obs.get("t"), sq))
        a = (av or am) if self.use_v1 else (am or av)
        return a if a is not None else {"tick": obs["tick"]}

    def end(self, msg):
        for b in (self.main, self.v1):
            try:
                if b is not None and hasattr(b, "end"):
                    b.end(msg)
            except Exception:
                _log()
