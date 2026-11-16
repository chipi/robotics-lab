"""The duck's navigator log (ticks.jsonl, start.json) as records (miniview.store).

Reads only; never edits the run. `DuckLog` turns one log line at a time into records, so a log
still being written (a live run) goes through the same code as a finished one. Every field of the
log lands in a record (`raw` holds what has no field of its own, ADR-0007). A goal-ending event with
a goal closes a `segment`; an evaluation's goals (a new navigator each, the simulator reset) are laid
end to end in run time and each has its epoch; exploration runs have one epoch from start.json.
"""

import json
from pathlib import Path

from miniview.se2 import compose, inverse
from miniview.store import build, verdict_of

ENDS = ("reached", "refused", "timeout", "stalled", "aborted")
NOTABLE = ("cliff_stop", "reflex_stop", "refused", "stalled", "timeout", "aborted", "trapped", "tight_pivot",
           "cleared", "no_frontier_left", "no_survey_turn", "reached", "leg", "invariant", "glance")
KIND_OF_RUN = (("phase1", "go-to evaluation"), ("explore", "exploration"), ("stairs", "stairs probe"))
ROBOT = {"name": "duck", "radius": 0.083, "height": 0.272}


def _r(v, n=3):
    return round(v, n)


def kind_of(run_id: str) -> str:
    return next((k for prefix, k in KIND_OF_RUN if run_id.startswith(prefix)), "run")


