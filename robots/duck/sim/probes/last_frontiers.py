"""Why an exploring run ended "no frontier left": the frontiers at its last pick (the recorded grid, pose, avoid list and
obstacle points), each cluster's size and centre in the world, how far it is from the nearest avoided point, and the
room it is in. Offline; the navigator's reachable() (lethal cells, floor seen near the target) is not replayed.

    .venv/bin/python sim/probes/last_frontiers.py runs/explore-b6-r1
"""

import json
import math
import sys
from pathlib import Path

from duck_lab.nav import explore
from duck_lab.nav.explore_score import room_of


def main() -> None:
    run = Path(sys.argv[1])
    picks = [e for e in map(json.loads, (run / "ticks.jsonl").open()) if e.get("event") == "pick"]
    p = picks[-1]
    clusters = explore.frontiers(p["grid"], p["scale"], obstacles=[tuple(o) for o in p["obstacles"]])
    avoid = [tuple(a) for a in p["avoid"]]
    # avoid = the explorer's failed targets + the navigator's drops (explore_run.run); the last world event's drops
    # (drops + edges) tell the drops apart
    worlds = [e for e in map(json.loads, (run / "ticks.jsonl").open()) if e.get("event") == "world" and e["t"] <= p["t"]]
    drops = {tuple(round(v, 2) for v in d) for d in (worlds[-1]["drops"] if worlds else [])}
    is_drop = [tuple(round(v, 2) for v in a) in drops for a in avoid]
    print(f"avoided: {sum(is_drop)} drop points, {len(avoid) - sum(is_drop)} failed targets or other: "
          f"{[a for a, d in zip(avoid, is_drop) if not d][:12]}")
    print(f"{run.name}: last pick at t {p['t']:.0f} s, pose {p['pose']}, target {p['target']}, "
          f"{len(clusters)} frontier clusters, {len(avoid)} avoided points (AVOID_M {explore.AVOID_M})")
    # the old run's avoid list mixed failed targets and retired frontier cells (before explore.without_retired):
    # targets are the legs' targets; the rest were retired cells
    leg_rows = [e for e in map(json.loads, (run / "ticks.jsonl").open()) if e.get("event") == "leg" and e["t"] <= p["t"]]
    legs = [tuple(e["target"]) for e in leg_rows]
    failed = [a for a in avoid if any(math.dist(a, t) < 0.02 for t in legs)]
    reached = [tuple(e["target"]) for e in leg_rows if e["status"] == "reached"]
    only_failed = [a for a in failed if not any(math.dist(a, t) < 0.02 for t in reached)]
    usable_if = sum(1 for c in explore.without_retired(clusters, p.get("retired") or []) for q in c
                    if all(math.dist(q, a) >= explore.AVOID_M for a in only_failed)
                    and all(math.dist(q, t) >= explore.STANDOFF_M for t in reached)
                    and math.dist(q, p["pose"][:2]) >= explore.MIN_DIST_M)
    print(f"of the {len(failed)} avoided targets {len(reached)} were reached; if reached ones kept only "
          f"STANDOFF_M {explore.STANDOFF_M} m: {usable_if} usable cells")
    retired = p.get("retired") or [a for a in avoid if a not in failed]
    new = explore.without_retired(clusters, retired)
    usable = sum(1 for c in new for q in c if all(math.dist(q, a) >= explore.AVOID_M for a in failed)
                 and math.dist(q, p["pose"][:2]) >= explore.MIN_DIST_M)
    target = explore.pick(new, tuple(p["pose"]), failed)
    print(f"the new rule: {len(failed)} failed targets (AVOID_M), {len(retired)} retired cells (RETIRED_M "
          f"{explore.RETIRED_M}); {len(new)} clusters, {usable} usable cells; pick -> {target} "
          f"(reachable() not replayed)")
    for c in sorted(clusters, key=len, reverse=True):
        cx, cy = sum(q[0] for q in c) / len(c), sum(q[1] for q in c) / len(c)
        near = min((math.dist((cx, cy), a) for a in avoid), default=float("inf"))
        free = sum(1 for q in c if all(math.dist(q, a) > explore.AVOID_M for a in avoid))
        by_drop = sum(1 for q in c if any(math.dist(q, a) <= explore.AVOID_M for a, d in zip(avoid, is_drop) if d))
        print(f"  {len(c):4d} cells at ({cx:.2f}, {cy:.2f}) map, room (map frame) {room_of((cx, cy))}; nearest avoided {near:.2f} m; "
              f"cells outside AVOID_M of any avoided point: {free}, within AVOID_M of a drop point: {by_drop}")


if __name__ == "__main__":
    main()
