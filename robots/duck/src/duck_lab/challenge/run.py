"""Run a challenge N times on its generated scenes, judged by truth, and report its pass rate (RFC-0008 step 1, ADR-0015).

    uv run duck-challenge 1 --runs 10                       # into $OBSERVATORY_DATA (the lab data folder)
    uv run duck-challenge 8 --runs 3 --seed 5 --miniview-data /work/robotics-lab/data
    uv run duck-challenge 22 --runs 3 --miniview-data /work/robotics-lab/data

Each run: the seed's scene written (the simulator's file under ~/.cache/duck-sim/scenarios, Observatory's scene in the data
folder), the simulator restarted on it (~40 s), a navigator given the goal, every truth sample checked against the
invariants (the first one broken is an `invariant` event in the run), and the outcome judged. Every run is an Observatory run,
`duck/<scene id>/<run>`, with its room. The simulator is stopped at the end (--keep-up leaves it).

Three challenges are not one goal to reach (RFC-0008 §3):
  21  ten goals in turn on one reset, one room with boxes and a hole, goals beside the boxes and the hole: every goal
      within 0.25 m by truth, no invariant broken; the belief's error (truth against belief), in position and in
      heading, is recorded at each goal.
  22  one room with a drop 0.5-0.8 m from the start, explored (the explorer, not go_to) for 5 minutes: safe, the room's
      reachable floor known to the map over the bar (explore.COVERAGE_BAR, 0.80, provisional), not ended trapped.
  23  two rooms joined by a door, explored for 8 minutes: as 22 for each room, and the door crossed.
Pass rates for these are over the same seeds the others use; a run's result.json has the goals, the coverage and the end.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from duck_lab.challenge import explore, sequence
from duck_lab.challenge.challenges import CHALLENGES, build
from duck_lab.challenge.judge import Judge
from duck_lab.challenge.scene import miniview_scene, mjcf
from duck_lab.nav import simreset
from duck_lab.nav.frames import compose, inverse
from duck_lab.nav.run import Navigator
from duck_lab.nav.runlog import RunLog
from runfile.catalog import default_data

STOPS = ("fall", "bounds")     # invariants after which the run cannot mean anything more: the navigator is stopped


def one(challenge: str, seed: int, data: Path, out: Path) -> dict:
    scene = build(challenge, seed)
    path = mjcf(scene)
    sc = data / "scenes" / scene.id / "scene.json"
    sc.parent.mkdir(parents=True, exist_ok=True)
    sc.write_text(json.dumps(miniview_scene(scene), separators=(",", ":")))
    name = datetime.now().strftime("run-%Y%m%d-%H%M%S")
    run_out = out / scene.id / name
    run_out.mkdir(parents=True, exist_ok=True)
    simreset.reset(str(path))
    runlog = RunLog(data, scene.id, name, "challenge", run_out)
    judge = Judge(scene)
    nav = None
    try:
        nav = Navigator(log=run_out / "ticks.jsonl", runlog=runlog)
        trail = explore.Trail(scene)

        def watch(row):
            trail.see(row["t"], row["truth"])
            broken = judge.check(row["t"], row["truth"], row.get("truth_z", 1.0))
            if not broken:
                return None
            if broken["rule"] in STOPS:
                nav.abort = f"invariant {broken['rule']}: {broken['why']}"
            return {"event": "invariant", "rule": broken["rule"], "why": broken["why"]}
        nav.watch = watch
        if nav.loc.pose() is None and not nav.fix():
            nav.survey()
        if nav.loc.pose() is None:
            out_ = {"status": "refused", "why": "no pose on the map after the survey"}
            verdict = judge.verdict(out_, nav.body.pose())
        elif scene.mode == "sequence":
            verdict = sequence.verdict(judge, scene, sequence.run(nav, scene))
        elif scene.mode == "explore":
            verdict = explore.verdict(scene, judge, trail, explore.run(nav, scene, run_out), run_out)
        else:
            map_from_world = compose(nav.loc.pose(), inverse(nav.body.pose()))
            out_ = nav.go_to(compose(map_from_world, (scene.goal[0], scene.goal[1], 0.0))[:2], scene.time_s)
            verdict = judge.verdict(out_, nav.body.pose())
        nav.record(event="judged", why="PASS" if verdict["pass"] else "; ".join(verdict["failed"]))
    finally:
        if nav is not None:
            nav.close()
        runlog.finish()
    row = {"challenge": challenge, "seed": seed, "scene": scene.id, "run": runlog.key, "right": scene.right,
           "goal": list(scene.goal), "jitter": [round(v, 4) for v in scene.jitter], "notes": scene.notes, **verdict}
    (run_out / "result.json").write_text(json.dumps(row, indent=1))
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("challenge", choices=sorted(CHALLENGES))
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1, help="the first seed; run i uses seed + i")
    ap.add_argument("--miniview-data", type=Path, default=default_data())
    ap.add_argument("--out", type=Path, default=Path("runs/challenges"), help="per run: ticks.jsonl and result.json")
    ap.add_argument("--keep-up", action="store_true", help="leave the simulator running at the end")
    args = ap.parse_args()
    if args.miniview_data is None:
        raise SystemExit("no miniview data folder (--miniview-data or OBSERVATORY_DATA): every challenge run is a miniview run")
    rows = []
    started = time.monotonic()
    try:
        for i in range(args.runs):
            row = one(args.challenge, args.seed + i, args.miniview_data, args.out)
            rows.append(row)
            keys = ("scene", "run", "pass", "failed", "status", "error_m", "min_clearance_m", "min_drop_m")
            more = ("reached", "belief_error_m", "heading_error_deg", "coverage", "end", "entered")      # challenges 21-23
            print(json.dumps({k: row[k] for k in keys + tuple(m for m in more if m in row)}), flush=True)
    finally:
        if not args.keep_up:
            simreset.down()
    n, ok = len(rows), sum(r["pass"] for r in rows)
    summary = {"challenge": args.challenge, "runs": n, "passed": ok, "rate": round(ok / n, 3) if n else None,
               "minutes": round((time.monotonic() - started) / 60, 1), "failures": [(r["run"], r["failed"]) for r in rows if not r["pass"]]}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"ch{args.challenge}-summary.json").write_text(json.dumps({"summary": summary, "runs": rows}, indent=1))
    print(f"CHALLENGE {args.challenge}: {ok} of {n} passed ({summary['rate']:.0%}) in {summary['minutes']} min" if n else "no runs", flush=True)
    sys.exit(0 if n and ok == n else 1)


if __name__ == "__main__":
    main()
