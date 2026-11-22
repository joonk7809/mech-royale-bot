import importlib
import json
import os
import sys
import traceback

from bots.main import bot as main_bot

NAME = "main"
SQUAD = os.environ.get("MECH_DUAL_SQUAD", "duel")
V1_KW = {"main_v1ag": {"squad_press": True}}.get(SQUAD, {})
v1_bot = importlib.import_module(f"bots.{SQUAD}.bot")
v1_nav = importlib.import_module(f"bots.{SQUAD}.nav")

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
    def __init__(self, hello, seed_mode=None, main_kw=None, v1_kw=None, opening=None, **kw):
        self.open = opening or os.environ.get("MECH_DUAL_OPEN", "main")
        mode = seed_mode or os.environ.get("MECH_DUAL_SEED", "hello")
        if mode == "urandom":
            hello = dict(hello, seed=int.from_bytes(os.urandom(4), "little"))
        self.main = self.v1 = None
        try:
            self.main = main_bot.Bot(hello, **dict(kw, **(main_kw or {})))
        except Exception:
            _log()
        try:
            env = os.environ.get("MECH_DUAL_V1")
            self.v1 = v1_bot.Bot(hello, **dict(V1_KW, **(json.loads(env) if env else {}), **(v1_kw or {})))
        except Exception:
            _log()
        self.navkind = getattr(self.main, "navkind", None)
        self.use_v1 = False
        self.switches = []
        self.cap = int(os.environ.get("MECH_CAP_KILLS", "0"))
        self.idle_t = float(os.environ.get("MECH_IDLE_T", "0"))
        self.kills = 0
        self.assume_t = float(os.environ.get("MECH_DUAL_ASSUME", "0"))
        self.farm = self.open == "farm" and self.v1 is not None and "farm" in getattr(self.v1, "cfg", {})
        self.farm_until = float(os.environ.get("MECH_FARM_UNTIL", "40"))
        self.farm_r = float(os.environ.get("MECH_FARM_CONTACT", "90"))
        self.farm_wait = float(os.environ.get("MECH_FARM_WAIT", "4"))
        self.farm_on = False
        self.contact_t = -1e9
        if self.farm:
            self.v1_cfg = dict(self.v1.cfg)
            self.farm_cfg = dict(self.v1_cfg, farm=True, squad_press=False, finish_low=False, squad_avoid=False)

    def _farming(self, obs):
        t = obs.get("t", 0)
        if t >= self.farm_until or getattr(self.main, "squad", None) is True:
            self.farm = False
            return False
        x, y = obs["self"]["pos"][:2]
        if any(e.get("type") == "damaged" and e.get("by") is not None and e["by"] < 16 for e in obs.get("events") or []) or any(m.get("kind") == "mech" and (m["pos"][0] - x) ** 2 + (m["pos"][1] - y) ** 2 < self.farm_r ** 2 for m in obs.get("mechs") or []):
            self.contact_t = t
        return t - self.contact_t >= self.farm_wait

    def _set_farm(self, on):
        if on != self.farm_on:
            self.farm_on = on
            self.v1.cfg.clear()
            self.v1.cfg.update(self.farm_cfg if on else self.v1_cfg)

    def _call(self, b, obs):
        if b is None:
            return None
        try:
            return b.act(obs)
        except Exception:
            _log()
            return None

    def act(self, obs):
        self.kills += sum(1 for e in obs.get("events") or [] if e.get("type") == "kill")
        if (self.cap and self.kills >= self.cap) or (self.idle_t and obs.get("t", 0) >= self.idle_t):
            return {"tick": obs["tick"]}
        am = self._call(self.main, obs)
        if self.farm or self.farm_on:
            self._set_farm(self.farm and self._farming(obs))
        av = self._call(self.v1, obs)
        if self.farm_on and av is not None:
            return av
        st = getattr(self.main, "squad", None)
        sq = st is True or (st is None and (self.open == "v1" or (self.assume_t > 0 and obs.get("t", 0) >= self.assume_t)))
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
