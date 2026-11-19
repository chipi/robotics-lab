"""sim/probes/legacy_rows.py: a recorded run as the navigator's old log rows. Rows written the way the navigator wrote them go through
the Observatory's adapter (runfile/adapters/duck.py, which made the corpus's records from such logs) and come back out of
`row_of` as they went in; `load` reads a folder with ticks.jsonl as it is. No simulator.
Run: cd robots/duck && uv run python tests/test_probe_rows.py"""

import json
import math
import sys
import tempfile
from pathlib import Path

from runfile.adapters import duck

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim" / "probes"))
import legacy_rows  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def same(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        return a == b or abs(a - b) < 6e-4
    return a == b


GRID = {"res_m": 0.05, "origin": [-1.0, -1.0], "width": 3, "height": 2, "cells": "..#?.."}
ROWS = [
    {"t": 0.1, "pose": [0.0, 0.0, 0.0], "truth": [0.05, 0.0, 0.0], "tilt": [1.0, 0.5], "vx": 0.2, "vyaw": 0.0,
     "truth_z": 0.1157, "truth_quat": [1.0, 0.0, 0.0, 0.0]},
    {"t": 0.2, "event": "plan", "path": [[0.0, 0.0], [1.0, 0.5]], "goal": [1.0, 0.5], "pose": [0.0, 0.0, 0.0], "truth": [0.05, 0.0, 0.0]},
    {"t": 0.3, "event": "world", "grid": GRID, "blocked": [[0.1, 0.2]], "drops": [], "truth": [0.05, 0.0, 0.0]},
    {"t": 0.4, "event": "refused", "why": "no room to turn", "room_m": 0.14, "pose": [0.0, 0.0, 0.0],
     "decision": {"rule": "refused", "reason": "no room to turn", "values": {"room_m": 0.14}}},
    {"t": 0.5, "event": "sighting", "pose": [0.0, 0.0, 0.1], "hfov_deg": 60.0, "range_m": 3.0,
     "seen": [{"kind": "cabinet", "x": 1.0, "y": 0.0}], "truth": [0.05, 0.0, 0.0]},
    {"t": 0.6, "event": "semantic", "objects": [{"id": "cabinet_1"}], "changes": [], "truth": [0.05, 0.0, 0.0]},
    {"t": 0.7, "event": "pick", "pose": [0.0, 0.0, 0.0], "target": [1.0, 0.0], "scale": 0.91, "grid": GRID, "obstacles": []},
    {"t": 0.8, "pose": [0.1, 0.0, 0.0], "truth": [0.15, 0.0, 0.0], "vx": 0.2, "vyaw": 0.0},
]

with tempfile.TemporaryDirectory() as tmp:
    run = Path(tmp) / "explore-x"
    run.mkdir()
    (run / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ROWS))
    (run / "start.json").write_text(json.dumps({"map": [0.0, 0.0, 0.0], "truth": [0.05, 0.0, 0.0], "scale": 0.91}))

    records = duck.records(run, "apartment")
    back = [r for t, k, p in records if (r := legacy_rows.row_of(k, p, t)) is not None]
    check("the adapter's records give back every log row, field for field (ticks, events with decisions, plan, world, sighting, semantic)",
          len(back) == len(ROWS) and all(same(a, b) for a, b in zip(ROWS, back)),
          [i for i, (a, b) in enumerate(zip(ROWS, back)) if not same(a, b)])
    check("a record with no log row (an epoch, the end) gives none", legacy_rows.row_of("epoch", {"map_to_world": [0, 0, 0]}, 0.0) is None
          and legacy_rows.row_of("end", {"verdict": "x"}, 1.0) is None)
    start, rows = legacy_rows.load(run)
    check("load reads a folder with ticks.jsonl as it is, and its start.json", rows == ROWS and start["scale"] == 0.91, start)
    grid, scale = legacy_rows.final_grid(run, rows)
    check("final_grid: the last world row's grid, already scaled, when there is no map_grid.json", grid == GRID and scale == 1.0, (grid, scale))
    (run / "map_grid.json").write_text(json.dumps({"res_m": 0.04}))
    check("... and map_grid.json as mapd wrote it, to be scaled with the start's, when there is one", legacy_rows.final_grid(run, rows) == ({"res_m": 0.04}, None))

print("TEST_PROBE_ROWS", "PASS" if not failures else f"FAIL {failures}")
sys.exit(1 if failures else 0)
