"""The duck adapter on synthetic runs (CONTRACT.md). Run: cd viewer && uv run python tests/test_duck_adapter.py"""

import json
import math
import sys
import tempfile
from pathlib import Path

from miniview.adapters.duck import prepare

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def tick(t, pose, truth, **kw):
    return dict({"t": t, "pose": pose, "truth": truth, "vx": 0.3, "vyaw": 0.0, "nearest_mm": 500, "turning": False}, **kw)


with tempfile.TemporaryDirectory() as tmp:
    # An evaluation run: two goals, the navigator (and its clock) new for each, the simulator reset.
    run = Path(tmp) / "phase1-runx"
    run.mkdir()
    rows = [
        {"event": "plan", "path": [[0.0, 0.0], [1.0, 0.0]], "t": 0.5},
        tick(1.0, [0.0, 0.0, 0.0], [0.1, 0.2, 0.0], depth=[[0.4, 0.0, 0.01, "f"]]),
        tick(2.0, [0.5, 0.0, 0.0], [0.6, 0.2, 0.0]),
        {"event": "reached", "goal": [1.0, 0.0], "t": 2.5},
        tick(1.0, [0.0, 0.0, math.pi / 2], [0.0, 0.0, 0.0]),        # goal 2: clock restarts, new map
        {"event": "refused", "why": "no path on the map", "goal": [3.0, 0.0], "t": 1.5},
    ]
    (run / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    meta, frames = prepare(run, "apartment")
    check("ticks laid end to end in time", frames["t"] == sorted(frames["t"]) and len(frames["t"]) == 3, frames["t"])
    # Goal 2's navigator clock reads 1.0 at its first tick: that second of setup happened, so goal 2
    # starts 1 s after goal 1's last record (2.5) and its first tick is at 2.5 + 1 + 1.0. Format 2
    # had dropped each goal's setup (phase1-run18: 340.8 s instead of ~588 s; 2026-11-16).
    check("a new goal keeps its own clock: its setup time is not dropped", frames["t"][2] == 4.5, frames["t"])

    # duck-eval writing natively (2026-11-16, eval2): after "reached" the evaluation logs a `leg` row still on the old
    # navigator's clock; goal 2's navigator then starts at 0. The restart must be found at goal 2's first record, not
    # given up at the stale row: goal 2's ticks went 29.86 .. 34.96 for 32.6 s of driving, and an empty third segment.
    ev = Path(tmp) / "phase1-runy"
    ev.mkdir()
    rows = [tick(1.0, [0.0, 0.0, 0.0], [0.1, 0.2, 0.0]), tick(20.0, [1.0, 0.0, 0.0], [1.1, 0.2, 0.0]),
            {"event": "reached", "goal": [1.0, 0.0], "t": 20.5},
            {"event": "leg", "n": 1, "status": "reached", "t": 20.6},           # the old navigator's clock
            tick(12.0, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]),                       # goal 2: its navigator's clock restarted
            tick(30.0, [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]),
            {"event": "reached", "goal": [3.0, 0.0], "t": 30.5},
            {"event": "leg", "n": 2, "status": "reached", "t": 30.6},
            tick(30.7, [1.0, 0.0, 0.0], [1.0, 0.0, 0.0])]                       # the stop command after "reached"
    (ev / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    meta4, frames4 = prepare(ev, "apartment")
    check("a stale row after a goal does not hide the next goal's clock restart: goal 2 keeps its own clock",
          frames4["t"] == [1.0, 20.0, 33.6, 51.6, 52.3], frames4["t"])
    segs = [r for r in (meta4.get("segments") or [])]
    check("no empty segment after the last goal", len(segs) == 2 and all(s.get("outcome") == "reached" for s in segs),
          [(s.get("index"), s.get("t_start"), s.get("t_end"), s.get("outcome")) for s in segs])
    check("one epoch per goal (the simulator reset each time)", len(meta["epochs"]) == 2, meta["epochs"])
    e0 = meta["epochs"][0]["map_to_world"]
    check("epoch 1: map to world from the first tick's truth and belief", abs(e0[0] - 0.1) < 1e-6 and abs(e0[1] - 0.2) < 1e-6, e0)
    e1 = meta["epochs"][1]["map_to_world"]
    check("epoch 2: a quarter turn back (stored to 5 decimals)", abs(e1[2] + math.pi / 2) < 1e-4, e1)
    check("plan in force from its time", frames["plan_at"][0] == 0, frames["plan_at"])
    check("depth only where a frame came", frames["depth"][0] is not None and frames["depth"][1] is None)
    check("notable events kept, with their kind", [e["kind"] for e in meta["events"]] == ["reached", "refused"], meta["events"])
    check("kind of run from its name", meta["kind"] == "go-to evaluation", meta["kind"])

    # An exploration run: one epoch from start.json.
    ex = Path(tmp) / "explore1"
    ex.mkdir()
    (ex / "start.json").write_text(json.dumps({"map": [0.0, 0.0, 0.0], "truth": [1.0, 0.0, 0.0], "scale": 0.91}))
    (ex / "ticks.jsonl").write_text(json.dumps(tick(0.5, [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])) + "\n"
                                    + json.dumps({"event": "trapped", "legs": 3, "t": 0.9}) + "\n")
    meta2, _ = prepare(ex, "apartment")
    check("exploration: one epoch from start.json, verdict from its last event",
          len(meta2["epochs"]) == 1 and meta2["epochs"][0]["map_to_world"][0] == 1.0 and meta2["verdict"] == "trapped",
          (meta2["epochs"], meta2["verdict"]))

    # explore12: events before the first pose and after the last (the navigator logged no poses
    # during surveys and stops); the run's span covers them, so the timeline shows "trapped".
    gap = Path(tmp) / "explore2"
    gap.mkdir()
    (gap / "start.json").write_text(json.dumps({"map": [0.0, 0.0, 0.0], "truth": [0.0, 0.0, 0.0], "scale": 0.91}))
    (gap / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
        {"event": "no_survey_turn", "why": "obstacle 0.16 m away", "t": 24.962},
        tick(26.992, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]),
        tick(79.655, [0.5, 0.0, 0.0], [0.5, 0.0, 0.0]),
        {"event": "cliff_stop", "drop_m": 0.475, "t": 79.755},
        {"event": "trapped", "t": 83.44}]))
    meta3, frames3 = prepare(gap, "apartment")
    check("the run's span covers every event, not only the poses",
          meta3["t0"] == 24.962 and meta3["t1"] == 83.44 and frames3["t"] == [26.992, 79.655], (meta3["t0"], meta3["t1"]))

print("ADAPTER", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
