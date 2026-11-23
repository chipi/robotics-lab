"""Replay the recoveries a batch recorded through the recovery choice as it was (from git) and as it is (K23/K24, b13 r3).

    robots/duck/.venv/bin/python robots/duck/sim/recovery_replay.py [--base REV] <run folders with ticks.jsonl> ...

Each `recovery` event holds what the choice was given: the attempt, the sensor's nearest_mm, a drop ahead, the hazard, and the memory's
room now and 0.1 m ahead. The choice at REV (default HEAD~1: the commit before the change, read with `git show`, not re-written)
must give the action the run took on every event (the faithfulness check), then the present one is asked of the same inputs. An
event whose action changes is shown with the truth's clearance (trunk centre to the nearest obstacle outline, the contact judge's
number) before it and after the move it made: what the old choice cost and the new one would not have spent.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from duck_lab.nav import recovery as new
from labrunner import geometry
from labrunner.geometry import clearance, obstacles

FOOTPRINT_M = geometry.profile().footprint.radius_m
LAYOUT = geometry.layout_path()
from duck_lab.profile import load

REPO = Path(__file__).resolve().parents[3]
SRC = "robots/duck/src/duck_lab/nav/recovery.py"


def old_module(rev: str):
    text = subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{SRC}"], check=True, capture_output=True, text=True).stdout
    tmp = Path(tempfile.mkdtemp()) / "recovery_old.py"
    tmp.write_text(text)
    spec = importlib.util.spec_from_file_location("recovery_old", tmp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inputs(ev: dict) -> tuple:
    haz = ev["hazard"]
    return ev["attempt"], ev["nearest_mm"], ev["drop_ahead"], (tuple(haz[0]), haz[1]) if haz else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="HEAD~1")
    ap.add_argument("runs", type=Path, nargs="+")
    args = ap.parse_args()
    old = old_module(args.base)
    prof = load("sim")
    pivot_obstacle_m = prof.footprint.lethal_m + prof.locomotion.pivot.obstacle_margin_m
    footprint = prof.footprint.radius_m
    obs = obstacles(json.loads(LAYOUT.read_text()))
    events = unfaithful = changed = 0
    lost_old = []
    for run in args.runs:
        rows = [json.loads(line) for line in open(run / "ticks.jsonl")]
        ticks = [r for r in rows if "pose" in r and "truth" in r and "event" not in r]
        for ev in (r for r in rows if r.get("event") == "recovery"):
            events += 1
            a, mm, front, haz = inputs(ev)
            creep_ok = old.creep_gains_room(ev["room_m"], ev["room_ahead_m"], pivot_obstacle_m)
            was = old.choose(a, mm, front, haz, creep_ok)
            if was != ev["action"]:
                unfaithful += 1
                print(f"UNFAITHFUL {run.name} t {ev['t']}: recorded {ev['action']}, the old choice gives {was}")
            now = new.choose(a, mm, front, haz, creep_ok, new.arc_room_ok(ev["room_m"], footprint))
            if now != was:
                changed += 1
                t = ev["t"]
                before = [x for x in ticks if t - 6 <= x["t"] <= t - 0.3]
                after = [x for x in ticks if x["t"] >= t - 0.05][:1]
                cb, ca = clearance(before[0]["truth"][:2], obs)[0], clearance(after[0]["truth"][:2], obs)[0]
                lost_old.append(cb - ca)
                print(f"CHANGED {run.name} t {t:7.1f} attempt {a}: {was} -> {now}; room {ev['room_m']:.3f} m, room ahead {ev['room_ahead_m']:.3f} m, "
                      f"the old arc moved {ev['moved_m']:.3f} m: truth clearance {cb:.3f} -> {ca:.3f} m (footprint {FOOTPRINT_M})")
    print(f"{events} recoveries in {len(args.runs)} runs; the old choice reproduces the recorded action on {events - unfaithful}; "
          f"the new one changes {changed} (arcs the room forbids -> the survey alone)")
    if lost_old:
        print(f"clearance the changed arcs spent: total {sum(lost_old):.3f} m, worst {max(lost_old):.3f} m")
    sys.exit(1 if unfaithful else 0)


if __name__ == "__main__":
    main()
