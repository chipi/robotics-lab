"""A persistence filter for the forward sensor's "below" returns, replayed on recorded runs: per 5 cm cell (map frame), the
frames that put a below-floor return there and the frames that put a floor return there; a cell is a drop cell once it has
at least K below frames and at least RATIO times as many below frames as floor frames. Per run: drop cells inside the true
hazard (put into the world frame with the epoch) and outside it (false), and when the first true one appeared against the
trunk's closest approach. For scenes with no drop, every drop cell is false.

    uv run python sim/probes/below_cells.py 3 2 ch1 ch2 ch3 ch4 ch5 ch10 ch11
"""

import collections
import json
import math
import sys
from pathlib import Path

from miniview.mcapio import Follower

sys.path.insert(0, str(Path(__file__).resolve().parent))
from room_vs_truth import box_distance  # noqa: E402
from below_seen import rects  # noqa: E402

DATA, CELL = Path("/work/robotics-lab/data"), 0.05
K, RATIO = int(sys.argv[1]), float(sys.argv[2])
for prefix in sys.argv[3:]:
    false_runs, false_cells, caught, n_drop, n_flat, leads = 0, [], 0, 0, 0, []
    for d in sorted((DATA / "runs" / "duck").glob(f"{prefix}-s*/run-20261116-*")):
        hz = rects(json.loads((DATA / "scenes" / d.parent.name / "scene.json").read_text()))
        b, f, epoch, cells, first_true, closest = collections.Counter(), collections.Counter(), None, set(), None, (math.inf, None)
        for t, k, p in Follower(d, keep_raw=True).poll():
            if k == "epoch":
                epoch = p["map_to_world"]
            elif k == "tick" and p.get("truth") and hz:
                dd = min(box_distance(p["truth"][0], p["truth"][1], h) for h in hz)
                if dd < closest[0]:
                    closest = (dd, t)
            elif k == "depth_frame":
                fb, ff = set(), set()
                for q in (p.get("derived") or {}).get("points") or []:
                    c = (round(q[0] / CELL), round(q[1] / CELL))
                    if q[3] == "b":
                        fb.add(c)
                    elif q[3] == "f":
                        ff.add(c)
                for c in fb:
                    b[c] += 1
                for c in ff:
                    f[c] += 1
                for c in fb:
                    if c not in cells and b[c] >= K and b[c] >= RATIO * f[c]:
                        cells.add(c)
                        if hz and epoch and first_true is None:
                            cs, sn = math.cos(epoch[2]), math.sin(epoch[2])
                            wx, wy = epoch[0] + cs * c[0] * CELL - sn * c[1] * CELL, epoch[1] + sn * c[0] * CELL + cs * c[1] * CELL
                            if min(box_distance(wx, wy, h) for h in hz) < CELL:
                                first_true = t
        if hz and epoch:
            n_drop += 1
            cs, sn = math.cos(epoch[2]), math.sin(epoch[2])
            inside = sum(1 for c in cells if min(box_distance(epoch[0] + cs * c[0] * CELL - sn * c[1] * CELL,
                                                              epoch[1] + sn * c[0] * CELL + cs * c[1] * CELL, h) for h in hz) < CELL)
            outside = len(cells) - inside
            if first_true is not None and closest[1] is not None and first_true < closest[1]:
                caught += 1
                leads.append(closest[1] - first_true)
            false_cells.append(outside)
            print(f"{d.parent.name:9s} {d.name}: drop cells inside {inside}, outside {outside}; first true "
                  f"{'%.1f s' % first_true if first_true is not None else 'never'}; closest {closest[0]:.3f} m at {closest[1]:.1f} s")
        else:
            n_flat += 1
            false_cells.append(len(cells))
            if cells:
                false_runs += 1
    fc = sorted(false_cells)
    if n_drop:
        leads.sort()
        print(f"== {prefix} K={K} ratio={RATIO}: drop caught before the closest approach in {caught} of {n_drop} runs "
              f"(lead median {leads[len(leads) // 2] if leads else float('nan'):.1f} s); false cells per run median {fc[len(fc) // 2]}, max {fc[-1]}")
    else:
        print(f"== {prefix} K={K} ratio={RATIO}: no drop; runs with any false drop cell {false_runs} of {n_flat}; "
              f"false cells per run median {fc[len(fc) // 2]}, max {fc[-1]}")
