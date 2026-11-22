"""Approach the stairwell from several angles: the cliff check, the drop memory and the planner must
keep the duck out of it each time (exploration trial 10 came diagonally past the corner and only the
truth guard stopped it, 5 cm from the edge).

Each approach starts from a reset simulator at the dock: go to a start point (world frame), then try
for a target inside or beside the opening. A truth guard aborts at GUARD_M, so a failure is a
reported closest distance, not a fall. Run with the simulator up:
    robots/duck/.venv/bin/python robots/duck/sim/probes/stairs_angles.py
"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from duck_lab.nav.frames import compose, inverse  # noqa: E402
from duck_lab.nav.run import Navigator, host_links  # noqa: E402
from simhost.truth import Body  # noqa: E402 - the probe's own truth, to measure with (the navigator has none)
import simhost  # noqa: E402

STAIRS = (-0.40, 0.00, -1.40, -0.70)
GUARD_M = 0.05
RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runs")     # robots/duck/runs, wherever this is run from
os.makedirs(RUNS, exist_ok=True)
APPROACHES = [   # name, start (world), target (world)
    ("head-on from the north", None, (-0.2, -1.05)),
    ("diagonal past the NW corner (trial 10)", (-0.09, -0.39), (-0.31, -0.80)),
    ("diagonal from the NE", (0.25, -0.30), (-0.15, -0.95)),
    ("from the NW", (-0.70, -0.30), (-0.20, -0.90)),
    ("along the east side", (0.25, -0.30), (0.25, -1.60)),
    ("trial 10's diagonal, from further back", (0.15, -0.15), (-0.31, -0.80)),
]


def edge_distance(p):
    x0, x1, y0, y1 = STAIRS
    return ((max(x0 - p[0], 0, p[0] - x1)) ** 2 + (max(y0 - p[1], 0, p[1] - y1)) ** 2) ** 0.5


ONLY = [int(a) for a in sys.argv[1:]]   # approach numbers to run (0-based); all when none
results = []
for i, (name, start, target) in enumerate(APPROACHES):
    if ONLY and i not in ONLY:
        continue
    simhost.reset(simhost.load())
    nav = Navigator(**host_links(simhost.load()), log=os.path.join(RUNS, f"stairs-{i}.jsonl"))
    truth = Body(simhost.load().truth_port)
    closest = [9.0]

    def guard(nav=nav, closest=closest):
        while not nav.abort:
            d = edge_distance(truth.pose()[:2])
            closest[0] = min(closest[0], d)
            if d < GUARD_M:
                nav.stop_goal("stopped_by_guardrail", f"truth guard: {d:.2f} m from the opening")
            time.sleep(0.05)

    try:
        if not nav.fix():
            nav.survey()
        map_from_world = compose(nav.loc.pose(), inverse(truth.pose()))
        threading.Thread(target=guard, daemon=True).start()
        first = None
        if start:
            first = nav.go_to(compose(map_from_world, (*start, 0.0))[:2], 60.0)
        out = nav.go_to(compose(map_from_world, (*target, 0.0))[:2], 60.0)
        guarded = (nav.abort or "").startswith("truth guard")
        nav.stop_goal("cancelled", "done")
        results.append({"approach": name, "start": first and first["status"], "result": out["status"],
                        "why": out.get("why"), "closest_m": round(closest[0], 3), "guard_tripped": guarded})
        print(json.dumps(results[-1]), flush=True)
    finally:
        nav.close()

bad = [r for r in results if r["guard_tripped"] or r["closest_m"] < 0.15]
print("STAIRS", "FAIL " + ", ".join(r["approach"] for r in bad) if bad else "PASS",
      f"(closest {min(r['closest_m'] for r in results):.3f} m)")
sys.exit(1 if bad else 0)
