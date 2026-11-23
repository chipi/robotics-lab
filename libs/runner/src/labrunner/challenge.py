"""Run a challenge N times on its generated scenes, judged by truth, and report its pass rate (RFC-0008 step 1, ADR-0015).

    uv run lab-challenge 1 --runs 10                       # into $OBSERVATORY_DATA (the lab data folder)
    uv run lab-challenge 8 --runs 3 --seed 5 --miniview-data /work/robotics-lab/data
    uv run lab-challenge 22 --runs 3 --miniview-data /work/robotics-lab/data

Each run: the seed's scene written (the simulator's file under the host's scenarios folder, Observatory's scene in the data
folder), the simulator restarted on it (~40 s), a navigator given the goal, every truth sample checked against the
invariants (the first one broken is an `invariant` event in the run), and the outcome judged. Every run is an Observatory run,
`<robot>/<scene id>/<run>` (`duck/...` for the duck), with its room. The simulator is stopped at the end (--keep-up leaves it).

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
import shlex
import sys
import time
from datetime import datetime
from pathlib import Path

from labrunner import explore, robots, sequence
from labrunner.challenges import CHALLENGES, build
from labrunner.judge import Judge
from labrunner.remote import Remote
from labrunner.scene import miniview_scene, mjcf
from labrunner.frames import compose, inverse
from runfile import keys
from runfile.catalog import default_data
from runfile.truthcopy import TruthLog
import simhost
from simhost.truth import RTF_LOW, Sample, Sampler

STOPS = ("fall", "bounds")     # invariants after which the run cannot mean anything more: the navigator is stopped


def floats(n: int):
    """An argparse type: n comma-separated numbers."""
    def parse(s: str) -> tuple:
        v = tuple(float(x) for x in s.split(","))
        if len(v) != n:
            raise argparse.ArgumentTypeError(f"{n} numbers, comma separated: {s!r}")
        return v
    return parse


def one(host: simhost.Host, challenge: str, seed: int, data: Path, out: Path, payload: list | None = None,
        start: tuple | None = None, goal: tuple | None = None) -> dict:
    """One challenge run, the navigator as a payload process (RFC-0021 §3): it gets the robot's sockets and nothing else;
    the runner reads the truth (its own sampler), judges, and writes the official run with the truth put in (runner.Remote,
    runfile.truthcopy). `start` and `goal`: a probe of one moment of a seed's run (challenges.build)."""
    scene = build(challenge, seed, start=start, goal=goal)
    path = mjcf(scene, host.scenarios, host.scene_dir)
    sc = data / "scenes" / scene.id / "scene.json"
    sc.parent.mkdir(parents=True, exist_ok=True)
    sc.write_text(json.dumps(miniview_scene(scene), separators=(",", ":")))
    name = datetime.now().strftime("run-%Y%m%d-%H%M%S")
    run_out = out / scene.id / name
    run_out.mkdir(parents=True, exist_ok=True)
    key = keys.make_key(robots.get().NAME, scene.id, name)
    simhost.reset(host, str(path))
    judge = Judge(scene)
    trail = explore.Trail(scene)
    truth_log = TruthLog(run_out / "truth.jsonl")
    nav = sampler = None
    t0 = time.monotonic()
    try:
        sampler = Sampler(host).start()
        nav = Remote(host, run_out, scene.id, name, data, key, truth_log, payload=payload, scene_file=sc)

        route = {"checks": 0, "max": None}       # the payload's connections to the truth's port, looked at every 2 s

        def watch(s: Sample) -> None:
            truth_log.add(s.wall_ns, s.pose, s.z, s.quat)
            if sampler.samples % 40 == 1:
                n = nav.truth_connections(host.truth_port)
                if n is not None:
                    route["checks"] += 1
                    route["max"] = max(route["max"] or 0, n)
            trail.see(s.t, s.pose)
            broken = judge.check(s.t, s.pose, s.z)
            if not broken:
                return
            if broken["rule"] in STOPS:
                nav.break_goal(broken["rule"], broken["why"])
            nav.record(event="invariant", rule=broken["rule"], why=broken["why"])
        sampler.on_sample = watch
        truth = lambda: sampler.latest.pose  # noqa: E731 - at most a sample period old: the duck stands at each use
        pose = nav.localise()
        if pose is None:
            out_ = {"status": "refused", "why": "no pose on the map after the survey"}
            verdict = judge.verdict(out_, truth())
        elif scene.mode == "sequence":
            verdict = sequence.verdict(judge, scene, sequence.run(nav, scene, truth, judge.reached))
        elif scene.mode == "explore":
            (run_out / "start.json").write_text(json.dumps({"map": list(pose), "truth": truth(), "scale": nav.scale}))
            result = nav.explore(scene.time_s / 60)
            rows = with_truth([json.loads(line) for line in open(run_out / "ticks.jsonl")], truth_log)
            verdict = explore.verdict(scene, judge, trail, result, run_out, rows)
        else:
            map_from_world = compose(pose, inverse(truth()))
            out_ = nav.go_to(compose(map_from_world, (scene.goal[0], scene.goal[1], 0.0))[:2], scene.time_s)
            verdict = judge.verdict(out_, truth())
        if sampler.error:
            verdict = {**verdict, "pass": False, "failed": verdict["failed"] + [f"the truth sampler stopped: {sampler.error}"]}
        verdict = clocked(verdict, sampler.rtf_low())
        nav.record(event="judged", why=f"NO VERDICT, {verdict['no_verdict']}" if verdict.get("no_verdict") else "PASS" if verdict["pass"] else "; ".join(verdict["failed"]))
    finally:
        if sampler is not None:
            sampler.stop()
        if nav is not None:
            nav.close()
        truth_log.close()
    copy = nav.copy.stats() if nav is not None else None
    row = {"challenge": challenge, "seed": seed, "scene": scene.id, "run": key, "right": scene.right,
           "goal": list(scene.goal), "jitter": [round(v, 4) for v in scene.jitter], "notes": scene.notes, **verdict,
           "truth_hz": round(sampler.samples / max(time.monotonic() - t0, 1e-9), 1) if sampler else None,
           "rtf": sampler.rtf() if sampler else None, "clock": sampler.clock() if sampler else None, "truth_copy": copy, "payload": "process",
           "payload_truth_connections": route if nav is not None else None}
    (run_out / "result.json").write_text(json.dumps(row, indent=1))
    return row


