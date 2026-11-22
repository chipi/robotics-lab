"""A run's world model in Rerun: what the brain believed, against what was there (roadmap, "the world
model in the viewer").

Reads a run directory written by the navigator (duck-go, duck-eval, duck-explore: ticks.jsonl, and
start.json when there is one) and draws, in the simulator's world frame, on a "run" timeline:

- apartment/   the simulator's layout (sim/apartment_layout.json): what was really there, static
- map/         mapd's grid at each change: occupied cells as boxes, free cells as dots
- memory/      the navigator's remembered obstacle points (orange) and drops (magenta)
- depth        each depth frame's returns: floor green, obstacle red, overhead blue
- plan         the path being followed
- belief/, truth/   the duck where the brain thought it was, and where it was, with their tracks
- events       stops, refusals, plans as a log

Map-frame data goes to the world frame with the transform measured at the start of each map (for
duck-eval, each goal: the simulator is reset per goal), so drift since then shows as belief leaving
truth.

    uv run duck-world runs/explore8                  # writes runs/explore8/world.rrd
    uv run rerun runs/explore8/world.rrd             # or open it in the running viewer
"""

import argparse
import json
import math
from pathlib import Path

import rerun as rr

from duck_lab.nav.frames import compose, inverse
from runfile.navcontract import STOPS, stop_before

LAYOUT = Path(__file__).resolve().parents[2] / "sim" / "apartment_layout.json"
STAIRS = (-0.40, 0.00, -1.40, -0.70)
ENDS = ("reached", "refused", "timeout", "stalled") + STOPS
DEPTH_COLOURS = {"f": (60, 200, 90), "o": (230, 50, 40), "v": (60, 120, 230), "b": (230, 0, 230)}   # floor, obstacle, overhead, below the floor


def apply(t: tuple, p) -> list:
    x, y, _ = compose(t, (p[0], p[1], 0.0))
    return [x, y]


def log_layout() -> None:
    layout = json.loads(LAYOUT.read_text())
    centres, halves, rotations = [], [], []
    for g in layout["geoms"]:
        if not g.get("collides") or str(g.get("name", "")).startswith("floor") or g.get("type") not in ("box", "cylinder"):
            continue
        size = g["size"]
        half = size if g["type"] == "box" else [size[0], size[0], size[1]]
        centres.append(g["pos"])
        halves.append(half)
        rotations.append(rr.RotationAxisAngle(axis=[0, 0, 1], angle=g.get("yaw", 0.0)))
    rr.log("apartment/geoms", rr.Boxes3D(centers=centres, half_sizes=halves, rotation_axis_angles=rotations,
                                         colors=[(160, 160, 170)], fill_mode="majorwireframe"), static=True)
    x0, x1, y0, y1 = STAIRS
    rr.log("apartment/stairs", rr.Boxes3D(centers=[[(x0 + x1) / 2, (y0 + y1) / 2, -0.05]],
                                          half_sizes=[[(x1 - x0) / 2, (y1 - y0) / 2, 0.05]],
                                          colors=[(200, 0, 200)], labels=["stairs"]), static=True)


def log_world(rec: dict, t: tuple, scale: float) -> None:
    g = rec["grid"]
    res, (ox, oy), w = g["res_m"], g["origin"], g["width"]
    occupied, free = [], []
    for i, c in enumerate(g["cells"]):
        if c == "?":
            continue
        xy = apply(t, (ox + (i % w + 0.5) * res, oy + (i // w + 0.5) * res))
        (occupied if c == "#" else free).append(xy)
    rr.log("map/occupied", rr.Boxes3D(centers=[[x, y, 0.05] for x, y in occupied],
                                      half_sizes=[[res / 2, res / 2, 0.05]] * len(occupied), colors=[(90, 90, 90)]))
    rr.log("map/free", rr.Points3D([[x, y, 0.002] for x, y in free], radii=res / 3, colors=[(170, 220, 170)]))
    rr.log("memory/obstacles", rr.Points3D([apply(t, b) + [0.1] for b in rec["blocked"]], radii=0.015,
                                           colors=[(255, 150, 0)]))
    rr.log("memory/drops", rr.Points3D([apply(t, d) + [0.0] for d in rec["drops"]], radii=0.02,
                                       colors=[(230, 0, 230)]))


def convert(run: Path, out: Path) -> dict:
    rr.init(f"duck-world-{run.name}", spawn=False)
    rr.save(str(out))
    rr.log("/", rr.ViewCoordinates.RIGHT_HAND_Z_UP, static=True)
    log_layout()
    start = json.loads((run / "start.json").read_text()) if (run / "start.json").exists() else None
    scale = start["scale"] if start else 1.0
    t_wm = compose(tuple(start["truth"]), inverse(tuple(start["map"]))) if start else None
    fresh = t_wm is None
    belief, truth, counts = [], [], {}
    offset, last_t = 0.0, 0.0
    for line in open(run / "ticks.jsonl"):
        r = json.loads(line)
        if "t" not in r:
            continue
        if r["t"] < last_t - 1.0:       # duck-eval: a new navigator per goal starts its clock at 0
            offset += last_t + 1.0
        last_t = r["t"]
        rr.set_time("run", duration=offset + r["t"])
        ev = r.get("event")
        if ev == "aborted":                 # a stop before the navigator contract: named by its reason now
            ev = stop_before(r.get("why"))
        counts[ev or "tick"] = counts.get(ev or "tick", 0) + 1
        if fresh and "pose" in r and "truth" in r and not ev:
            t_wm = compose(tuple(r["truth"]), inverse(tuple(r["pose"])))     # the map's start, by truth
            fresh = False
            belief, truth = [], []
        if t_wm is None:
            continue
        if ev == "world":
            log_world(r, t_wm, scale)
        elif ev == "plan":
            rr.log("plan", rr.LineStrips3D([[apply(t_wm, q) + [0.03] for q in r["path"]]], colors=[(250, 210, 0)],
                                           radii=0.008))
        elif ev:
            detail = {k: v for k, v in r.items() if k not in ("t", "truth", "truth_z", "pose", "path", "drops",
                                                             "blocked", "grid")}
            rr.log("events", rr.TextLog(f"{ev} {json.dumps(detail)}", level="WARN" if ev in (
                "refused", "stalled", "timeout", "cliff_stop", "reflex_stop", *STOPS, "trapped") else "INFO"))
            if ev in ENDS and r.get("goal") is not None and start is None:
                fresh = True        # duck-eval: the next goal starts from a reset simulator, a new map
        if "pose" in r and not ev:
            b = apply(t_wm, r["pose"])
            belief.append(b + [0.02])
            rr.log("belief/duck", rr.Points3D([b + [0.14]], radii=0.083, colors=[(70, 130, 255)]))
            rr.log("belief/track", rr.LineStrips3D([belief], colors=[(70, 130, 255)], radii=0.004))
            if r.get("depth"):
                pts = [apply(t_wm, d) + [d[2]] for d in r["depth"]]
                rr.log("depth", rr.Points3D(pts, radii=0.012, colors=[DEPTH_COLOURS[d[3]] for d in r["depth"]]))
        if "truth" in r and not ev:
            truth.append(list(r["truth"][:2]) + [0.01])
            rr.log("truth/duck", rr.Points3D([list(r["truth"][:2]) + [0.14]], radii=0.083, colors=[(40, 200, 90)]))
            rr.log("truth/track", rr.LineStrips3D([truth], colors=[(40, 200, 90)], radii=0.004))
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path, help="a run directory with ticks.jsonl")
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()
    out = args.out or args.run / "world.rrd"
    counts = convert(args.run, out)
    print(f"wrote {out}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
