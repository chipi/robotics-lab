"""How wrong is the duck about where things are relative to itself? (stream A, 2026-11-17: b3 r1's door-frame contact,
the navigator 0.29 m from the frame, the truth 0.08 m.) The safety-relevant error is not the duck's belief against the
world but the obstacles it remembers against itself: if its map drifts with its belief it stays consistent and walks
safely.

At each pick event (from batch b2 on: the navigator's remembered obstacle points, its belief pose and the truth at that
moment), every remembered obstacle point within NEAR_M of the duck is taken relative to the belief pose and placed in the
world from the truth pose; its distance to the nearest real surface (a colliding geom's outline, apartment layout) is how
far the duck is wrong about it. Also: the belief's offset from the truth through start.json, for comparison.

    .venv/bin/python sim/probes/map_relative_error.py runs/explore-b3-r1 runs/explore-b3-r3

Not measured: mapd's occupied cells (the remembered obstacle points are what the planner keeps the duck off); points with
no real surface near them (a phantom point stays far from every surface and is counted as a large error, which it is).
"""

import json
import math
import statistics
import sys
from pathlib import Path

import legacy_rows

from labrunner import geometry
from labrunner.geometry import footprint_distance

LAYOUT = geometry.layout_path()
from duck_lab.nav.frames import compose, inverse

NEAR_M = 1.0
layout = json.loads(LAYOUT.read_text())
walls = [g for g in layout["geoms"] if g["collides"] and g["type"] != "plane" and not g["name"].startswith("floor")]


def surface(p):
    return min(abs(footprint_distance(p, g)) for g in walls)


for run in map(Path, sys.argv[1:]):
    st, log = legacy_rows.load(run)
    w_from_m = compose(tuple(st["truth"]), inverse(tuple(st["map"])))
    s = st["scale"]
    print(f"== {run.name}")
    for r in log:
        if r.get("event") != "pick":
            continue
        b, tr = r["pose"], r.get("truth")
        if not tr:
            continue
        c, sn = math.cos(-b[2]), math.sin(-b[2])
        ct, stt = math.cos(tr[2]), math.sin(tr[2])
        errs = []
        for o in r["obstacles"]:
            dx, dy = o[0] - b[0], o[1] - b[1]
            if math.hypot(dx, dy) > NEAR_M:
                continue
            rx, ry = c * dx - sn * dy, sn * dx + c * dy                  # in the duck's frame, by its belief
            wx, wy = tr[0] + ct * rx - stt * ry, tr[1] + stt * rx + ct * ry   # placed from where it really was
            errs.append(surface((wx, wy)))
        bw = compose(w_from_m, (b[0] * s, b[1] * s, b[2]))
        off = math.dist(bw[:2], tr[:2])
        if errs:
            errs.sort()
            print(f"t {r['t']:6.1f} near points {len(errs):3d}: off the real surface median {statistics.median(errs):.3f} m, "
                  f"p90 {errs[int(len(errs) * 0.9)]:.3f} m | belief off the world {off:.3f} m")
