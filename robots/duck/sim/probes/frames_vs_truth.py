"""Does the duck's grid sit where the walls are, relative to the duck? (RFC-0016 §6, the frame fix.) At each pick event
(the grid the explorer read, the remembered obstacle points, the belief pose and the truth at that moment), the grid's wall
cells and the remembered points within NEAR_M of the duck are taken relative to the belief pose and placed in the world from
the truth pose; their distance to the nearest real surface (a colliding geom's outline, apartment layout) is how far the
duck is wrong about them. Also the belief's error against the truth (through start.json). Rows from T0 on are the ones a
fault at T0 affects; the rows before it are the same measure with no fault.

    .venv/bin/python sim/probes/frames_vs_truth.py T0 runs/frames-before runs/frames-after

Not measured: wall cells that have no real surface near them are counted as the large error they are (a phantom cell);
mapd's own frame (the picks of a run with --no-frames carry the grid as mapd drew it).
"""

import json
import math
import statistics
import sys
from pathlib import Path

import legacy_rows

from duck_lab.nav.evaluate import LAYOUT, footprint_distance
from duck_lab.nav.frames import compose, inverse

NEAR_M = 1.0
layout = json.loads(LAYOUT.read_text())
walls = [g for g in layout["geoms"] if g["collides"] and g["type"] != "plane" and not g["name"].startswith("floor")]


def surface(p):
    return min(abs(footprint_distance(p, g)) for g in walls)


def placed(points, b, tr):
    """points (belief frame) relative to the belief pose b, placed in the world from the truth tr: their distances to the
    nearest real surface."""
    c, sn = math.cos(-b[2]), math.sin(-b[2])
    ct, st = math.cos(tr[2]), math.sin(tr[2])
    out = []
    for p in points:
        dx, dy = p[0] - b[0], p[1] - b[1]
        if math.hypot(dx, dy) > NEAR_M:
            continue
        rx, ry = c * dx - sn * dy, sn * dx + c * dy
        out.append(surface((tr[0] + ct * rx - st * ry, tr[1] + st * rx + ct * ry)))
    return sorted(out)


def wall_cells(grid, scale):
    res, (ox, oy), w = grid["res_m"] * scale, (grid["origin"][0] * scale, grid["origin"][1] * scale), grid["width"]
    return [(ox + (i % w + 0.5) * res, oy + (i // w + 0.5) * res) for i, c in enumerate(grid["cells"]) if c == "#"]


def med(v):
    return statistics.median(v) if v else float("nan")


t0 = float(sys.argv[1])
for run in map(Path, sys.argv[2:]):
    st, log = legacy_rows.load(run)
    w_from_m = compose(tuple(st["truth"]), inverse(tuple(st["map"])))
    rows = {"pre-fault": [], "post-fault": []}
    beliefs = {"pre-fault": [], "post-fault": []}
    for r in log:
        if r.get("event") != "pick":
            if "truth" in r and "event" not in r and "pose" in r:
                bq = compose(w_from_m, tuple(r["pose"]))
                beliefs["post-fault" if r["t"] >= t0 else "pre-fault"].append(math.dist(bq[:2], r["truth"][:2]))
            continue
        b, tr = r["pose"], r.get("truth")
        if not tr:
            continue
        cells = placed(wall_cells(r["grid"], r["scale"]), b, tr)
        pts = placed(r["obstacles"], b, tr)
        bw = compose(w_from_m, (b[0], b[1], b[2]))
        rows["post-fault" if r["t"] >= t0 else "pre-fault"].append((r["t"], len(cells), med(cells), cells[int(len(cells) * 0.9)] if cells else float("nan"),
                                                           len(pts), med(pts), math.dist(bw[:2], tr[:2])))
    print(f"== {run.name}")
    for k, v in rows.items():
        if not v:
            continue
        ok = [x for x in v if x[1]]
        print(f"{k:10s} ({len(v)} picks); wall cells within {NEAR_M:g} m off the real surface: median of medians "
              f"{med([x[2] for x in ok]):.3f} m, worst median {max((x[2] for x in ok), default=float('nan')):.3f} m, "
              f"p90 of p90s {med([x[3] for x in ok]):.3f} m; remembered points: median of medians "
              f"{med([x[5] for x in v if x[4]]):.3f} m; belief off the world: mean {statistics.mean(x[6] for x in v):.3f} m, "
              f"max {max(x[6] for x in v):.3f} m")
    for k, v in beliefs.items():
        if v:
            print(f"{k:10s} belief off the world, every tick ({len(v)}): mean {statistics.mean(v):.3f} m, max {max(v):.3f} m, last {v[-1]:.3f} m")
    for x in rows["post-fault"]:
        print(f"  t {x[0]:6.1f}: {x[1]:4d} wall cells median {x[2]:.3f} p90 {x[3]:.3f} | {x[4]:3d} points median {x[5]:.3f} | belief off {x[6]:.3f}")
