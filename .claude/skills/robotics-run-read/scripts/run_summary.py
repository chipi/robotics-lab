#!/usr/bin/env python3
"""Summarise one run directory of the duck, read only: the verdict and judge, the build identity, the ticks with requested/applied,
the stops and guards that fired, and the belief against the truth where the run recorded one.

    run_summary.py robots/duck/runs/c22-ten/ch22-s6/run-20261119-113229
    run_summary.py robots/duck/runs/explore-b13-r1
    run_summary.py --data /work/robotics-lab/data DIR     # where run.mcap is looked up by the key in result.json
    run_summary.py --json DIR

A directory is a runner's folder (ticks.jsonl, with result.json / results.json / start.json beside it), or a data-folder run
(run.mcap, with source/ticks.jsonl for an import). A folder that holds several runs is listed, not summarised.
The run record in run.mcap (build, judge_profile, judge_truth, end verdict) is read when the `mcap` package is importable; the script
re-runs itself under apps/observatory/.venv when it is not. Standard library otherwise. Writes nothing.
Exit 0 summarised, 2 nothing to summarise."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
OBS_PYTHON = REPO / "apps" / "observatory" / ".venv" / "bin" / "python"
STOPS = ("reflex_stop", "cliff_stop", "stuck", "stalled", "trapped", "stopped_by_guardrail", "robot_guard", "held_off", "refused",
         "no_frontier_left", "recovery", "relocalise")
GUARDS = ("stopped_by_guardrail", "robot_guard")
NOT_RECORDED = "not recorded"


def installation_data() -> Path | None:
    f = Path(os.path.expanduser(os.environ.get("ROBOTICS_LAB_INSTALLATION") or "~/.config/robotics-lab/installation.json"))
    try:
        d = json.loads(f.read_text()).get("data")
    except (OSError, ValueError):
        return None
    return Path(os.path.expanduser(d)) if d else None


def find_runs(root: Path) -> list:
    """Directories at or under root (3 levels) that hold a ticks.jsonl or a run.mcap."""
    found = []
    for depth_glob in ("", "*/", "*/*/"):
        for marker in ("ticks.jsonl", "run.mcap", "source/ticks.jsonl"):
            found += [p.parent.parent if marker.startswith("source") else p.parent for p in root.glob(depth_glob + marker)]
        if found:
            break
    return sorted(set(found))


def jload(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def yaw_pair(a, b):
    """The rigid map->world transform that takes pose a (map) to pose b (truth): (dtheta, tx, ty) as a function."""
    dth = b[2] - a[2]
    c, s = math.cos(dth), math.sin(dth)
    tx = b[0] - (c * a[0] - s * a[1])
    ty = b[1] - (s * a[0] + c * a[1])
    return lambda p: (c * p[0] - s * p[1] + tx, s * p[0] + c * p[1] + ty)


def read_ticks(path: Path) -> dict:
    n_ticks = n_events = bad = 0
    events, first_t, last_t = Counter(), None, None
    first_of = {}
    requested = capped = 0
    max_vx = 0.0
    pairs = []          # (belief, truth) per tick that has both
    walled = []         # (belief, wall_ns) for a log whose truth is in truth.jsonl
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                bad += 1
                continue
            t = r.get("t")
            if "event" in r:
                n_events += 1
                events[r["event"]] += 1
                first_of.setdefault(r["event"], t)
                continue
            if "pose" not in r:
                continue
            n_ticks += 1
            first_t = t if first_t is None else first_t
            last_t = t
            rq, ap = r.get("requested"), r.get("applied")
            if rq is not None and ap is not None:
                requested += 1
                max_vx = max(max_vx, abs(ap.get("vx", 0.0)))
                if abs(rq.get("vx", 0.0) - ap.get("vx", 0.0)) > 1e-9 or abs(rq.get("vyaw", 0.0) - ap.get("vyaw", 0.0)) > 1e-9:
                    capped += 1
            if isinstance(r.get("wall_ns"), int) and len(r["pose"]) >= 3:
                walled.append((r["pose"], r["wall_ns"]))
            if r.get("truth") and len(r["truth"]) >= 3 and len(r["pose"]) >= 3:
                pairs.append((r["pose"], r["truth"]))
    return dict(ticks=n_ticks, events=n_events, bad_lines=bad, event_counts=dict(events), first_of=first_of, t0=first_t, t1=last_t,
                with_requested=requested, capped=capped, max_applied_vx=round(max_vx, 3), pairs=pairs, walled=walled)


def pair_with_truth_file(walled: list, path: Path) -> list:
    """Newer runs keep the truth in truth.jsonl (wall_ns, pose); each tick takes the sample nearest its wall_ns, within 100 ms."""
    if not walled or not path.exists():
        return []
    stamps, poses = [], []
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r.get("wall_ns"), int) and r.get("pose"):
                stamps.append(r["wall_ns"])
                poses.append(r["pose"])
    out = []
    for belief, ns in walled:
        i = bisect.bisect_left(stamps, ns)
        near = [j for j in (i - 1, i) if 0 <= j < len(stamps)]
        if near:
            j = min(near, key=lambda j: abs(stamps[j] - ns))
            if abs(stamps[j] - ns) <= 100_000_000:
                out.append((belief, poses[j]))
    return out


def belief_vs_truth(pairs: list, start: dict | None) -> dict | None:
    if not pairs:
        return None
    a, b = (start["map"], start["truth"]) if start and start.get("map") and start.get("truth") else pairs[0]
    to_world = yaw_pair(a, b)
    errs = []
    for p, q in pairs:
        x, y = to_world(p)
        errs.append(math.hypot(x - q[0], y - q[1]))
    return dict(samples=len(errs), mean_m=round(sum(errs) / len(errs), 3), max_m=round(max(errs), 3), last_m=round(errs[-1], 3),
                how="belief pose aligned to truth at the start, then compared tick by tick; a relocalise fix moves the map frame, so a later error can read high")


def read_mcap_record(path: Path) -> dict | None:
    try:
        from mcap.reader import make_reader
    except ImportError:
        if OBS_PYTHON.exists() and os.environ.get("RUN_SUMMARY_REEXEC") != "1":
            os.environ["RUN_SUMMARY_REEXEC"] = "1"
            os.execv(str(OBS_PYTHON), [str(OBS_PYTHON), *sys.argv])
        return {"unread": "the mcap package is not importable (apps/observatory/.venv is missing: make observatory-sync)"}
    out = {}
    try:
        with path.open("rb") as fh:
            for _, ch, msg in make_reader(fh).iter_messages(topics=["/miniview/run", "/miniview/end"]):
                d = json.loads(msg.data)
                if ch.topic == "/miniview/run":
                    out["run"] = {k: d.get(k) for k in ("key", "kind", "scene", "official", "started_at_source", "build", "judge_profile",
                                                        "judge_scene", "judge_truth", "goal_run")}
                else:
                    out["end"] = d
    except Exception as exc:        # a live or broken file: say so, do not guess
        out["unread"] = f"{type(exc).__name__}: {exc}"
    return out


def summarise(d: Path, data: Path | None) -> dict:
    s: dict = {"dir": str(d)}
    ticks = d / "ticks.jsonl"
    if not ticks.exists() and (d / "source" / "ticks.jsonl").exists():
        ticks = d / "source" / "ticks.jsonl"
    src = d / "source" if (d / "source").is_dir() and not (d / "ticks.jsonl").exists() else d
    result = jload(src / "result.json")
    results = jload(src / "results.json")
    start = jload(src / "start.json")
    t = read_ticks(ticks) if ticks.exists() else None

    mcap = None
    mcap_path = d / "run.mcap"
    if not mcap_path.exists() and result and data and result.get("run"):
        mcap_path = data / "runs" / result["run"] / "run.mcap"
    if mcap_path.exists():
        mcap = read_mcap_record(mcap_path)
        s["run_mcap"] = str(mcap_path)

    # verdict and judge
    v: dict = {}
    if result:
        v = {k: result.get(k) for k in ("challenge", "scene", "seed", "right", "pass", "failed", "status", "why", "error_m", "end",
                                         "end_s", "coverage", "min_clearance_m", "nearest", "min_drop_m", "lowest_trunk_m", "bar")
             if k in result}
        v["source"] = "result.json (the runner's judge: scores against the simulator's truth)"
    elif results is not None and isinstance(results, list):
        v = dict(goals=len(results), reached=sum(1 for g in results if g.get("status") == "reached"),
                 reached_by_truth=sum(1 for g in results if g.get("reached_truth")), fell=sum(1 for g in results if g.get("fell")),
                 contact=sum(1 for g in results if g.get("contact")), reflex_stops=sum(g.get("reflex_stops", 0) for g in results),
                 not_reached=[(g.get("goal"), g.get("status")) for g in results if g.get("status") != "reached"],
                 source="results.json (one row per goal)")
    elif t and "judged" in t["event_counts"]:
        v = {"source": "judged events in ticks.jsonl"}
    else:
        v = {"verdict": NOT_RECORDED, "source": "no result.json or results.json here: an explore run prints its result and scores it with "
             "labrunner.explore_score; this folder holds only the log. The end is the last of trapped / no_frontier_left / "
             "stopped_by_guardrail in the events below, else the clock ran out"}
    if mcap and mcap.get("end"):
        v["end_verdict_in_run_mcap"] = mcap["end"].get("verdict")
    s["verdict"] = v

    rec = (mcap or {}).get("run") or {}
    judge = {k: rec.get(k) for k in ("judge_profile", "judge_scene", "judge_truth") if rec.get(k)}
    if judge:
        s["judge"] = judge
    elif rec:
        s["judge"] = {"recorded": False, "note": "the run record has no judge_profile/judge_scene/judge_truth: written before they were recorded"}
    else:
        s["judge"] = {"recorded": False, "note": "judge_profile/judge_truth live in the run.mcap record; none was read "
                      "(no run.mcap found for this folder, or the mcap package is missing)"}
    if mcap and mcap.get("unread"):
        s["run_mcap_unread"] = mcap["unread"]

    # build identity: the run record first, result.json next
    build = rec.get("build") or (result or {}).get("build")
    s["build"] = build if build else {"recorded": False, "note": "no build field: the run was written before ebe0b8a (2026-11-26) "
                                      "or its record was not read; every reader treats it as absent"}

    if t:
        s["ticks"] = dict(count=t["ticks"], t_first=t["t0"], t_last=t["t1"], bad_lines=t["bad_lines"],
                          requested_applied=(dict(ticks_with_both=t["with_requested"], differ=t["capped"], max_applied_vx=t["max_applied_vx"])
                                             if t["with_requested"] else {"recorded": False, "note": "ticks carry no requested/applied: written before ebe0b8a"}))
        c = t["event_counts"]
        s["stops_and_guards"] = {k: dict(n=c[k], first_t=t["first_of"].get(k)) for k in STOPS if c.get(k)}
        s["guards_fired"] = [k for k in GUARDS if c.get(k)]
        enders = [(t["first_of"][k], k) for k in ("trapped", "no_frontier_left", "stopped_by_guardrail", "cancelled") if k in t["first_of"]]
        s["ended_by"] = max(enders)[1] if enders else "none of trapped / no_frontier_left / stopped_by_guardrail / cancelled: the clock ran out or the log was cut"
        s["events"] = dict(sorted(c.items(), key=lambda kv: -kv[1])[:12])
        pairs = t["pairs"] or pair_with_truth_file(t["walled"], d / "truth.jsonl")
        bt = belief_vs_truth(pairs, start)
        recorded = (result or {}).get("belief_error_m")
        s["belief_vs_truth"] = ({"recorded_by_runner": recorded, "recomputed": bt} if recorded else
                                bt or {"recorded": False, "note": "no tick carries a truth pose (a real robot, or a log without truth)"})
    else:
        s["ticks"] = {"recorded": False, "note": "no ticks.jsonl here (the log of a data-folder run is in run.mcap: use `observatory events|state <key>`)"}
    return s


def text(s: dict) -> str:
    out = [f"RUN {s['dir']}"]
    v = s["verdict"]
    out.append("VERDICT  " + json.dumps(v, ensure_ascii=False))
    out.append("JUDGE    " + json.dumps(s["judge"], ensure_ascii=False))
    out.append("BUILD    " + (s["build"]["id"] + ("  (dirty tree)" if s["build"].get("dirty") else "") if "id" in s["build"] else json.dumps(s["build"])))
    tk = s["ticks"]
    out.append("TICKS    " + json.dumps(tk))
    if "stops_and_guards" in s:
        out.append("STOPS    " + (json.dumps(s["stops_and_guards"]) if s["stops_and_guards"] else "none recorded"))
        if "pass" not in s["verdict"]:
            out.append("ENDED    " + s["ended_by"])
        out.append("GUARDS   " +(", ".join(s["guards_fired"]) if s["guards_fired"] else "none fired (stopped_by_guardrail, robot_guard absent)"))
        out.append("BELIEF   " + json.dumps(s["belief_vs_truth"]))
        out.append("EVENTS   " + json.dumps(s["events"]))
    if "run_mcap_unread" in s:
        out.append("MCAP     unread: " + s["run_mcap_unread"])
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir")
    ap.add_argument("--data", help="the data folder (default: `data` in the installation file) holding runs/<key>/run.mcap")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = Path(a.dir)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    runs = [root] if (root / "ticks.jsonl").exists() or (root / "run.mcap").exists() or (root / "source" / "ticks.jsonl").exists() else find_runs(root)
    if not runs:
        print(f"no ticks.jsonl or run.mcap at or under {root}", file=sys.stderr)
        return 2
    if len(runs) > 1:
        print(f"{root} holds {len(runs)} runs; name one:")
        for r in runs[:50]:
            print("  " + str(r))
        return 2
    s = summarise(runs[0], Path(a.data) if a.data else installation_data())
    print(json.dumps(s, indent=1, ensure_ascii=False) if a.json else text(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
