"""Replay the fix gate on recorded runs, old against new (K26): the gate before the loop-closure change (from git, never
re-implemented: `git show <rev>:.../frames.py` is executed as it was) and the gate as it is in the tree.

Every recorded `fix` event (a run records the held ones, the first three and every twentieth, and every taken fix that moved the
belief more than record_m) is replayed alone through both gates: a Localizer built the way the plugin builds it, seeded so its
belief is the event's `before` (the landmarks' offset too: `after` minus the raw pose), then the event's raw pose at its odometry
instant, with mapd's loop closure as the event says it was (`trusted`, the old record of it). The two decisions and the belief
after (and its distance to the simulator's truth) are printed for every event where they differ, and the counts for all. Fixes
that moved the belief less than record_m were not recorded: a replay of the sequence between the recorded ones is not possible.

For each recorded loop closure, the landmarks' side: the run's sightings go through the relocaliser as they were up to the closure
(anchors are made as in the run); after it each sighting is placed as the closure's frame places the duck (the recorded pose, less
the landmarks' own corrections the run then made, which the held belief would not have had) and judged by Relocaliser.probe and
agreement with profile localisation.closure.agree_m. The belief after the closure, held, is the closure undone on the recorded
ticks (only while mapd's frame stays where the closure put it: the odometry is not recorded, so no longer than the first
--window seconds).

Run: cd robots/duck && uv run python sim/probes/closure_replay.py --old-rev 5c4322b <run folder or a folder of runs>..."""

import argparse
import math
import subprocess
import sys
import types
from pathlib import Path

import legacy_rows

from duck_lab.nav import frames as new_frames
from duck_lab.nav.frames import compose, inverse
from duck_lab.profile import load as load_profile
from worldmodel.objects import load_kinds
from worldmodel.relocalise import Relocaliser
from worldmodel.semantic_map import Detection, SemanticMap

REPO = Path(__file__).resolve().parents[4]
FRAMES = "robots/duck/src/duck_lab/nav/frames.py"
LOC = load_profile("sim").localisation


def old_frames(rev: str):
    """frames.py as it was at `rev`, executed as a module of its own."""
    src = subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{FRAMES}"], check=True, capture_output=True, text=True).stdout
    mod = types.ModuleType("frames_old")
    exec(compile(src, f"{rev}:{FRAMES}", "exec"), mod.__dict__)
    return mod


def runs_in(paths) -> list:
    out = []
    for p in map(Path, paths):
        out += [p] if (p / "run.mcap").exists() else sorted(q for q in p.iterdir() if (q / "run.mcap").exists())
    return out


def seeded(mod, ev: dict):
    """A Localizer as the plugin builds it, whose belief is the event's `before` and whose offset is the one it had."""
    loc = mod.Localizer(LOC.fix, history=10, max_jump_m=LOC.fix.jump_m, hold_n=None)
    t, odom = ev["odom_t_ns"], tuple(ev["odom"])
    loc.on_odom(t, odom)
    if ev.get("before") is not None:
        loc.on_fix(t, tuple(ev["before"]))
        loc.offset = (ev["after"][0] - ev["raw"][0], ev["after"][1] - ev["raw"][1])
    return loc


def replay_event(mod, ev: dict, closure: bool, new: bool) -> tuple:
    """(status, belief after as (x, y, yaw)) of one recorded fix event through the gate in `mod`."""
    loc = seeded(mod, ev)
    reason = "loop closure" if closure else None
    kw = {"closure": reason} if new else {"trust": reason}
    loc.on_fix(ev["t_ns"], tuple(ev["raw"]), **kw)
    return loc.last_fix["status"], compose(loc.map_from_odom, tuple(ev["odom"]))


def error(pose, truth) -> float | None:
    return None if truth is None else math.dist(pose[:2], truth[:2])


def all_events(runs, old) -> None:
    n = same_as_record = changed = 0
    for run in runs:
        _, rows = legacy_rows.load(run)
        fixes = [r for r in rows if r.get("event") == "fix" and r.get("odom_t_ns") is not None]
        for ev in fixes:
            closure = bool(ev.get("trusted"))
            o_status, o_after = replay_event(old, ev, closure, new=False)
            n_status, n_after = replay_event(new_frames, ev, closure, new=True)
            n += 1
            same_as_record += o_status == ev["status"]
            if o_status != ev["status"]:
                print(f"NOT REPRODUCED {run.name} t={ev['t']:.1f}: recorded {ev['status']}, the old gate says {o_status} (moved {ev['moved_m']} m)")
            if (o_status, [round(v, 4) for v in o_after]) != (n_status, [round(v, 4) for v in n_after]):
                changed += 1
                tr = ev.get("truth")
                print(f"CHANGED {run.name} t={ev['t']:.1f}: moved {ev['moved_m']} m; recorded {ev['status']}"
                      f"{' (' + ev['trusted'] + ')' if closure else ''}; old {o_status} belief err "
                      f"{error(o_after, tr):.2f} m; new {n_status} belief err {error(n_after, tr):.2f} m")
        if fixes:
            print(f"{run.name}: {len(fixes)} recorded fix events")
    print(f"\n{n} fix events in {len(runs)} runs: the old gate reproduces the recorded status in {same_as_record}; "
          f"{changed} decisions changed between old and new")


