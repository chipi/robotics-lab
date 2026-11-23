"""Challenge 21, ten goals in a row on one reset (RFC-0008): the navigator goes to each goal in turn, nothing reset between
them, so the belief's drift builds up. Judged by truth at each goal (reached within the phase 1 tolerance), by the judge's
invariants over the whole run, and the belief's error against the truth is recorded at each goal, in position and in
heading (a heading belief off by tens of degrees puts every remembered obstacle in the wrong place).
"""

import math

from labrunner.judge import Judge
from labrunner.scene import Scene
from labrunner.frames import compose, inverse


def run(nav, scene: Scene, truth, reached_m: float) -> list:
    """Visit scene.goals in order, each within scene.time_s; stop at the first goal not reached (the run after it would
    start from a place nobody planned). One row per goal tried: the status the navigator gave, the truth's distance to the
    goal, and the belief's distance and heading difference from the truth (both in the map frame, the truth put there by the
    start's transform), and what kind of place the goal is (beside a box, by the hole, in the open)."""
    map_from_world = compose(nav.loc.pose(), inverse(truth()))
    kinds = scene.notes.get("goal_kinds", [])
    rows = []
    for i, goal in enumerate(scene.goals, 1):
        began = truth()
        out = nav.go_to(compose(map_from_world, (goal[0], goal[1], 0.0))[:2], scene.time_s)
        here, belief = truth(), nav.loc.pose()
        in_map = compose(map_from_world, here)
        row = {"n": i, "goal": [round(goal[0], 3), round(goal[1], 3)], "kind": kinds[i - 1] if i <= len(kinds) else None,
               "status": out["status"], "why": out.get("why"), "error_m": round(math.dist(here[:2], goal), 3),
               "belief_error_m": round(math.dist(belief[:2], in_map[:2]), 3) if belief else None,
               "heading_error_deg": round(abs(math.degrees(math.remainder(belief[2] - in_map[2], math.tau))), 1) if belief else None,
               "leg_m": round(math.dist(began[:2], goal), 2)}
        row["reached"] = out["status"] == "reached" and row["error_m"] <= reached_m
        rows.append(row)
        nav.record(event="goal", **row)
        if not row["reached"]:
            break
    return rows


def _stat(values: list) -> dict:
    values = [v for v in values if v is not None]
    return {"mean": round(sum(values) / len(values), 3) if values else None, "max": round(max(values), 3) if values else None,
            "last": values[-1] if values else None}


def verdict(judge: Judge, scene: Scene, rows: list) -> dict:
    """PASS when every goal was reached by truth and no invariant broke. The belief's error is reported, not judged."""
    failed = judge.broken_failures()
    n = len(scene.goals)
    reached = sum(r["reached"] for r in rows)
    if reached < n:
        last = rows[-1] if rows else {"n": 1, "status": "none", "why": None, "error_m": None}
        failed.append(f"goal {last['n']} of {n}: " + (f"said reached {last['error_m']:.2f} m from it (over {judge.reached} m)"
                      if last["status"] == "reached" else f"{last['status']}" + (f": {last['why']}" if last["why"] else "")))
    return {"pass": not failed, "failed": failed, "status": "reached" if reached == n else (rows[-1]["status"] if rows else "none"),
            "why": None if reached == n or not rows else rows[-1]["why"],
            "error_m": round(max((r["error_m"] for r in rows if r["reached"]), default=0.0), 3),
            "reached": reached, "goals": rows,
            "belief_error_m": _stat([r["belief_error_m"] for r in rows]),
            "heading_error_deg": _stat([r["heading_error_deg"] for r in rows]),
            **judge.stats()}
