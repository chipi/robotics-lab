"""A run's picks and approach against the true hole (challenge 22's rim, docs/wip/CH22-RIM.md): each pick's target in the
world (the belief frame moved by the run's epoch), its distance to the hole's outline, whether the pick's grid had a drop
point within AVOID_M of it, and the truth path's last stretch before the judge's nearest approach (position, heading
against the direction to the hole's nearest point).

    .venv/bin/python sim/probes/rim_approach.py CHALLENGE SEED RUN_DIR [RUN_DIR ...]
"""

import json
import math
import sys
from pathlib import Path

from duck_lab.nav import explore
from duck_lab.nav.explore import rim_unseen
from duck_lab.nav.frames import compose, inverse
from labrunner import challenges
from labrunner.geometry import footprint_distance


def hole_geoms(scene):
    return [{"name": f.name, "type": "box", "pos": [f.cx, f.cy, 0.0], "size": [f.hx, f.hy, 0.1], "yaw": f.yaw} for f in scene.drops()]


def nearest_on_hole(p, f):
    c, s = math.cos(-f.yaw), math.sin(-f.yaw)
    dx, dy = p[0] - f.cx, p[1] - f.cy
    lx, ly = c * dx - s * dy, s * dx + c * dy
    qx, qy = max(-f.hx, min(f.hx, lx)), max(-f.hy, min(f.hy, ly))
    c, s = math.cos(f.yaw), math.sin(f.yaw)
    return (f.cx + c * qx - s * qy, f.cy + s * qx + c * qy)


def main() -> None:
    challenge, seed, runs = sys.argv[1], int(sys.argv[2]), [Path(a) for a in sys.argv[3:]]
    scene = challenges.build(challenge, seed)
    holes = scene.drops()
    geoms = hole_geoms(scene)
    print("hole(s):", [(f.cx, f.cy, f.hx, f.hy, round(f.yaw, 3)) for f in holes])

    def hole_d(p):
        return min(footprint_distance(p, g) for g in geoms)

    for run in runs:
        start = json.loads((run / "start.json").read_text())
        w_from_m = compose(tuple(start["truth"]), inverse(tuple(start["map"])))
        rows = [json.loads(line) for line in (run / "ticks.jsonl").read_text().splitlines() if line.strip()]
        truth = [json.loads(line) for line in (run / "truth.jsonl").read_text().splitlines() if line.strip()]
        t0 = truth[0]["wall_ns"]
        res = json.loads((run / "result.json").read_text())
        print(f"\n== {run.name}  pass {res['pass']}  min_drop {res['min_drop_m']}  {res['failed']}")
        worst = min(truth, key=lambda r: hole_d(r["pose"][:2]))
        tw = (worst["wall_ns"] - t0) / 1e9
        print(f"nearest approach at truth t {tw:.1f} s, pose {worst['pose']}, {hole_d(worst['pose'][:2]):.3f} m from the hole")
        for r in rows:
            if r.get("event") not in ("pick", "leg") or "wall_ns" not in r:
                continue
            t = (r["wall_ns"] - t0) / 1e9
            if r["event"] == "pick":
                if not r.get("target"):
                    continue
                w = compose(w_from_m, (r["target"][0], r["target"][1], 0.0))[:2]
                pw = compose(w_from_m, (r["pose"][0], r["pose"][1], r["pose"][2]))
                g = r["grid"]
                near_avoid = min((math.dist(r["target"], a) for a in r["avoid"]), default=math.inf)
                clusters = explore.frontiers(g, 1.0, obstacles=[tuple(p) for p in r["obstacles"]])
                m_from_w = inverse(w_from_m)

                def seen_at(q):
                    wq = compose(w_from_m, (q[0], q[1], 0.0))
                    return not any(footprint_distance(wq[:2], gm) < 1e-9 for gm in geoms)

                share = rim_unseen(g, tuple(r["target"]), seen_at)
                after = explore.pick(clusters, tuple(r["pose"]), [tuple(a) for a in r["avoid"]],
                                     ok=lambda goal: rim_unseen(g, goal, seen_at) < explore.RIM_UNSEEN)
                again = f"{compose(w_from_m, (after[0], after[1], 0.0))[0]:.2f},{compose(w_from_m, (after[0], after[1], 0.0))[1]:.2f}" if after else "none"
                print(f"  pick t {t:6.1f}: target world ({w[0]:.2f}, {w[1]:.2f}) {hole_d(w):.2f} m from the hole; from pose "
                      f"({pw[0]:.2f}, {pw[1]:.2f}) {hole_d(pw[:2]):.2f} m; nearest avoided {near_avoid:.2f} m of {len(r['avoid'])}; "
                      f"{len(clusters)} clusters; rim share {share:.2f} (oracle: the true hole is unseen), rim rule picks world {again}")
            else:
                print(f"  leg  t {t:6.1f}: n {r['n']} {r['status']} {r.get('why')}")
        print("  truth path before the nearest approach (every 1 s): t, x, y, yaw, dist to hole, heading to the hole's nearest point")
        for r in truth:
            t = (r["wall_ns"] - t0) / 1e9
            if tw - 12 <= t <= tw + 1 and abs(t - round(t)) < 0.03:
                p = r["pose"]
                q = min((nearest_on_hole(p[:2], f) for f in holes), key=lambda q: math.dist(p[:2], q))
                bearing = math.atan2(q[1] - p[1], q[0] - p[0])
                rel = math.degrees(math.remainder(bearing - p[2], math.tau))
                print(f"    {t:6.1f}  ({p[0]:.2f}, {p[1]:.2f}) yaw {math.degrees(p[2]):5.0f}  {hole_d(p[:2]):.3f} m  hole at {rel:+.0f} deg from the nose")


if __name__ == "__main__":
    main()
