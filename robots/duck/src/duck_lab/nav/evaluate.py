"""Phase 1's test (RFC-0002 §3.4): go-to goals, each reached or refused, no contacts, all logged.

    uv run duck-eval --goals 20 --out runs/phase1     # simulator with mapd running
    uv run duck-eval --goals 20 --out runs/phase1 --miniview-data /work/robotics-lab/data   # goals are the miniview run's segments

The format 2 run (miniview, ADR-0014) is the record; ticks.jsonl is kept during the transition.

Goals are drawn once, with a fixed seed, from free floor in the apartment layout (sim/apartment_layout.json,
from MuJoCo): at least GOAL_CLEARANCE_M from every colliding geom and the staircase. Every goal starts
from the dock with an empty map (simreset.reset: the simulator restarted, mapd fresh), as the bar
says; --chain runs them one after another instead (run 4 did, by mistake: drift and failures carried
from goal to goal). Each goal is given in world coordinates
and converted to the map with the map ← world transform measured at the first fix.

Scored against the simulator's truth (the body server's trunk pose), not the navigator's belief:
- error: truth's distance to the goal when the navigator says "reached";
- clearance: the trunk centre's nearest distance to any colliding geom's footprint, every tick.
  "Contact" is clearance under FOOTPRINT_M. This is an approximation of MuJoCo's contact list,
  which the body server does not expose.
"""

import argparse
import json
import math
import random
import time
from pathlib import Path

from duck_lab.nav.frames import compose, inverse
from duck_lab.nav import simreset
from duck_lab.nav.run import Navigator
from duck_lab.nav.runlog import add_args, open_from_args

LAYOUT = Path(__file__).resolve().parents[3] / "sim" / "apartment_layout.json"
# The duck as the simulator models it (robots/duck/sim/measure_duck.py, STAND pose): 27.2 cm tall, every
# collision part within 8.3 cm of the trunk's centre in plan view. Pollen publishes ~25 cm tall,
# 14 cm wide, under 800 g; the model's extra 2 cm is the head in the standing pose.
DUCK_HEIGHT_M = 0.272
FOOTPRINT_M = 0.083       # the trunk centre closer than this to an obstacle's outline: a part can touch
FALLEN_Z_M = 0.06         # trunk height below this (standing: 0.116) is a fall; so is leaving the flat
APARTMENT = (-4.0, 4.0, -3.0, 3.0)
OVERHEAD_CLEAR_M = 0.30   # obstacles whose underside is higher than this pass over the duck's head
GOAL_CLEARANCE_M = 0.35
REACHED_M = 0.25          # truth within this of the goal counts as reached


def footprint_distance(p: tuple, g: dict) -> float:
    """2D distance from point p to a geom's footprint (box with yaw, or cylinder/sphere/capsule)."""
    dx, dy = p[0] - g["pos"][0], p[1] - g["pos"][1]
    if g["type"] == "box":
        c, s = math.cos(-g["yaw"]), math.sin(-g["yaw"])
        lx, ly = c * dx - s * dy, s * dx + c * dy
        return math.hypot(max(abs(lx) - g["size"][0], 0.0), max(abs(ly) - g["size"][1], 0.0))
    return max(math.hypot(dx, dy) - g["size"][0], 0.0)


def underside(g: dict) -> float:
    """Height of a geom's lowest point (boxes and cylinders by half-height, capsules and spheres by
    radius plus half-length)."""
    z = g["pos"][2]
    if g["type"] == "box":
        return z - g["size"][2]
    if g["type"] == "cylinder":
        return z - g["size"][1]
    if g["type"] == "capsule":
        return z - g["size"][1] - g["size"][0]
    return z - g["size"][0]


def obstacles(layout: dict, landmarks: bool = True) -> list:
    """Colliding geoms the duck can walk into: not the floors, not the stairs' treads (the hole is the
    cliff check's business, not a contact). With landmarks, also the per-room lm_* markers: visual only
    in the simulator, but the depth sensor sees them, so in this world they are things the duck would hit
    (RFC-0016; b7 ended three runs 3 cm from lm_office, uncounted)."""
    out = []
    for g in layout["geoms"]:
        name = g["name"]
        marker = landmarks and name.startswith("lm_")
        if (not g["collides"] and not marker) or g["type"] == "plane" or name.startswith("floor") or \
                name.startswith("stair"):
            continue
        if underside(g) > OVERHEAD_CLEAR_M:
            continue    # above the duck's head (a table top, a high shelf): it walks under it
        out.append(g)
    return out


def clearance(p: tuple, obs: list) -> tuple:
    best = min(obs, key=lambda g: footprint_distance(p, g))
    return footprint_distance(p, best), best["name"]


