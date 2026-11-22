"""Phase 1's test (RFC-0002 §3.4): go-to goals, each reached or refused, no contacts, all logged.

    uv run lab-eval --goals 20 --out runs/phase1 --miniview-data /work/robotics-lab/data   # the run is the record

The format 2 run (Observatory, ADR-0014) is the record; ticks.jsonl is kept during the transition.

Goals are drawn once, with a fixed seed, from free floor in the apartment layout (sim/apartment_layout.json,
from MuJoCo): at least GOAL_CLEARANCE_M from every colliding geom and the staircase. Every goal starts
from the dock with an empty map (the host's reset, simhost.reset: the simulator restarted, mapd fresh), as the bar
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

from labrunner import robots
from labrunner.cli import add_args
from labrunner.frames import compose, inverse
from labrunner.geometry import (FALLEN_Z_M, FOOTPRINT_M, GOAL_CLEARANCE_M, GOALS, LAYOUT, REACHED_M, clearance,
                                footprint_distance, obstacles)
from runfile import keys, scenefile
from runfile.catalog import default_data


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
    ap.add_argument("--goals-file", type=Path, default=GOALS, help="the fixed goals (default: phase 1's 20)")
    ap.add_argument("--draw", action="store_true", help="draw goals from the layout instead (--goals, --seed)")
    ap.add_argument("--goals", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out", type=Path, default=Path("runs/phase1"))
    ap.add_argument("--chain", action="store_true", help="goal after goal, no reset (not the bar)")
    ap.add_argument("--host", help="the host file (RFC-0021; default $ROBOTICS_LAB_HOST, else ~/.config/robotics-lab/host.json)")
    add_args(ap)
    args = ap.parse_args()
    import simhost
    robots.select(args.robot)
    host = simhost.load(args.host)
    x0, x1, y0, y1 = scenefile.load(args.scene).bounds    # outside the scene's bounds is a fall
    layout = json.loads(LAYOUT.read_text())
    obs = obstacles(layout)
    if args.draw:
        goals = draw_goals(layout, args.goals, args.seed)
    else:
        goals = [tuple(g) for g in json.loads(args.goals_file.read_text())["goals"]]
        args.goals = len(goals)
    args.out.mkdir(parents=True, exist_ok=True)
    data = args.miniview_data or default_data()
    if data is None:
        raise SystemExit("no Observatory data folder (--miniview-data or OBSERVATORY_DATA): the evaluation's record is its run")
    # The navigator is a payload (RFC-0021 step 2): a process per goal (a reset simulator, a new map), given only the
    # robot's sockets; the runner here reads the truth, scores each goal, and copies the goals' runs into one official run.
    from labrunner.remote import Remote
    from runfile.truthcopy import TruthLog
    from simhost.truth import Sampler
    name = args.run or args.out.name
    key = keys.make_key(robots.get().NAME, args.scene, name)
    if keys.run_dir(Path(data), key).exists():
        raise SystemExit(f"cannot write the Observatory run: {key} exists")
    truth_log = TruthLog(args.out / "truth.jsonl")
    results = []
    nav = sampler = copy = None
    samples = []

    def watch(s) -> None:
        truth_log.add(s.wall_ns, s.pose, s.z, s.quat)
        samples.append(s)

    def start(i: int):
        """A reset simulator, the truth sampled, a payload for this goal (all goals in one, with --chain)."""
        nonlocal sampler, copy
        simhost.reset(host)
        sampler = Sampler(host, on_sample=watch).start()
        n_ = Remote(host, args.out, args.scene, f"{name}-g{i}", Path(data), key, truth_log, copy=copy,
                    run={"kind": "go-to evaluation"})
        copy = n_.copy
        pose = n_.localise()
        return n_, compose(pose, inverse(sampler.latest.pose)) if pose is not None else None

    try:
        if args.chain:
            nav, map_from_world = start(1)
        for i, (gx, gy, room) in enumerate(goals, 1):
            if not args.chain:
                if nav is not None:
                    nav.close(finish=False)
                    sampler.stop()
                nav, map_from_world = start(i)
            started = time.monotonic()
            samples.clear()
            if map_from_world is None:
                goal_map, out = (gx, gy), {"status": "refused", "why": "no pose on the map after the survey"}
            else:
                goal_map = compose(map_from_world, (gx, gy, 0.0))[:2]
                out = nav.go_to(goal_map, args.timeout)
            tr = [s.pose for s in samples]
            low = min((s.z for s in samples), default=1.0)
            outside = any(not (x0 < p[0] < x1 and y0 < p[1] < y1)
                          for p in tr)
            near = min((clearance(p, obs) for p in tr), default=(math.inf, None))
            end = sampler.latest.pose
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
        if sampler is not None:
            sampler.stop()
        if nav is not None:
            nav.close()             # the last goal's run copied, then the official run ends
        truth_log.close()
        (args.out / "results.json").write_text(json.dumps(results, indent=1))
    if copy is not None:
        print(f"Observatory run {key}: {copy.sources} payload runs, ticks {copy.stats()}", flush=True)
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
