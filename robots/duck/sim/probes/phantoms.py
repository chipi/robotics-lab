"""Phantom obstacles in a run: obstacle points and mapd cells where the simulator has nothing.

For a run directory written with the world logging (duck-world's input), measures every remembered
obstacle point, mapd's occupied cells and each depth return classed "obstacle" against the layout's
colliding geoms (their footprints, by truth), and reports the ones farther than PHANTOM_M from any of
them, with what the duck was doing when the depth returns came.

    .venv/bin/python sim/probes/phantoms.py runs/explore9
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from duck_lab.nav.frames import compose, inverse  # noqa: E402

PHANTOM_M = 0.10
LAYOUT = Path(__file__).resolve().parents[1] / "apartment_layout.json"
STAIRS = (-0.40, 0.00, -1.40, -0.70)

geoms = []
for g in json.loads(LAYOUT.read_text())["geoms"]:
    if g.get("collides") and not str(g.get("name", "")).startswith("floor") and g.get("type") in ("box", "cylinder"):
        sx, sy = (g["size"][0], g["size"][1]) if g["type"] == "box" else (g["size"][0], g["size"][0])
        geoms.append((g["name"], g["pos"][0], g["pos"][1], sx, sy, g.get("yaw", 0.0)))


def nearest(p):
    best = (math.inf, None)
    for name, cx, cy, sx, sy, yaw in geoms:
        c, s = math.cos(-yaw), math.sin(-yaw)
        dx, dy = p[0] - cx, p[1] - cy
        lx, ly = c * dx - s * dy, s * dx + c * dy
        d = math.hypot(max(abs(lx) - sx, 0), max(abs(ly) - sy, 0))
        best = min(best, (d, name))
    x0, x1, y0, y1 = STAIRS
    d = math.hypot(max(x0 - p[0], 0, p[0] - x1), max(y0 - p[1], 0, p[1] - y1))
    return min(best, (d, "stairs"))


run = Path(sys.argv[1])
start = json.loads((run / "start.json").read_text())
t = compose(tuple(start["truth"]), inverse(tuple(start["map"])))


def world(p):
    x, y, _ = compose(t, (p[0], p[1], 0.0))
    return x, y


rows = [json.loads(l) for l in open(run / "ticks.jsonl")]
worlds = [r for r in rows if r.get("event") == "world"]
last = worlds[-1]
blocked = [world(b) for b in last["blocked"]]
ph = [(nearest(b), b) for b in blocked]
bad = [x for x in ph if x[0][0] > PHANTOM_M]
print(f"remembered obstacle points: {len(blocked)}, phantoms (> {PHANTOM_M} m from anything real): {len(bad)}")
for (d, name), b in sorted(bad, reverse=True)[:8]:
    print(f"   at ({b[0]:.2f}, {b[1]:.2f}): {d:.2f} m from {name}")
g = last["grid"]
res, (ox, oy), w = g["res_m"], g["origin"], g["width"]
cells = [world((ox + (i % w + 0.5) * res, oy + (i // w + 0.5) * res)) for i, c in enumerate(g["cells"]) if c == "#"]
cbad = [(nearest(c), c) for c in cells if nearest(c)[0] > PHANTOM_M + res / 2]
print(f"mapd occupied cells: {len(cells)}, phantoms: {len(cbad)}")
for (d, name), c in sorted(cbad, reverse=True)[:8]:
    print(f"   at ({c[0]:.2f}, {c[1]:.2f}): {d:.2f} m from {name}")

# Depth returns classed obstacle: phantom or real, against height, range and motion.
real, phantom = [], []
for r in rows:
    if not r.get("depth") or "pose" not in r:
        continue
    pose = r["pose"]
    for x, y, z, k in r["depth"]:
        if k != "o":
            continue
        p = world((x, y))
        d, name = nearest(p)
        rng = math.dist((x, y), pose[:2])
        rec = {"z": z, "range": rng, "turning": r.get("turning"), "vx": r.get("vx"), "vyaw": r.get("vyaw"), "d": d}
        (phantom if d > PHANTOM_M else real).append(rec)
print(f"depth returns classed obstacle: {len(real) + len(phantom)}, phantoms: {len(phantom)}")
if phantom:
    def summary(xs, key):
        v = sorted(x[key] for x in xs)
        return f"median {v[len(v) // 2]:.3f}, 10-90 % {v[len(v) // 10]:.3f}-{v[9 * len(v) // 10]:.3f}"
    for key in ("z", "range"):
        print(f"   {key}: phantoms {summary(phantom, key)} | real {summary(real, key) if real else '-'}")
    print("   motion (phantoms):", Counter("turning" if x["turning"] else ("walking" if x["vx"] else "still") for x in phantom))
    print("   motion (real):    ", Counter("turning" if x["turning"] else ("walking" if x["vx"] else "still") for x in real))
