"""K45 replayed: three inventory goals of sim_duck (2026-11-22) whose seeded objects were marked gone, their looks put through the
real worldmodel.SemanticMap again (tests/fixtures/k45_inventory.json.gz: each goal's seeds, sighting rows and recorded grids; the
grid at a look is the last one recorded before it, which the navigator held then or an older one).

First the replay is checked faithful: with the rule as it was (a sight line counts unless mapd's grid has a wall on it; the code
of before is `wall_between`, unchanged, so swapping it back in is that code), it marks gone exactly what each run marked gone.
Then the rule as it is (sight_clear: only a sight line mapd has mapped and found free counts) marks none of them gone. The
looks behind walls mapd had not mapped are what changed; worldmodel's own cases (no grid, an unmapped column, a known free line
still forgets) are in test_world_model.py.
Run: cd robots/duck && uv run python tests/test_forget_replay.py"""

import gzip
import json
import sys
from pathlib import Path

from worldmodel import semantic_map as SM
from worldmodel.objects import load_kinds

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "k45_inventory.json.gz"
with gzip.open(FIXTURE, "rt") as f:
    GOALS = json.load(f)["goals"]
KINDS = load_kinds()
HFOV, RANGE = 60.0, 3.0                       # the simulated camera's (calibration/sim.json, profile sensors.camera)


def replay(goal: dict) -> list:
    seeds = [{**o, "n": max(o["n"], SM.CONFIRM_N), "misses": 0, "gone": False, "gone_t": None, "missing": False,
              "sources": ["site"]} for o in goal["seeds"]]
    m = SM.SemanticMap.from_json({"objects": seeds}, KINDS)
    gone = []
    for look in goal["looks"]:
        grid = None
        for g in goal["grids"]:
            if g["t"] <= look["t"]:
                grid = g["grid"]
        dets = [SM.Detection(**{k: d[k] for k in ("kind", "x", "y", "radius", "z0", "z1", "range_m", "confidence", "source")})
                for d in look["seen"]]
        pose = tuple(look["pose"])
        m.integrate(dets, pose, look["t"])
        gone += [o.oid for change, o in m.forget(pose, HFOV, RANGE, grid, look["t"]) if change == "gone"]
    return sorted(set(gone))


check("the fixture holds the three goals, each with seeds, looks and grids",
      len(GOALS) == 3 and all(g["seeds"] and g["looks"] and g["grids"] for g in GOALS), [g["source"] for g in GOALS])

now = SM.sight_clear
SM.sight_clear = lambda grid, a, b: not SM.wall_between(grid, a, b)      # the rule of before: only a mapped wall stops a miss
try:
    before = [replay(g) for g in GOALS]
finally:
    SM.sight_clear = now
for g, b in zip(GOALS, before):
    check(f"faithful: with the rule of before, the replay marks gone what the run did ({g['source']})", b == g["gone"],
          (b, g["gone"]))

after = [replay(g) for g in GOALS]
for g, a in zip(GOALS, after):
    check(f"with sight_clear none of the run's seeds is gone ({g['source']}: was {g['gone']})", a == [], a)

print()
print("FORGET REPLAY", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
