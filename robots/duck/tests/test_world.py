"""duck-world on a small synthetic run: every record kind converts. Run: cd robots/duck && uv run python tests/test_world.py"""

import json
import sys
import tempfile
from pathlib import Path

from duck_lab.world import convert

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


with tempfile.TemporaryDirectory() as tmp:
    run = Path(tmp) / "run"
    run.mkdir()
    (run / "start.json").write_text(json.dumps({"map": [0.1, 0.0, 0.0], "truth": [0.0, 0.0, 0.0], "scale": 0.91}))
    grid = {"res_m": 0.05, "origin": [-0.1, -0.1], "width": 4, "height": 4, "cells": "????.#..##..??.."}
    rows = [
        {"event": "world", "grid": grid, "blocked": [[0.2, 0.1]], "drops": [[0.5, -0.3]], "t": 0.5},
        {"event": "plan", "pose": [0.1, 0.0, 0.0], "goal": [1.0, 0.0], "path": [[0.1, 0.0], [0.5, 0.0], [1.0, 0.0]], "t": 0.6},
        {"pose": [0.1, 0.0, 0.0], "vx": 0.3, "vyaw": 0.0, "nearest_mm": 500, "turning": False, "t": 0.7,
         "truth": [0.0, 0.0, 0.0], "truth_z": 0.11, "depth": [[0.4, 0.0, 0.01, "f"], [0.6, 0.1, 0.2, "o"]]},
        {"event": "refused", "why": "no room to turn", "pose": [0.2, 0.0, 0.0], "t": 1.0},
        # duck-eval: a new navigator per goal restarts the clock
        {"pose": [0.0, 0.0, 0.0], "vx": 0.0, "vyaw": 0.0, "nearest_mm": None, "turning": False, "t": 0.1,
         "truth": [0.0, 0.0, 0.0], "truth_z": 0.11},
    ]
    (run / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = Path(tmp) / "world.rrd"
    counts = convert(run, out)
    check("every record kind is read", counts == {"world": 1, "plan": 1, "tick": 2, "refused": 1}, counts)
    check("a recording is written", out.exists() and out.stat().st_size > 1000, out.stat().st_size if out.exists() else None)

print("WORLD", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
