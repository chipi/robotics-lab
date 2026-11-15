"""The duck's navigator log (ticks.jsonl, start.json) as records (miniview.store).

Reads only; never edits the run. `DuckLog` turns one log line at a time into records, so a log
still being written (a live run) goes through the same code as a finished one. Evaluation runs (a
new navigator per goal, the simulator reset each time) are laid end to end in time, one epoch per
goal; exploration runs have one epoch from start.json.
"""

import json
from pathlib import Path

from miniview.se2 import compose, inverse
from miniview.store import build, verdict_of

ENDS = ("reached", "refused", "timeout", "stalled", "aborted")
NOTABLE = ("cliff_stop", "reflex_stop", "refused", "stalled", "timeout", "aborted", "trapped", "tight_pivot",
           "cleared", "no_frontier_left", "no_survey_turn", "reached", "leg")
KIND_OF_RUN = (("phase1", "go-to evaluation"), ("explore", "exploration"), ("stairs", "stairs probe"))
ROBOT = {"name": "duck", "radius": 0.083, "height": 0.272}


def _r(v, n=3):
    return round(v, n)


def kind_of(run_id: str) -> str:
    return next((k for prefix, k in KIND_OF_RUN if run_id.startswith(prefix)), "run")


class DuckLog:
    def __init__(self, run_dir: Path, scene_id: str):
        self.run_dir = Path(run_dir)
        start_p = self.run_dir / "start.json"
        self.start = json.loads(start_p.read_text()) if start_p.exists() else None
        self.offset, self.last_t = 0.0, 0.0
        self.fresh = self.start is None
        self.events = []
        self.ticks = 0
        self.header = [(0.0, "run", {"id": self.run_dir.name, "scene": scene_id, "kind": kind_of(self.run_dir.name),
                                     "robot": ROBOT})]
        if self.start:
            m2w = compose(tuple(self.start["truth"]), inverse(tuple(self.start["map"])))
            self.header.append((0.0, "epoch", {"map_to_world": [_r(v, 5) for v in m2w]}))

    def feed(self, line: str) -> list:
        """One log line -> its records (none for lines the viewer does not use)."""
        try:
            r = json.loads(line)
        except ValueError:
            return []
        if not isinstance(r, dict) or "t" not in r:
            return []
        if r["t"] < self.last_t - 1.0:                  # a new navigator (next goal): its clock restarts
            self.offset += self.last_t + 1.0
        self.last_t = r["t"]
        t = _r(self.offset + r["t"])
        ev = r.get("event")
        if ev == "plan":
            return [(t, "plan", {"path": [[_r(p[0]), _r(p[1])] for p in r["path"]]})] if r.get("path") else []
        if ev == "world":
            g = r["grid"]
            return [(t, "world", {"grid": {"res": g["res_m"], "origin": g["origin"], "w": g["width"],
                                           "h": g["height"], "cells": g["cells"]},
                                  "obstacles": r.get("blocked", []), "drops": r.get("drops", [])})]
        if ev:
            out = []
            if ev in NOTABLE and not (ev == "leg" and r.get("status") == "reached"):
                detail = " ".join(f"{k} {v}" for k, v in r.items()
                                  if k in ("why", "status", "drop_m", "room_m", "nearest_mm", "n"))
                e = {"kind": ev, "text": f"{ev} {detail}".strip()}
                self.events.append(dict(e, t=t))
                out.append((t, "event", e))
            if ev in ENDS and r.get("goal") is not None and self.start is None:
                self.fresh = True                       # the next goal starts on a reset simulator
            return out
        if "pose" not in r:
            return []
        out = []
        if self.fresh and "truth" in r:
            m2w = compose(tuple(r["truth"]), inverse(tuple(r["pose"])))
            out.append((t, "epoch", {"map_to_world": [_r(v, 5) for v in m2w]}))
            self.fresh = False
        self.ticks += 1
        out.append((t, "tick", {"belief": [_r(v, 4) for v in r["pose"][:3]],
                                "truth": [_r(v, 4) for v in r["truth"][:3]] if "truth" in r else None,
                                "tilt": r.get("tilt"), "cmd": [r.get("vx", 0.0), r.get("vyaw", 0.0)],
                                "depth": r.get("depth")}))
        return out

    def ended(self) -> bool:
        """The log says the run is over: an exploration's last word, or an evaluation's results."""
        return (self.run_dir / "results.json").exists() or bool(self.events and self.events[-1]["kind"] in
                                                                  ("trapped", "aborted", "no_frontier_left"))

    def end(self) -> tuple:
        v = verdict_of(self.events, (self.run_dir / "results.json").exists()) if self.ticks else "empty"
        return (self.last_t + self.offset, "end", {"verdict": v})


def records(run_dir: Path, scene_id: str) -> list:
    """Every record of a finished log, the end included."""
    log = DuckLog(run_dir, scene_id)
    out = list(log.header)
    with open(Path(run_dir) / "ticks.jsonl") as fh:
        for line in fh:
            out += log.feed(line)
    out.append(log.end())
    return out


def prepare(run_dir: Path, scene_id: str) -> tuple:
    """(run.json, frames.json) as dicts."""
    d = build(records(run_dir, scene_id))
    return d.run, d.frames
