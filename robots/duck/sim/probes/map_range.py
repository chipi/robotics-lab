"""Score the grid maploc's replay bench built from a recorded session (record_session.py) against the apartment's layout:
how far each occupied cell lies from the nearest real surface, and how many cells the map calls free that lie inside one.

    cd /work/pollen/microduck   # Pollen's tree, read only; the build goes to a scratch target dir, never into theirs
    CARGO_TARGET_DIR=<scratch>/target cargo build -p maploc --release --example replay --offline --locked
    <scratch>/target/release/examples/replay SESSION --latency-ms 60 --quiet --export a.json [--set project.range_is_axial=false] \
        [--tof-pitch-deg 2.5]
    uv run python sim/probes/map_range.py [--scale 1] SESSION a.json [b.json ...]

The grid is in the map's frame; the map-to-world transform is the first keyframe's pose in the map against the truth at its
time (record_session's truth.jsonl, the same clock), and the other keyframes' distance from the truth through it is printed
(the frame's own error, which would move every cell the same way in each variant). A real surface is a solid layout geom's
footprint (boxes, cylinders, spheres, capsules; not floors, not the stairs' treads) whose underside is under 0.40 m (mapd's
ceiling) and which stands in the sensor's band.
"""

import bisect
import json
import math
import statistics
import sys
from pathlib import Path

from duck_lab.nav.frames import compose, inverse
from duck_lab.profile import load as load_profile

LAYOUT = Path(__file__).resolve().parents[1] / "apartment_layout.json"
CEILING_M = 0.40


def solid(g: dict) -> bool:
    name = g["name"]
    return bool(g.get("collides") or name.startswith("lm_")) and g.get("type") != "plane" and not name.startswith(("floor", "stair"))


def underside(g: dict) -> float:
    return g["pos"][2] - (g["size"][2] if g["type"] == "box" else g["size"][1] if g["type"] in ("cylinder", "capsule") else g["size"][0])


def footprint(g: dict) -> tuple:
    """(half x, half y) of the geom's footprint in its own frame, and whether it is round."""
    s = g["size"]
    if g["type"] == "box":
        return s[0], s[1], False
    return s[0], s[0], True


GEOMS = [g for g in json.loads(LAYOUT.read_text())["geoms"] if solid(g) and underside(g) <= CEILING_M]


def distance(x: float, y: float) -> float:
    """Signed distance from (x, y) to the nearest solid footprint's surface: positive outside it (in the free space a sensor
    looks through), negative inside (how deep)."""
    best = math.inf
    for g in GEOMS:
        hx, hy, round_ = footprint(g)
        c, s = math.cos(-g.get("yaw", 0.0)), math.sin(-g.get("yaw", 0.0))
        dx, dy = x - g["pos"][0], y - g["pos"][1]
        lx, ly = c * dx - s * dy, s * dx + c * dy
        if round_:
            d = math.hypot(lx, ly) - hx
        else:
            ox_, oy_ = abs(lx) - hx, abs(ly) - hy
            d = math.hypot(max(ox_, 0.0), max(oy_, 0.0)) if ox_ > 0 or oy_ > 0 else max(ox_, oy_)
        if abs(d) < abs(best):
            best = d
    return best


def scaled(pose, s: float) -> tuple:
    return (pose[0] * s, pose[1] * s, pose[2])


def frame_of(export: dict, truth: list, s: float) -> tuple:
    """(map-to-world, the keyframes' distances from the truth through it). Poses and the grid are in odometry metres; the
    navigator scales them by `s` (the profile's odometry scale) and so does this."""
    ts = [r["t_ns"] for r in truth]

    def truth_at(t_ns: int) -> tuple:
        i = min(max(bisect.bisect_left(ts, t_ns), 0), len(ts) - 1)
        w, x, y, z = truth[i]["quat"]
        return truth[i]["trunk"][0], truth[i]["trunk"][1], math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))

    kfs = [k for k in export["keyframes"] if k.get("final")]
    first = kfs[0]
    m2w = compose(truth_at(first["t_ns"]), inverse(scaled(first["final"], s)))
    resid = [math.dist(compose(m2w, scaled(k["final"], s))[:2], truth_at(k["t_ns"])[:2]) for k in kfs]
    return m2w, resid


def score(export: dict, m2w: tuple, s: float) -> dict:
    g = export["grid"]
    res, (ox, oy) = g["res"] * s, (g["origin"][0] * s, g["origin"][1] * s)
    occ, free_in = [], 0
    for j, row in enumerate(g["rows"]):
        for i, ch in enumerate(row):
            if ch == "?":
                continue
            wx, wy, _ = compose(m2w, (ox + (i + 0.5) * res, oy + (j + 0.5) * res, 0.0))
            d = distance(wx, wy)
            if ch == "#":
                occ.append(d)
            elif d < -0.01:
                free_in += 1
    occ.sort()
    n = len(occ)
    return {"res": res, "occupied": n, "median": statistics.median(occ), "mean": statistics.fmean(occ), "p10": occ[n // 10],
            "p90": occ[min(n - 1, int(n * 0.9))], "outside": sum(d > res / 2 for d in occ) / n,
            "on": sum(abs(d) <= res / 2 for d in occ) / n, "free_in_solid": free_in}


def main() -> None:
    args = sys.argv[1:]
    s = float(load_profile("sim").localisation.odometry.scale)
    if args[0] == "--scale":                 # 1 for a session whose odometry is the truth (truth_odometry.py)
        s, args = float(args[1]), args[2:]
    session = Path(args[0])
    truth = [json.loads(line) for line in (session / "truth.jsonl").read_text().splitlines()]
    for path in args[1:]:
        export = json.loads(Path(path).read_text())
        m2w, resid = frame_of(export, truth, s)
        r = score(export, m2w, s)
        print(f"{Path(path).name:14s} keyframes {len(export['keyframes'])}, frame residual max {max(resid) * 100:.1f} cm; occupied {r['occupied']} "
              f"(signed distance to a real surface, + outside: median {r['median'] * 100:+.1f} cm, mean {r['mean'] * 100:+.1f}, "
              f"p10 {r['p10'] * 100:+.1f}, p90 {r['p90'] * 100:+.1f}); on the surface within half a cell {r['on'] * 100:.0f} %, "
              f"outside it by more {r['outside'] * 100:.0f} %; {r['free_in_solid']} free cells more than 1 cm inside a real footprint")


if __name__ == "__main__":
    main()
