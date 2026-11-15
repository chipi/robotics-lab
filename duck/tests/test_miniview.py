"""miniview on a small synthetic run: events, top and 3D frames, the filmstrip. No browser needed (the
SVG is checked; rasterizing is Chromium's). Run: cd duck && uv run python tests/test_miniview.py"""

import json
import sys
import tempfile
from pathlib import Path

from duck_lab.miniview import composite, events, load, svg_at

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


with tempfile.TemporaryDirectory() as tmp:
    run = Path(tmp)
    (run / "start.json").write_text(json.dumps({"map": [0.0, 0.0, 0.0], "truth": [0.0, 0.0, 0.0], "scale": 0.91}))
    grid = {"res_m": 0.05, "origin": [-0.1, -0.1], "width": 4, "height": 4, "cells": "????.#..##..??.."}
    tick = {"vx": 0.3, "vyaw": 0.0, "nearest_mm": 500, "turning": False, "truth_z": 0.11}
    rows = [
        {"event": "world", "grid": grid, "blocked": [[0.2, 0.1]], "drops": [[0.5, -0.3]], "t": 0.5},
        {"event": "plan", "path": [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]], "t": 0.6},
        dict(tick, pose=[0.0, 0.0, 0.0], truth=[0.01, 0.0, 0.0], t=0.7,
             depth=[[0.4, 0.0, 0.01, "f"], [0.6, 0.1, 0.2, "o"], [0.7, 0.0, -0.1, "b"]]),
        dict(tick, pose=[0.1, 0.0, 0.0], truth=[0.11, 0.0, 0.0], t=0.8),
        {"event": "cliff_stop", "drop_m": 0.5, "pose": [0.1, 0.0, 0.0], "truth": [0.11, 0.0, 0.0], "t": 0.9},
    ]
    (run / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    recs = load(run)
    ev = events(recs)
    check("events list the stop with its time", "cliff_stop" in ev and "0.90" in ev, ev)
    top = svg_at(recs, 0.85, 1.0, 1.0)
    check("top view: map cells, depth of each kind, the plan, both ducks",
          top.count("<polygon") >= 9 and "#e600e6" in top and "#e6b400" in top and "#4682ff" in top and "#28b45a" in top)
    d3 = svg_at(recs, 0.85, 1.0, 1.0, view="3d")
    check("3D view draws", d3.startswith("<svg") and d3.count("<circle") >= 3 and "<polyline" in d3)
    only = svg_at(recs, 0.85, 1.0, 1.0, layers=("truth",))
    check("layers: only what is named", "#28b45a" in only and "#4682ff" not in only and "#e6b400" not in only)
    film = composite(recs, 0.85, 1.0, 1.0, ("truth", "belief"), "3d", 3, 0.2, -120.0, 40.0)
    check("a filmstrip under the main view: main + 3 frames", film.count("<svg") >= 1 + 3 + 3, film.count("<svg"))

print("MINIVIEW", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
