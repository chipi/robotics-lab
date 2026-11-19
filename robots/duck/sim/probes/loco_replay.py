"""Replay a recorded run's inputs through the locomotion code, old (the base commit's follow.step) and new (follow.step + DuckWalk.drive),
and compare with the logged commands.

For each tick of a run: the belief's pose, the plan in force, the logged command. The state of the follower is carried through the
run; the three flags the log does not keep (near, pivot_ok, close) are tried in every combination, and the first that gives the logged
command is committed (none: the tick is unexplained, and the follower carries on with near=False, pivot_ok=True, close from the
logged room). Old and new are run side by side on the same flags and must give the same Twist on every combination of every tick.

    python loco_replay.py RUN_DIR... --base /work/robotics-lab/p3-base --pivot-vx -0.06
"""

import argparse
import copy
import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower


TOL = 0.15      # rad/s: the logged pose is the one after the command; 3 cm of walking moves the heading error ~0.1 rad


def load_old(base: Path):
    spec = importlib.util.spec_from_file_location("old_follow", base / "robots/duck/src/duck_lab/nav/follow.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["old_follow"] = mod
    spec.loader.exec_module(mod)
    return mod


def ticks_of(run_dir: Path):
    recs = Follower(run_dir, keep_raw=True).poll()
    plan, room, rows = None, None, []
    events = []
    for t, k, p in recs:
        if k == "plan":
            plan = [tuple(q[:2]) for q in (p.get("path") or (p.get("raw") or {}).get("path") or [])]
            events.append(("plan", len(plan) if plan else 0))
            rows.append(("plan", plan))
        elif k == "event" and p.get("kind") == "plan_kept":
            rows.append(("kept",))
        elif k == "signals":
            v = p.get("values") or {}
            if "room_m" in v:
                room = v["room_m"]
        elif k == "tick" and p.get("belief") and p.get("cmd"):
            rows.append(("tick", t, tuple(p["belief"]), tuple(p["cmd"]), room))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--pivot-vx", type=float, default=-0.06)
    args = ap.parse_args()
    from duck_lab.nav.follow import FollowState, step as new_step
    from duck_lab.plugins.duck_walk import DuckWalk
    from duck_lab.profile import load
    old = load_old(args.base)
    prof = load("sim")
    walker = DuckWalk(prof, pivot_vx=args.pivot_vx)
    loco = prof.locomotion
    tot = {"ticks": 0, "explained": 0, "old_new_same": 0, "combos": 0, "walking_exact": 0, "walking": 0}
    for run in args.runs:
        path, st_o, st_n, t0 = None, old.FollowState(), FollowState(), None
        n = same = expl = 0
        for row in ticks_of(run):
            if row[0] == "kept":
                if path:
                    path = path[st_n.target_index:] or path[-1:]
                st_o.target_index = st_n.target_index = 0
                continue
            if row[0] == "plan":
                path = row[1]
                st_o.target_index = st_n.target_index = 0
                continue
            _, t, pose, cmd, room = row
            if not path:
                continue
            now = t
            close = room is not None and room < loco.slow_clearance_m
            best = None
            for near, pivot_ok, cl in itertools.product((False, True), (True, False), (close, not close)):
                so, sn = copy.deepcopy(st_o), copy.deepcopy(st_n)
                to, do = old.step(path, pose, now, so, near=near, pivot_ok=pivot_ok, pivot_vx=args.pivot_vx, close=cl)
                tn, dn = new_step(path, pose, now, sn, loco, walker, near=near, pivot_ok=pivot_ok, close=cl)
                tot["combos"] += 1
                if (to.vx, to.vyaw, do) == (tn.vx, tn.vyaw, dn) and vars(so) == vars(sn):
                    tot["old_new_same"] += 1
                else:
                    print("OLD/NEW DIFFER", run.name, t, near, pivot_ok, cl, to, tn)
                if best is None and (abs(tn.vx - cmd[0]) < 1e-9 and abs(tn.vyaw - cmd[1]) < TOL or
                                     (dn and cmd[0] == 0.0 and cmd[1] == 0.0)):
                    best = (sn, so)
            n += 1
            nz = cmd != (0.0, 0.0)
            tot["nonzero"] = tot.get("nonzero", 0) + nz
            if best:
                expl += 1
                tot["nonzero_explained"] = tot.get("nonzero_explained", 0) + nz
                st_n, st_o = best
            else:
                _, so = None, None
                st_o_c, st_n_c = copy.deepcopy(st_o), copy.deepcopy(st_n)
                old.step(path, pose, now, st_o_c, near=False, pivot_ok=True, pivot_vx=args.pivot_vx, close=close)
                new_step(path, pose, now, st_n_c, loco, walker, near=False, pivot_ok=True, close=close)
                st_o, st_n = st_o_c, st_n_c
        tot["ticks"] += n
        tot["explained"] += expl
        print(f"{run.name}: ticks {n}, logged command reproduced by some flags {expl}")
    print(json.dumps(tot))
    ok = tot["old_new_same"] == tot["combos"]
    print("LOCO REPLAY", "PASS: old and new give the same motion and the same follower state on every combination of every tick"
          if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
