"""The glance's edge against the real one, over recorded runs (docs/wip/SIDE-DROPS.md's error budget was stated as -14/+6.4 cm looking aside,
-18/+3 cm ahead, 54 glances; re-measured over challenges 8-11, 355 glances: short up to -36.5 cm, past up to +74.6 cm at a glance's worst rim
point, +8.8 cm at its least-past one: that section, "What the edge error is used for"). Each glance event of the runs given is replayed from the run's own depth frames with the edge
code as it is now (glance_from_run.replay_glance), and every rim point it makes is measured against the scene's drop (the
hazard boxes of data/scenes/<scene>/scene.json, or an apartment run's stairwell, y -0.70): signed, negative when the rim lies
on the floor side of the edge (short: the edge is farther than the duck believes), positive past it (inside the hole).

    .venv/bin/python sim/probes/glance_edge_error.py ch11-s1 ch10-s1 ...          # every run of those scenes
    .venv/bin/python sim/probes/glance_edge_error.py apartment/explore-b11-r2    # one run (the stairwell)

A glance's error is its worst rim point on each side (min and max); the table gives them over all glances. Glances in a run
that predates `time_s` in the event, or whose frames carry no pose, are counted as skipped.
"""

import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

from duck_lab import replay
from duck_lab.nav.frames import compose, inverse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glance_from_run import DATA, glances, replay_glance  # noqa: E402

AIMED_M = 0.5                                  # a glance counts when its target is this near a real drop
STAIRS = (-0.40, 0.00, -1.40, -0.70)         # explore_run.STAIRS: x0, x1, y0, y1, the opening in the apartment (world frame)


def box_signed(p: tuple, cx: float, cy: float, hx: float, hy: float, yaw: float) -> float:
    """Signed plan distance from p to a box: positive outside, negative inside."""
    c, s = math.cos(-yaw), math.sin(-yaw)
    lx, ly = c * (p[0] - cx) - s * (p[1] - cy), s * (p[0] - cx) + c * (p[1] - cy)
    dx, dy = abs(lx) - hx, abs(ly) - hy
    return math.hypot(max(dx, 0.0), max(dy, 0.0)) if dx > 0 or dy > 0 else max(dx, dy)


def holes_of(run: str) -> list:
    if run.startswith("apartment/"):
        x0, x1, y0, y1 = STAIRS
        return [((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2, 0.0)]
    scene = json.loads((DATA / "scenes" / run.split("/")[0] / "scene.json").read_text())
    return [((h["x0"] + h["x1"]) / 2, (h["y0"] + h["y1"]) / 2, (h["x1"] - h["x0"]) / 2, (h["y1"] - h["y0"]) / 2, h["yaw"])
            for h in scene["hazards"]]


def runs_of(arg: str) -> list:
    base = DATA / "runs" / "duck"
    if "/" in arg:
        return [arg]
    return [f"{arg}/{d.name}" for d in sorted((base / arg).iterdir()) if d.is_dir()]


def measure(arg: str, sensor_origin: bool = False) -> list:
    """[(run, glance index, t, status, worst short (min), worst past (max), rim points)] for each glance of a scene's runs."""
    rows, skipped = [], 0
    for run in runs_of(arg):
        records = list(Follower(DATA / "runs" / "duck" / run, keep_raw=True).poll())
        holes = holes_of(run)
        for n, (t, raw) in enumerate(glances(records)):
            if raw.get("time_s") is None or not raw.get("truth") or not raw.get("pose"):
                skipped += 1
                continue
            out = replay_glance(records, t, raw, sensor_origin=sensor_origin)
            if not out["rim"]:
                continue
            w = compose(tuple(raw["truth"]), inverse(tuple(raw["pose"])))
            tx, ty, _ = compose(w, (raw["target"][0], raw["target"][1], 0.0))
            if min(box_signed((tx, ty), *h) for h in holes) > AIMED_M:
                skipped += 1                    # looked at something that is not a drop in the scene's list (a false suspicion)
                continue
            errs = []
            for q in out["rim"]:
                x, y, _ = compose(w, (q[0], q[1], 0.0))
                errs.append(-min(box_signed((x, y), *h) for h in holes))
            rows.append((run, n, t, raw["status"], min(errs), max(errs), len(errs)))
    return rows, skipped


def main() -> None:
    rows, skipped = [], 0
    sensor = "--sensor" in sys.argv
    for arg in (a for a in sys.argv[1:] if a != "--sensor"):
        r, s = measure(arg, sensor)
        rows += r
        skipped += s
    for run, n, t, status, lo, hi, k in rows:
        print(f"{run} glance {n} t {t:6.1f} {status:5s} {k} rim points: {lo * 100:+6.1f} .. {hi * 100:+6.1f} cm")
    if rows:
        print(f"{len(rows)} glances with a rim ({skipped} skipped): worst short {min(r[4] for r in rows) * 100:+.1f} cm, "
              f"worst past {max(r[5] for r in rows) * 100:+.1f} cm; median of the shortest "
              f"{sorted(r[4] for r in rows)[len(rows) // 2] * 100:+.1f} cm")


if __name__ == "__main__":
    main()
