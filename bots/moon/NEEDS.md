# Requests from bots/main to geo/

Names bots/main/nav.py already uses (local fallback implements the same):
- World.load(map_dir) -> World, under 3 s.
- W.ground(x, y) -> float, W.walkable((x, y)) -> bool.
- W.los(a, b) and W.los_many(A, B) -> bool array, points [x, y, z] with eye z explicit.
- W.line_clear(a_xy, b_xy) -> bool: can a 2.5 m radius mech walk the straight segment (no rise above step_up). Used for strafing wall checks and waypoint skipping. Missing in geo: bot falls back to walkable() sampling.
- W.cover(me_xy, threats_xyz, radius) -> xy or None: nearest reachable point with no LOS from any threat eye to my body center (z+4.5) and head (z+8).
- Follower(W).step(pos_xy, goal_xy) -> [dx, dy]; please expose `stuck_t` (seconds) or a `replan()` so the bot can force a replan after it detects being stuck.
- Optional: W.surface(x, y) -> walkable top (roof or ground), used to predict mortar shell impact.
- Optional: W.roof_access(xy) -> (roof_xy, height) nearest roof a jet can reach with given energy.
