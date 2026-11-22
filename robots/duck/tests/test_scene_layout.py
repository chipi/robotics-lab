"""The apartment's description (scenes/apartment/scene.json, phase 5 item 2) against the duck's simulator, and the runner's truth guard
reading the scene's drops only: the file's boxes are the layout's (runfile.scenefile.boxes_from_layout), its stairwell is where the
layout's treads are, its rooms are between the layout's walls; the guard stops a goal at the apartment's stairwell, and in a scene
with no drop it has none (before, it added the apartment's stairwell to any layout without a drop: the architecture review's
finding). Run: cd robots/duck && uv run python tests/test_scene_layout.py"""

import json
import sys
import tempfile
from pathlib import Path

from labrunner.geometry import LAYOUT
from labrunner.guard import TruthGuard, drop_distance, load_layout
from runfile import scenefile

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


apt = scenefile.load("apartment")
layout = json.loads(LAYOUT.read_text())
geoms = {g["name"]: g for g in layout["geoms"]}
made = scenefile.boxes_from_layout(layout)
check("the scene's boxes are the simulator layout's, the free bodies too (refresh: scenefile.boxes_from_layout)",
      apt.raw["boxes"] == made, "" if apt.raw["boxes"] == made else sorted({b["name"] for b in made} ^ {b["name"] for b in apt.raw["boxes"]}) or "values differ")
check("61 boxes, obj_0..3 among them", len(made) == 61 and {f"obj_{i}_geom" for i in range(4)} <= {b["name"] for b in made})

treads = [g for n, g in geoms.items() if n.startswith("stair_")]
x0 = min(g["pos"][0] - g["size"][0] for g in treads)
x1 = max(g["pos"][0] + g["size"][0] for g in treads)
y0 = min(g["pos"][1] - g["size"][1] for g in treads)
y1 = max(g["pos"][1] + g["size"][1] for g in treads)
low = min(g["pos"][2] + g["size"][2] for g in treads)
(stairs,) = apt.drops
check("the stairwell is the treads' outline", all(abs(a - b) < 0.002 for a, b in zip((x0, x1, y0, y1),
                                                                                    (stairs["x0"], stairs["x1"], stairs["y0"], stairs["y1"]))),
      (round(x0, 3), round(x1, 3), round(y0, 3), round(y1, 3)))
check("and as deep as the last tread's top", abs(stairs["depth"] + low) < 1e-9, low)


def wall_at(axis: int, v: float) -> bool:
    """A wall of the layout runs along x = v (axis 0) or y = v (axis 1)."""
    return any(n.startswith("w") and abs(g["pos"][axis] - v) < 1e-9 and g["size"][axis] < 0.1 for n, g in geoms.items())


bad = [r.name for r in apt.rooms if not (wall_at(0, r.x0) and wall_at(0, r.x1) and wall_at(1, r.y0) and wall_at(1, r.y1))]
check("each room is between the layout's walls", not bad, bad)
check("the scene's bounds are the outer walls' lines", wall_at(0, apt.bounds[0]) and wall_at(0, apt.bounds[1])
      and wall_at(1, apt.bounds[2]) and wall_at(1, apt.bounds[3]))

rail = [{"name": "drop_clearance", "m": 0.3}]
guard = TruthGuard(rail, scene=apt)
hit = guard.check((-0.2, -0.5, 0.0), 0.2)
check("the guard stops a goal 0.2 m from the apartment's stairwell, naming it", hit is not None and hit[0] == "drop_clearance"
      and "stairs" in hit[1], hit)
check("and lets it be 1 m away", guard.check((-0.2, 0.5, 0.0), 0.2) is None)
check("the drop distance is the stairwell's", abs(drop_distance(apt, (-0.2, -0.5)) - 0.2) < 1e-9, drop_distance(apt, (-0.2, -0.5)))

with tempfile.TemporaryDirectory() as tmp:
    flat = {**apt.raw, "id": "flat", "hazards": []}
    (Path(tmp) / "flat").mkdir()
    (Path(tmp) / "flat" / "scene.json").write_text(json.dumps(flat))
    none = scenefile.load("flat", Path(tmp))
obs, drops = load_layout(none)
check("must fail: a scene with no drop: the guard has none, nothing added", drops == [] and obs, drops)
check("and does not stop at the place of the apartment's stairwell", TruthGuard(rail, scene=none).check((-0.2, -1.0, 0.0), 0.2) is None)
check("a scene with no drop is infinitely far from one", drop_distance(none, (0.0, 0.0)) == float("inf"))
try:
    TruthGuard(rail)
    check("must fail: a truth guard with neither a scene nor a layout", False)
except ValueError as e:
    check("must fail: a truth guard with neither a scene nor a layout", "scene" in str(e), e)

print("SCENE LAYOUT", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
