"""Replay the explorer's target choice on recorded runs, offline (stream A, EXPLORE-PROGRESS.md): for each leg, the
navigator's world grid at the leg's start (the last "world" event before it, already scaled), the belief pose then, and
the targets that failed before it; explore.frontiers + explore.pick choose a target, compared with the one the run took.
Then the chosen target's distance, in the world, to the nearest wall or object of the layout (the truth), so a change to
the choice can be judged on recordings: how many targets land in or next to something real.

    .venv/bin/python sim/probes/frontier_replay.py runs/explore-b1-r1 runs/explore-b1-r2 runs/explore-b1-r3

Not replayed: the navigator's reachable() check (lethal cells of its cost grid, floor the depth sensor saw), which needs
state the ticks do not carry; a target the replay picks may be one the run's check refused, so "same" is approximate.
"""

import json
import math
import sys
from pathlib import Path

import legacy_rows

from duck_lab.nav import explore
from labrunner import geometry
from labrunner.geometry import footprint_distance

LAYOUT = geometry.layout_path()
from duck_lab.nav.frames import compose, inverse

NEAR_M = 0.15
layout = json.loads(LAYOUT.read_text())
geoms = [g for g in layout["geoms"] if not g["name"].startswith(("floor", "rug")) and g["type"] != "plane"]


def nearest(wp):
    return min((footprint_distance(wp, g), g["name"]) for g in geoms)


def lethal_free(grid):
    w, res, (ox, oy) = grid["width"], grid["res_m"], grid["origin"]

    def ok(goal):
        cx, cy = int((goal[0] - ox) // res), int((goal[1] - oy) // res)
        return 0 <= cx < w and 0 <= cy < grid["height"] and grid["cells"][cy * w + cx] == "."
    return ok


def replay(run: Path, pick=explore.pick, frontiers=explore.frontiers) -> list:
    start, log = legacy_rows.load(run)
    w_from_m = compose(tuple(start["truth"]), inverse(tuple(start["map"])))
    s = start["scale"]
    world, pose, failed, out = None, None, [], []
    for r in log:
        ev = r.get("event")
        if ev == "world":
            world = r["grid"]
        elif "event" not in r and r.get("pose"):
            pose = r["pose"]
        if ev != "leg":
            continue
        if world is not None and pose is not None:
            got = pick(frontiers(world, 1.0), pose, failed, ok=lethal_free(world))
            rec = tuple(r["target"])
            w_rec = compose(w_from_m, (rec[0] * s, rec[1] * s, 0.0))[:2]
            w_got = compose(w_from_m, (got[0] * s, got[1] * s, 0.0))[:2] if got else None
            out.append({"leg": r["n"], "status": r["status"], "recorded": rec,
                        "replayed": tuple(round(v, 2) for v in got) if got else None,
                        "same": got is not None and math.dist(got, rec) < 0.15,
                        "rec_near": nearest(w_rec), "got_near": nearest(w_got) if w_got else None})
        if r["status"] != "reached":
            failed.append(tuple(r["target"]))
    return out


def replay_picks(run: Path, pick=explore.pick, frontiers=explore.frontiers) -> list:
    """From the pick events (runs from b2 on): the exact grid, pose, avoid list and obstacle points the run's choice used.
    The navigator's ok() is not recorded; its verdict is approximated by the grid's own free cells."""
    start, log = legacy_rows.load(run)
    w_from_m = compose(tuple(start["truth"]), inverse(tuple(start["map"])))
    s = start["scale"]
    out = []
    for r in log:
        if r.get("event") != "pick" or not r.get("target"):
            continue
        g = r["grid"]
        scaled = dict(g, res_m=g["res_m"] * r["scale"], origin=[g["origin"][0] * r["scale"], g["origin"][1] * r["scale"]])
        got = pick(frontiers(g, r["scale"], obstacles=[tuple(p) for p in r["obstacles"]]), tuple(r["pose"]),
                   [tuple(a) for a in r["avoid"]], ok=lethal_free(scaled))
        rec = tuple(r["target"])
        w_rec = compose(w_from_m, (rec[0] * s, rec[1] * s, 0.0))[:2]
        w_got = compose(w_from_m, (got[0] * s, got[1] * s, 0.0))[:2] if got else None
        out.append({"leg": f"t{r['t']}", "status": "pick", "recorded": rec,
                    "replayed": tuple(round(v, 2) for v in got) if got else None,
                    "same": got is not None and math.dist(got, rec) < 0.05,
                    "rec_near": nearest(w_rec), "got_near": nearest(w_got) if w_got else None})
    return out


def report(runs, **kw) -> tuple:
    same = total = rec_bad = got_bad = 0
    for run in runs:
        has_picks = any(r.get("event") == "pick" for r in legacy_rows.load(run)[1])
        for o in (replay_picks if has_picks else replay)(run, **kw):
            total += 1
            same += o["same"]
            rec_bad += o["rec_near"][0] < NEAR_M
            got_bad += o["got_near"] is not None and o["got_near"][0] < NEAR_M
            gn = f"{o['got_near'][0]:.2f} from {o['got_near'][1]}" if o["got_near"] else "none"
            print(f"{run.name} leg {o['leg']!s:>6} {o['status']:8s} recorded {o['recorded']} ({o['rec_near'][0]:.2f} from "
                  f"{o['rec_near'][1]})  replayed {o['replayed']} ({gn}){'  same' if o['same'] else ''}")
    print(f"REPLAY legs {total}: replay picks the recorded target {same}/{total}; targets within {NEAR_M} m of something "
          f"real: recorded {rec_bad}, replayed {got_bad}")
    return total, same, rec_bad, got_bad


if __name__ == "__main__":
    report([Path(a) for a in sys.argv[1:]])