def draw_goals(layout: dict, n: int, seed: int = 1) -> list:
    # Phase 1's scope (RFC-0002 §3.4, revised): what the duck sees from the dock or on the way — the
    # office and the north corridor. Rooms behind walls it has not seen are phase 2's (exploring).
    floors = [g for g in layout["geoms"] if g["name"] in ("floor_office", "floor_cor_n")]
    obs = obstacles(layout, landmarks=False)      # phase 1's goals as they were drawn (comparable with old runs)
    rng = random.Random(seed)
    goals = []
    while len(goals) < n:
        f = rng.choices(floors, weights=[g["size"][0] * g["size"][1] for g in floors])[0]
        p = (f["pos"][0] + rng.uniform(-f["size"][0], f["size"][0]),
             f["pos"][1] + rng.uniform(-f["size"][1], f["size"][1]))
        stairs = [g for g in layout["geoms"] if g["name"].startswith("stair")]
        near_stairs = min((footprint_distance(p, s) for s in stairs), default=math.inf)
        if clearance(p, obs)[0] >= GOAL_CLEARANCE_M and near_stairs >= GOAL_CLEARANCE_M:
            goals.append((round(p[0], 2), round(p[1], 2), f["name"].removeprefix("floor_")))
    return goals


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--goals", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out", type=Path, default=Path("runs/phase1"))
    ap.add_argument("--chain", action="store_true", help="goal after goal, no reset (not the bar)")
    add_args(ap)
    args = ap.parse_args()
    layout = json.loads(LAYOUT.read_text())
    obs = obstacles(layout)
    goals = draw_goals(layout, args.goals, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    runlog = open_from_args(args, args.out.name, "go-to evaluation", args.out, evaluation=not args.chain)
    results = []
    nav = None

    def start():
        n_ = Navigator(log=args.out / "ticks.jsonl", runlog=runlog)
        if n_.loc.pose() is None and not n_.fix():
            n_.survey()
        return n_, compose(n_.loc.pose(), inverse(n_.body.pose()))

    try:
        if args.chain:
            nav, map_from_world = start()
        for i, (gx, gy, room) in enumerate(goals, 1):
            if not args.chain:
                if nav is not None:
                    nav.close()
                simreset.reset()
                nav, map_from_world = start()
            goal_map = compose(map_from_world, (gx, gy, 0.0))[:2]
            started = time.monotonic()
            ticks_before = sum(1 for _ in open(args.out / "ticks.jsonl")) if (args.out / "ticks.jsonl").exists() else 0
            out = nav.go_to(goal_map, args.timeout)
            ticks = [json.loads(l) for l in list(open(args.out / "ticks.jsonl"))[ticks_before:]]
            tr = [t["truth"] for t in ticks if "truth" in t]
            low = min((t["truth_z"] for t in ticks if "truth_z" in t), default=1.0)
            outside = any(not (APARTMENT[0] < p[0] < APARTMENT[1] and APARTMENT[2] < p[1] < APARTMENT[3])
                          for p in tr)
            near = min((clearance(p, obs) for p in tr), default=(math.inf, None))
            end = nav.body.pose()
            row = {"goal": i, "room": room, "world": [gx, gy], "map": [round(v, 3) for v in goal_map],
                   **out, "truth_end": [round(v, 3) for v in end[:2]],
                   "error_m": round(math.dist(end[:2], (gx, gy)), 3),
                   "min_clearance_m": round(near[0], 3), "nearest": near[1],
                   "contact": near[0] < FOOTPRINT_M, "wall_s": round(time.monotonic() - started, 1),
                   "lowest_trunk_m": round(low, 3), "fell": low < FALLEN_Z_M or outside}
            row["reached_truth"] = out["status"] == "reached" and row["error_m"] <= REACHED_M
            results.append(row)
            print(json.dumps(row), flush=True)
            if row["fell"]:
                print("ABORT: the duck fell (or left the apartment); the run stops here", flush=True)
                break
    finally:
        if nav is not None:
            nav.close()
        (args.out / "results.json").write_text(json.dumps(results, indent=1))
        if runlog:
            runlog.finish()
    n = len(results)
    said = sum(r["status"] == "reached" for r in results)
    true_ok = sum(r["reached_truth"] for r in results)
    refused = sum(r["status"] == "refused" for r in results)
    contacts = sum(r["contact"] for r in results)
    falls = sum(r["fell"] for r in results)
    # A stall (no progress for NO_PROGRESS_S) is a timeout found sooner: run 11's goal 20 stalled and was
    # not counted, so the bar read MET.
    timeouts = sum(r["status"] in ("timeout", "stalled") for r in results)
    bar = (n == args.goals and falls == 0 and contacts == 0 and timeouts == 0 and true_ok >= 18)
    print(f"PHASE1 goals {n}: navigator reached {said}, within {REACHED_M} m by truth {true_ok}, "
          f"refused {refused}, timeouts or stalls {timeouts}, goals with a contact {contacts}, falls {falls} — "
          f"bar {'MET' if bar else 'NOT MET'} (20 goals, 0 falls, 0 contacts, 0 timeouts or stalls, >= 18 within {REACHED_M} m)")


if __name__ == "__main__":
    main()
