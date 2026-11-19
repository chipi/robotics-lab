"""Challenges 22 and 23: the explorer in a challenge's scene, scored against the scene's own floors (RFC-0008).

The apartment's explorer (duck_lab.nav.explore_run.Explorer) runs as it is, without objects, for the scene's time budget.
Judged by truth: the judge's invariants over the run, how the run ended (explore_score's ENDS: `no_frontier_left` is the right
end, `trapped` and `aborted` fail, `time` is the budget running out), and the share of each room's reachable floor
(floor.py) that mapd's grid knows, against COVERAGE_BAR; where there are two rooms, the duck's truth must have entered both.
"""

import json
from pathlib import Path

from duck_lab.challenge import floor
from duck_lab.challenge.judge import Judge
from duck_lab.challenge.scene import Scene
from duck_lab.nav.explore_run import Explorer
from duck_lab.nav.explore_score import ENDS, belief_score

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


def run(nav, scene: Scene, out_dir: Path) -> dict:
    """The explorer for the scene's budget; the run's start and its final map are written beside the run (start.json,
    map_grid.json: what explore_score reads). Returns the explorer's result and how it ended."""
    (out_dir / "start.json").write_text(json.dumps({"map": nav.loc.pose(), "truth": nav.body.pose(), "scale": nav.scale}))
    explorer = Explorer(nav, out_dir)
    result = explorer.run(scene.time_s / 60)
    ended = [e for e in explorer.events if e.get("event") in ENDS]
    return {**result, "end": ended[-1]["event"] if ended else "time", "end_s": ended[-1]["t"] if ended else None,
            "why": ended[-1].get("why") if ended else None}


def verdict(scene: Scene, judge: Judge, trail: Trail, out: dict, out_dir: Path) -> dict:
    grid = json.loads((out_dir / "map_grid.json").read_text())
    start = json.loads((out_dir / "start.json").read_text())
    cov = floor.coverage(scene, grid, start)
    failed = judge.broken_failures()
    if out["end"] in ("trapped", "aborted") and not (out["end"] == "aborted" and judge.broken):
        failed.append(f"ended {out['end']}" + (f": {out['why']}" if out.get("why") else ""))
    for name, share in cov["areas"].items():
        if share < COVERAGE_BAR:
            failed.append(f"coverage of {name} {share:.0%}, under {COVERAGE_BAR:.0%}")
    if len(scene.areas) > 1:
        for a in scene.areas[1:]:
            if a.name not in trail.entered:
                failed.append(f"never entered {a.name}: the door not crossed")
    rows = [json.loads(line) for line in open(out_dir / "ticks.jsonl")]
    belief = belief_score(out_dir, rows)
    return {"pass": not failed, "failed": failed, "status": out["end"], "why": out.get("why"), "error_m": None,
            "end": out["end"], "end_s": out["end_s"], "legs": out["legs"], "coverage": cov, "bar": COVERAGE_BAR,
            "entered": trail.entered, "belief_error_m": {"mean": belief["mean_m"], "max": belief["max_m"], "last": belief["final_m"]},
            **judge.stats()}
