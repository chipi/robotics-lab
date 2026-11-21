"""Drive at the staircase on purpose: the cliff check must stop the duck before the edge.

Goal: the middle of the staircase opening (it must end refused or stopped short, never reached).
A truth guard (the body server's pose) aborts the run if the trunk centre comes within GUARD_M of the
opening, so a failing check cannot end in a fall. Run with the simulator and mapd up:
    robots/duck/.venv/bin/python robots/duck/sim/probes/cliff_test.py
"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from duck_lab.nav.frames import compose, inverse  # noqa: E402
import simhost
from duck_lab.nav.run import Navigator, host_links  # noqa: E402
from simhost.truth import Body  # noqa: E402 - the probe's own truth, to measure with (the navigator has none)

STAIRS = (-0.40, 0.00, -1.40, -0.70)   # x min, x max, y min, y max (apartment_layout.json)
GUARD_M = 0.05



def edge_distance(p):
    x0, x1, y0, y1 = STAIRS
    dx = max(x0 - p[0], 0, p[0] - x1)
    dy = max(y0 - p[1], 0, p[1] - y1)
    return (dx * dx + dy * dy) ** 0.5


RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runs")     # robots/duck/runs, wherever this is run from
os.makedirs(RUNS, exist_ok=True)
LOG = os.path.join(RUNS, "cliff-test.jsonl")
nav = Navigator(**host_links(simhost.load()), log=LOG)
truth = Body(simhost.load().truth_port)
closest = [9.0]


def guard():
    while not nav.abort:
        d = edge_distance(truth.pose()[:2])
        closest[0] = min(closest[0], d)
        if d < GUARD_M:
            nav.abort = f"truth guard: {d:.2f} m from the staircase opening"
        time.sleep(0.05)


try:
    if not nav.fix():
        nav.survey()
    map_from_world = compose(nav.loc.pose(), inverse(truth.pose()))
    threading.Thread(target=guard, daemon=True).start()
    goal = compose(map_from_world, (-0.2, -1.05, 0.0))[:2]
    out = nav.go_to(goal, 120.0)
    nav.abort = nav.abort or "done"
    end = truth.pose()
    print(json.dumps({"result": out, "truth_end": [round(v, 3) for v in end],
                      "closest_to_opening_m": round(closest[0], 3),
                      "cliff_stops": sum(1 for l in open(LOG) if '"cliff_stop"' in l)}))
finally:
    nav.close()
