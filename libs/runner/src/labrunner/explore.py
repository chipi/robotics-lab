"""Challenges 22 and 23: the explorer in a challenge's scene, scored against the scene's own floors (RFC-0008).

The robot's explorer runs as it is, as a payload's explore goal without objects, for the scene's time budget.
Judged by truth: the judge's invariants over the run, how the run ended (explore_score's ENDS: `no_frontier_left` is the right
end, `trapped` and a stop (`stopped_by_guardrail`, `cancelled`) fail, `time` is the budget running out), and the share of each room's reachable floor
(floor.py) that mapd's grid knows, against COVERAGE_BAR; where there are two rooms, the duck's truth must have entered both.
"""

import json
from pathlib import Path

from labrunner import floor
from labrunner.judge import Judge
from labrunner.scene import Scene
from labrunner.explore_score import belief_score
from runfile.navcontract import STOPS

# The bar, set from the ten seeds of challenge 22 (RFC-0008 §3): the nine runs that did not end trapped knew 87.8-96.6 % of the
# room's reachable floor (median 92.1 %), the trapped one 65.4 %. 80 % sits 7.8 points under the lowest healthy run and 14.6
# over the trapped one. The scenes' own slack agrees: the floor within 0.2 m of a wall, a box or the drop is 25-33 % of the
# reachable floor (tests/test_challenge.py), floor the planner keeps off and the 8 x 8 sensor sees at a grazing angle.
COVERAGE_BAR = 0.80       # provisional: from the ten seeds of challenge 22 (RFC-0008 §3); challenge 23 has three seeds


class Trail:
    """Which of the scene's areas the duck's truth has been in, and when (the door is crossed when it is in the second)."""

    def __init__(self, scene: Scene):
        self.areas = scene.areas
        self.entered = {}

    def see(self, t: float, truth: tuple) -> None:
        for a in self.areas:
            if a.name not in self.entered and floor.in_area(truth[:2], a):
                self.entered[a.name] = round(t, 1)


def verdict(scene: Scene, judge: Judge, trail: Trail, out: dict, out_dir: Path, rows: list | None = None) -> dict:
    """`rows`: the navigator's rows with the truth in them; default its ticks.jsonl (a navigator that recorded the truth
    itself). A payload's rows have none: the runner puts its own in first (run.with_truth)."""
    grid = json.loads((out_dir / "map_grid.json").read_text())
    start = json.loads((out_dir / "start.json").read_text())
    cov = floor.coverage(scene, grid, start)
    failed = judge.broken_failures()
    # a stop the judge's own broken invariant caused is said once, by the invariant
    if out["end"] == "trapped" or (out["end"] in STOPS and not judge.broken):
        failed.append(f"ended {out['end']}" + (f": {out['why']}" if out.get("why") else ""))
    for name, share in cov["areas"].items():
        if share < COVERAGE_BAR:
            failed.append(f"coverage of {name} {share:.0%}, under {COVERAGE_BAR:.0%}")
    if len(scene.areas) > 1:
        for a in scene.areas[1:]:
            if a.name not in trail.entered:
                failed.append(f"never entered {a.name}: the door not crossed")
    if rows is None:
        rows = [json.loads(line) for line in open(out_dir / "ticks.jsonl")]
    belief = belief_score(out_dir, rows)
    return {"pass": not failed, "failed": failed, "status": out["end"], "why": out.get("why"), "error_m": None,
            "end": out["end"], "end_s": out["end_s"], "legs": out["legs"], "coverage": cov, "bar": COVERAGE_BAR,
            "entered": trail.entered, "belief_error_m": {"mean": belief["mean_m"], "max": belief["max_m"], "last": belief["final_m"]},
            **judge.stats()}
