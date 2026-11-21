import hashlib
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from geo.nav import Nav, nav_params
from geo.world import World, find_map_dir

VERSION = 6
CACHE_DIR = os.path.join(HERE, "cache")
INF16 = 65535


def map_digest(map_dir):
    h = hashlib.sha1()
    for f in ("world.json", "terrain.i16"):
        with open(os.path.join(map_dir, "v2", f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def cache_key(map_dir, params):
    return "%s:%d:%s" % (map_digest(map_dir), VERSION, json.dumps(params, sort_keys=True))


def cache_path(key):
    return os.path.join(CACHE_DIR, "nav_%s.npz" % hashlib.sha1(key.encode()).hexdigest()[:12])


def save(nav, key, exposure, expo_step):
    cells, src, dst, D = nav.roadmap_arrays()
    Dq = np.where(np.isfinite(D), np.minimum(np.round(D * 10.0), INF16 - 1), INF16).astype(np.uint16)
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = cache_path(key)
    np.savez_compressed(path, key=np.array(key), node_cell=cells.astype(np.int32), src=src.astype(np.int16),
                        dst=dst.astype(np.int16), D=Dq, exposure=exposure, expo_step=np.array(expo_step))
    return path


def load_into(nav, key):
    path = cache_path(key)
    if not os.path.exists(path):
        return None
    z = np.load(path)
    if str(z["key"]) != key:
        return None
    Dq = z["D"]
    D = np.where(Dq == INF16, np.inf, Dq.astype(np.float32) * 0.1).astype(np.float32)
    nav.load_roadmap(z["node_cell"].astype(np.int64), z["src"].astype(np.int64), z["dst"].astype(np.int64), D)
    return z["exposure"], int(z["expo_step"])


def build(map_dir=None, config=None, log=print):
    from geo.query import build_exposure
    map_dir = find_map_dir(map_dir)
    params = nav_params(config)
    t0 = time.perf_counter()
    W = World(map_dir)
    nav = Nav(W, params)
    log("world+grid %.2fs" % (time.perf_counter() - t0))
    nav.build_roadmap(log=log)
    log("roadmap %.2fs nodes %d" % (time.perf_counter() - t0, nav.node_cell.size))
    exposure, step = build_exposure(W, nav, log=log)
    log("exposure %.2fs" % (time.perf_counter() - t0))
    path = save(nav, cache_key(map_dir, params), exposure, step)
    log("saved %s %d bytes" % (path, os.path.getsize(path)))
    return path


if __name__ == "__main__":
    md = sys.argv[1] if len(sys.argv) > 1 else None
    cfg = None
    if len(sys.argv) > 2:
        import gzip
        with gzip.open(sys.argv[2], "rt") as f:
            cfg = json.loads(f.readline())["config"]
    build(md, cfg)