def offset_at(rows_before: list, t: float) -> tuple:
    """The landmarks' running correction at t from the run's relocalise events (their `offset` after the nudge), halving in offset_half_s."""
    off, at = (0.0, 0.0), 0.0
    for r in rows_before:
        if r["t"] > t:
            break
        if r.get("event") == "relocalise" and r.get("status") == "corrected":
            off, at = tuple(r["offset"]), r["t"]
    k = 0.5 ** ((t - at) / LOC.fix.offset_half_s)
    return off[0] * k, off[1] * k


def closure_runs(runs, old, window_s: float) -> None:
    for run in runs:
        _, rows = legacy_rows.load(run)
        closures = [r for r in rows if r.get("event") == "fix" and r.get("trusted")]
        for ev in closures:
            tc, truth = ev["t"], ev["truth"]
            o_status, o_after = replay_event(old, ev, True, new=False)
            loc = seeded(new_frames, ev)
            loc.on_fix(ev["t_ns"], tuple(ev["raw"]), closure="loop closure")
            n_status = loc.last_fix["status"]
            h = loc.closure_frame()
            before = tuple(ev["before"])
            print(f"\n{run.name}: loop closure at t={tc:.2f} s, mapd's pose moves the belief {ev['moved_m']} m and "
                  f"{math.degrees(abs(math.atan2(math.sin(ev['after'][2] - before[2]), math.cos(ev['after'][2] - before[2])))):.0f} deg")
            print(f"  old gate: {o_status}; belief error {error(before, truth):.2f} m -> {error(o_after, truth):.2f} m")
            print(f"  new gate: {n_status}; belief error {error(before, truth):.2f} m -> {error(before, truth):.2f} m (the belief stays); "
                  f"the closure pending: {loc.closure_pending()}")

            ticks = [r for r in rows if "pose" in r and "truth" in r and "event" not in r and tc <= r["t"] <= tc + window_s]
            if ticks:
                old_e = [error(r["pose"], r["truth"]) for r in ticks]
                held_e = [error(compose(inverse(h), tuple(r["pose"])), r["truth"]) for r in ticks]
                print(f"  the {window_s:.0f} s after it: belief error old max {max(old_e):.2f} m mean {sum(old_e) / len(old_e):.2f} m; "
                      f"new (the closure undone on the recorded ticks) max {max(held_e):.2f} m mean {sum(held_e) / len(held_e):.2f} m")
            after = [r for r in rows if "pose" in r and "truth" in r and "event" not in r and r["t"] > tc]
            if after:
                e = [error(r["pose"], r["truth"]) for r in after]
                print(f"  old, to the end of the run: error mean {sum(e) / len(e):.2f} m max {max(e):.2f} m (recorded)")

            sm = SemanticMap(load_kinds())
            rel = Relocaliser(sm, numbers=LOC.landmarks)
            window, verdicts, taken_at = [], [], None
            for r in rows:
                if r.get("event") != "sighting":
                    continue
                found = [Detection(s["kind"], s["x"], s["y"], s["radius"], s["z0"], s["z1"], s["range_m"], s["confidence"], s["source"])
                         for s in r["seen"]]
                if r["t"] <= tc:
                    rel.observe(found, tuple(r["pose"]), r["t"])
                    sm.integrate(found, tuple(r["pose"]), r["t"])
                    continue
                if taken_at is not None:
                    break
                off = offset_at(rows, r["t"])
                hyp = (r["pose"][0] - off[0], r["pose"][1] - off[1], r["pose"][2])
                window = rel.probe(found, hyp, r["t"], window)
                v = rel.agreement(window, LOC.closure.agree_m)
                if v is None:
                    continue
                window = window[-1:] if v["status"] == "refused" else []
                verdicts.append((r["t"], v))
                if v["status"] == "agrees" and loc.accept_closure() is not None:
                    taken_at = r["t"]
            print(f"  anchors at the closure: {len(sm.anchors)} ({sorted(sm.anchors)})")
            if not verdicts:
                print("  landmarks: no verdict in the run (fewer than min_n anchored sightings in any window); the closure stays held")
            for t, v in verdicts:
                print(f"  landmarks: t={t:.1f} {v['status']}: n={v['n']} median {v['median']} (|{math.hypot(*v['median']):.2f}| m, agree within "
                      f"{v['agree_m']}), spread {v['spread_m']}, {v['landmarks']}")
            print(f"  new gate: {'taken at t=%.1f' % taken_at if taken_at else 'held to the end of the run'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old-rev", required=True, help="the commit whose frames.py is the old gate")
    ap.add_argument("--window", type=float, default=15.0)
    ap.add_argument("--events-only", action="store_true", help="only the old-against-new decisions over the recorded fix events")
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    runs = runs_in(a.runs)
    old = old_frames(a.old_rev)
    all_events(runs, old)
    if not a.events_only:
        closure_runs(runs, old, a.window)
    sys.exit(0)