class DuckLog:
    def __init__(self, run_dir: Path, scene_id: str):
        self.run_dir = Path(run_dir)
        self.scene = scene_id
        self.kind = kind_of(self.run_dir.name)
        self.robot = dict(ROBOT)
        start_p = self.run_dir / "start.json"
        self.start = json.loads(start_p.read_text()) if start_p.exists() else None
        self.offset, self.last_t = 0.0, 0.0           # source -> run time; the last run time
        self.fresh = self.start is None
        self.reset_per_goal = self.start is None       # a goal-ending event means the next goal starts on a reset simulator (an evaluation)
        self.boundary = False                          # the last goal ended: the next record opens a segment
        self.restart_armed = False                     # a goal ended: the next goal's clock restart is still to come
        self.seg_ticks = 0                             # ticks in the open segment (a segment with none is not written)
        self.seg = {"index": 0, "t_start": None, "origin_src": None, "goal": None}
        self.events = []
        self.ticks = 0
        self.header = []
        if self.start:
            m2w = compose(tuple(self.start["truth"]), inverse(tuple(self.start["map"])))
            self.header.append((0.0, "epoch", {"map_to_world": [_r(v, 5) for v in m2w]}))

    def _time(self, ts: float) -> float:
        """Run time for a source time: never back. A new segment whose clock restarted keeps that clock: its
        zero goes 1 s after the last record (the gap between goals is not in the log), so the time the new
        navigator spent before its first record (a survey, about 12 s a goal in phase 1) stays in the run."""
        if self.boundary:                              # the first record after a goal opens the next segment
            self.seg.update(origin_src=ts, t_start=None)
            self.boundary = False
            self.restart_armed = True
        # A restart is a source clock more than 1 s back (the threads' records can be a few ms out of order), looked
        # for until it comes: the first record after a goal can still be the old navigator's (duck-eval logs a `leg`
        # row after "reached"), and taking that one as the answer squeezed the next goal into the old one's time.
        if self.restart_armed and ts + self.offset < self.last_t - 1.0:
            self.offset = self.last_t + 1.0
            self.seg.update(origin_src=ts, t_start=None)     # the goal starts with its own navigator's first record
            self.restart_armed = False
        t = max(_r(ts + self.offset), self.last_t)
        self.last_t = t
        if self.seg["t_start"] is None:
            self.seg["t_start"] = t
            self.seg["origin_src"] = ts if self.seg["origin_src"] is None else self.seg["origin_src"]
        return t

    def _segment(self, t: float, outcome, goal) -> tuple:
        g = goal if goal is not None else self.seg["goal"]
        rec = {"index": self.seg["index"], "t_start": self.seg["t_start"] if self.seg["t_start"] is not None else t,
               "t_end": t, "origin_src": self.seg["origin_src"] if self.seg["origin_src"] is not None else 0.0}
        if g is not None:
            rec["goal"] = [_r(v, 4) for v in g]
        if outcome:
            rec["outcome"] = outcome
        self.seg = {"index": self.seg["index"] + 1, "t_start": None, "origin_src": None, "goal": None}
        self.seg_ticks = 0
        return (t, "segment", rec)

    def feed(self, line: str) -> list:
        """One log line -> its records (none for a line that is not a JSON object with a time)."""
        try:
            r = json.loads(line)
        except ValueError:
            return []
        return self.feed_row(r)

    def feed_row(self, r) -> list:
        """One log row (a dict, as the navigator writes it) -> its records: what a writer that has the row already uses."""
        if not isinstance(r, dict) or not isinstance(r.get("t"), (int, float)):
            return []
        ts = r["t"]
        t = self._time(ts)
        ev = r.get("event")
        rest = lambda *drop: {k: v for k, v in r.items() if k not in ("t", "event", *drop)}  # noqa: E731
        if r.get("goal") is not None and ev in ("plan", "plan_kept"):
            self.seg["goal"] = r["goal"]
        if ev == "plan" and r.get("path"):
            return [(t, "plan", {"path": [[_r(p[0]), _r(p[1])] for p in r["path"]], "t_src": ts, "raw": rest("path")})]
        if ev == "world" and isinstance(r.get("grid"), dict):
            g = r["grid"]
            return [(t, "world", {"grid": {"res": g["res_m"], "origin": g["origin"], "w": g["width"],
                                           "h": g["height"], "cells": g["cells"]},
                                  "obstacles": r.get("blocked", []), "drops": r.get("drops", []),
                                  "raw": rest("grid", "blocked", "drops")})]
        if ev:
            notable = ev in NOTABLE and not (ev == "leg" and r.get("status") == "reached")
            detail = " ".join(f"{k} {v}" for k, v in r.items() if k in ("why", "status", "drop_m", "room_m",
                                                                         "nearest_mm", "n"))
            e = {"kind": ev, "text": f"{ev} {detail}".strip() if notable else "", "notable": notable, "t_src": ts,
                 "raw": rest("decision")}
            if isinstance(r.get("decision"), dict):         # a rule that fired, with the values it compared (ADR-0014)
                e["decision"] = r["decision"]
            out = [(t, "event", e)]
            if notable:
                self.events.append({"kind": ev, "text": e["text"], "t": t})
            if ev in ENDS and r.get("goal") is not None:
                out.append(self._segment(t, ev, r["goal"]))
                self.boundary = True
                if self.reset_per_goal:
                    self.fresh = True                   # the next goal starts on a reset simulator
            return out
        if "pose" not in r:
            return [(t, "event", {"kind": "unrecognized", "text": "", "notable": False, "t_src": ts, "raw": rest()})]
        out = []
        if self.fresh and "truth" in r:
            m2w = compose(tuple(r["truth"]), inverse(tuple(r["pose"])))
            out.append((t, "epoch", {"map_to_world": [_r(v, 5) for v in m2w]}))
            self.fresh = False
        self.ticks += 1
        self.seg_ticks += 1
        # the trunk's height and whole orientation, when the log has them (ADR-0016): the truth's full pose, not a raw field
        full = ("truth" in r and isinstance(r.get("truth_quat"), list) and len(r["truth_quat"]) == 4
                and isinstance(r.get("truth_z"), (int, float)))
        tick = {"belief": [_r(v, 4) for v in r["pose"][:3]],
                "truth": [_r(v, 4) for v in r["truth"][:3]] if "truth" in r else None,
                "tilt": r.get("tilt"), "cmd": [r.get("vx", 0.0), r.get("vyaw", 0.0)],
                "depth": r.get("depth"), "t_src": ts,
                "raw": rest("pose", "truth", "tilt", "vx", "vyaw", "depth", *(("truth_z", "truth_quat") if full else ()))}
        if full:
            tick["truth_3d"] = {"z": _r(r["truth_z"], 4), "quat": [_r(v, 6) for v in r["truth_quat"]]}
        out.append((t, "tick", tick))
        return out

    def ended(self) -> bool:
        """The log says the run is over: an exploration's last word, or an evaluation's results."""
        return (self.run_dir / "results.json").exists() or bool(self.events and self.events[-1]["kind"] in
                                                                  ("trapped", "aborted", "no_frontier_left"))

    def finish(self) -> list:
        """The records that close the run: the open segment (if it saw anything), then the verdict."""
        out = []
        # An open segment is written when it has ticks of its own. In an evaluation, what comes after a goal ended and
        # before a new navigator's clock started (the stop command logged after "reached") is that goal's tail, no goal.
        tail = self.reset_per_goal and self.restart_armed
        if self.seg["t_start"] is not None and self.seg_ticks and not tail:
            out.append(self._segment(self.last_t, None, None))
        v = verdict_of(self.events, (self.run_dir / "results.json").exists()) if self.ticks else "empty"
        out.append((self.last_t, "end", {"verdict": v}))
        return out


def records(run_dir: Path, scene_id: str) -> list:
    """Every record of a finished log (without the run record), the end included."""
    log = DuckLog(run_dir, scene_id)
    out = list(log.header)
    with open(Path(run_dir) / "ticks.jsonl") as fh:
        for line in fh:
            out += log.feed(line)
    return out + log.finish()


def prepare(run_dir: Path, scene_id: str) -> tuple:
    """(run.json, frames.json) as dicts, for a log in memory (tests and quick looks; imports go through the importer)."""
    from miniview.mcapio import new_run

    log = DuckLog(run_dir, scene_id)
    run = new_run(f"duck/{scene_id}/{Path(run_dir).name}", log.robot, scene_id, log.kind, 1, "file_mtime")
    d = build([(0.0, "run", run)] + records(run_dir, scene_id))
    return d.run, d.frames
