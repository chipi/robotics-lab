"""The duck's navigator log (ticks.jsonl, start.json) as prepared run files (CONTRACT.md).

Reads only; never edits the run. Evaluation runs (a new navigator per goal, the simulator reset each
time) are laid end to end in time, one epoch per goal; exploration runs have one epoch from start.json.
"""

import json
from pathlib import Path

from miniview.se2 import compose, inverse

ENDS = ("reached", "refused", "timeout", "stalled", "aborted")
NOTABLE = ("cliff_stop", "reflex_stop", "refused", "stalled", "timeout", "aborted", "trapped", "tight_pivot",
           "cleared", "no_frontier_left", "no_survey_turn", "reached", "leg")
KIND_OF_RUN = (("phase1", "go-to evaluation"), ("explore", "exploration"), ("stairs", "stairs probe"))


def _r(v, n=3):
    return round(v, n)


def prepare(run_dir: Path, scene_id: str) -> tuple:
    """(run.json, frames.json) as dicts."""
    start = json.loads((run_dir / "start.json").read_text()) if (run_dir / "start.json").exists() else None
    epoch_t = compose(tuple(start["truth"]), inverse(tuple(start["map"]))) if start else None
    epochs, fresh = [], epoch_t is None
    if epoch_t is not None:
        epochs.append({"from_t": 0.0, "map_to_world": [_r(v, 5) for v in epoch_t]})

    f = {"t": [], "belief": [], "truth": [], "tilt": [], "cmd": [], "depth": [], "plan_at": [], "world_at": [],
         "plans": [], "worlds": []}
    events, offset, last_t = [], 0.0, 0.0
    plan_i, world_i = -1, -1
    for line in open(run_dir / "ticks.jsonl"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if "t" not in r:
            continue
        if r["t"] < last_t - 1.0:                  # a new navigator (next goal): its clock restarts
            offset += last_t + 1.0
        last_t = r["t"]
        t = _r(offset + r["t"])
        ev = r.get("event")
        if ev == "plan" and r.get("path"):
            f["plans"].append({"t": t, "path": [[_r(p[0]), _r(p[1])] for p in r["path"]]})
            plan_i = len(f["plans"]) - 1
            continue
        if ev == "world":
            g = r["grid"]
            f["worlds"].append({"t": t, "grid": {"res": g["res_m"], "origin": g["origin"], "w": g["width"],
                                                 "h": g["height"], "cells": g["cells"]},
                                "obstacles": r.get("blocked", []), "drops": r.get("drops", [])})
            world_i = len(f["worlds"]) - 1
            continue
        if ev:
            if ev in NOTABLE and not (ev == "leg" and r.get("status") == "reached"):
                detail = " ".join(f"{k} {v}" for k, v in r.items()
                                  if k in ("why", "status", "drop_m", "room_m", "nearest_mm", "n"))
                events.append({"t": t, "kind": ev, "text": f"{ev} {detail}".strip()})
            if ev in ENDS and r.get("goal") is not None and start is None:
                fresh = True                       # the next goal starts on a reset simulator
            continue
        if "pose" not in r:
            continue
        if fresh and "truth" in r:
            m2w = compose(tuple(r["truth"]), inverse(tuple(r["pose"])))
            epochs.append({"from_t": t, "map_to_world": [_r(v, 5) for v in m2w]})
            fresh = False
        f["t"].append(t)
        f["belief"].append([_r(v, 4) for v in r["pose"][:3]])
        f["truth"].append([_r(v, 4) for v in r["truth"][:3]] if "truth" in r else None)
        f["tilt"].append(r.get("tilt"))
        f["cmd"].append([r.get("vx", 0.0), r.get("vyaw", 0.0)])
        f["depth"].append(r.get("depth"))
        f["plan_at"].append(plan_i)
        f["world_at"].append(world_i)

    verdict = events[-1]["kind"] if events and events[-1]["kind"] in ("trapped", "aborted", "no_frontier_left") else (
        "ended" if f["t"] else "empty")
    if (run_dir / "results.json").exists():
        verdict = "evaluated"
    kind = next((k for prefix, k in KIND_OF_RUN if run_dir.name.startswith(prefix)), "run")
    run = {"id": run_dir.name, "scene": scene_id, "kind": kind,
           "robot": {"name": "duck", "radius": 0.083, "height": 0.272},
           "t0": f["t"][0] if f["t"] else 0.0, "t1": f["t"][-1] if f["t"] else 0.0, "ticks": len(f["t"]),
           "verdict": verdict, "epochs": epochs, "events": events, "streams": streams(f, events)}
    return run, f


def streams(f: dict, events: list) -> list:
    """What the run holds, stream by stream, for the streams tree and its badges (CONTRACT.md)."""
    span = (f["t"][-1] - f["t"][0]) if len(f["t"]) > 1 else 0.0

    def rate(n):
        return round(n / span, 1) if span else None

    def s(sid, group, name, frame, count, modes=("at",), default="at", parent=None, why="not in this run"):
        e = {"id": sid, "group": group, "name": name, "frame": frame, "count": count, "rate_hz": rate(count),
             "missing": count == 0, "time_modes": list(modes), "default_mode": default}
        if parent:
            e["parent"] = parent
        if count == 0:
            e["why"] = why
        return e

    n = len(f["t"])
    truth = sum(1 for x in f["truth"] if x)
    depth_frames = sum(1 for d in f["depth"] if d)
    kinds = {"f": 0, "o": 0, "v": 0, "b": 0}
    for d in f["depth"]:
        for p in d or ():
            kinds[p[3]] = kinds.get(p[3], 0) + 1
    tilt = sum(1 for x in f["tilt"] if x)
    last = f["worlds"][-1] if f["worlds"] else {"obstacles": [], "drops": []}
    track = ("at", "window", "upto")
    out = [
        s("scene.boxes", "Scene", "walls and furniture", "world", 1, why="no scene"),
        s("scene.hazards", "Scene", "hazards", "world", 1, why="no scene"),
        s("belief.pose", "Robot (belief)", "pose", "map", n),
        s("belief.track", "Robot (belief)", "track", "map", n, track, "upto"),
        s("truth.pose", "Truth", "pose", "world", truth, why="no simulator truth"),
        s("truth.track", "Truth", "track", "world", truth, track, "upto", why="no simulator truth"),
        s("sensors.depth", "Sensors", "depth", "map", depth_frames, track, "at"),
    ]
    for k, name in (("f", "floor"), ("o", "obstacle"), ("v", "overhead"), ("b", "below the floor")):
        out.append(s(f"sensors.depth.{ {'f': 'floor', 'o': 'obstacle', 'v': 'overhead', 'b': 'below'}[k] }",
                     "Sensors", name, "map", kinds.get(k, 0), track, "at", parent="sensors.depth",
                     why="none of this kind"))
    out += [
        s("sensors.tilt", "Sensors", "tilt", "robot", tilt),
        s("world.grid", "World model", "map grid", "map", len(f["worlds"])),
        s("world.obstacles", "World model", "obstacle memory", "map", len(last["obstacles"])),
        s("world.drops", "World model", "drops", "map", len(last["drops"]), why="no drop seen"),
        s("plan.path", "Plan", "path", "map", len(f["plans"])),
        s("events", "Events", "events", "time", len(events), why="no events"),
    ]
    return out