def clocked(verdict: dict, low: dict | None) -> dict:
    """The verdict, or none (`pass` None) when the simulator ran under the real-time factor RTF_LOW (`low` is its clock, simhost.truth.Sampler.rtf_low):
    timing, timeouts and the truth pairing are not what they say (RFC-0025 question 7)."""
    return {**verdict, "pass": None, "no_verdict": f"rtf_low: {low['rtf']} under {RTF_LOW}"} if low else verdict


def with_truth(rows: list, log: TruthLog) -> list:
    """The navigator's rows with the runner's truth put in by wall clock, for the scores that read rows (explore_score)."""
    out = []
    for r in rows:
        s = log.nearest(r["wall_ns"]) if isinstance(r.get("wall_ns"), int) else None
        out.append({**r, "truth": s["pose"]} if s and "event" not in r else r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("challenge", choices=sorted(CHALLENGES))
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1, help="the first seed; run i uses seed + i")
    ap.add_argument("--miniview-data", type=Path, default=default_data())
    ap.add_argument("--out", type=Path, default=Path("runs/challenges"), help="per run: ticks.jsonl and result.json")
    ap.add_argument("--keep-up", action="store_true", help="leave the simulator running at the end")
    ap.add_argument("--host", help="the host file (RFC-0021; default $ROBOTICS_LAB_HOST, else ~/.config/robotics-lab/host.json)")
    ap.add_argument("--payload", help="the navigator to run, a command that keeps the payload contract (default: the robot's own)")
    ap.add_argument("--start", type=floats(3), help="x,y,yaw: a probe starts the duck here, named in the seed's world as a run of it "
                    "shows it (ticks, truth); every run then uses --seed itself")
    ap.add_argument("--goal", type=floats(2), help="x,y in the seed's world: a probe goes to this one goal (mode go), whatever the challenge")
    robots.add_robot_arg(ap)
    args = ap.parse_args()
    robots.select(args.robot)
    if args.miniview_data is None:
        raise SystemExit("no miniview data folder (--miniview-data or OBSERVATORY_DATA): every challenge run is a miniview run")
    host = simhost.load(args.host)
    probe = args.start is not None or args.goal is not None
    rows = []
    started = time.monotonic()
    try:
        for i in range(args.runs):
            row = one(host, args.challenge, args.seed + (0 if probe else i), args.miniview_data, args.out,
                      shlex.split(args.payload) if args.payload else None, start=args.start, goal=args.goal)
            rows.append(row)
            keys = ("scene", "run", "pass", "failed", "status", "error_m", "min_clearance_m", "min_drop_m")
            more = ("reached", "belief_error_m", "heading_error_deg", "coverage", "end", "entered", "no_verdict")      # challenges 21-23
            print(json.dumps({k: row[k] for k in keys + tuple(m for m in more if m in row)}), flush=True)
    finally:
        if not args.keep_up:
            simhost.down(host)
    n, ok = len(rows), sum(r["pass"] is True for r in rows)       # a run with no verdict (rtf_low) is neither
    summary = {"challenge": args.challenge, "runs": n, "passed": ok, "rate": round(ok / n, 3) if n else None,
               "minutes": round((time.monotonic() - started) / 60, 1), "failures": [(r["run"], r["failed"]) for r in rows if not r["pass"]]}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"ch{args.challenge}-summary.json").write_text(json.dumps({"summary": summary, "runs": rows}, indent=1))
    print(f"CHALLENGE {args.challenge}: {ok} of {n} passed ({summary['rate']:.0%}) in {summary['minutes']} min" if n else "no runs", flush=True)
    sys.exit(0 if n and ok == n else 1)


if __name__ == "__main__":
    main()
