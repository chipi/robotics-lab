"""The state at t from prepared data. Run: cd viewer && uv run python tests/test_query.py"""

import math
import sys

from miniview.query import state, tick_at

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


run = {"id": "r", "scene": "s", "epochs": [{"from_t": 0.0, "map_to_world": [1.0, 0.0, math.pi / 2]}],
       "events": [{"t": 0.15, "kind": "cliff_stop", "text": "cliff_stop"}]}
frames = {"t": [0.1, 0.2, 0.3], "belief": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
          "truth": [[1.0, 0.0, 1.5708], [1.0, 1.0, 1.5708], None], "tilt": [None, [2.0, 0.5], None],
          "cmd": [[0.3, 0.0]] * 3, "depth": [[[0.5, 0.0, 0.0, "f"]], None, None], "plan_at": [-1, 0, 0],
          "world_at": [-1, -1, 0]}

check("tick at t: the last at or before it", tick_at(frames, 0.25) == 1 and tick_at(frames, 0.05) == 0)
st = state(run, frames, 0.2)
check("belief moved into the world by the epoch (a quarter turn, then 1 m along x)",
      abs(st["belief_world"][0] - 1.0) < 1e-6 and abs(st["belief_world"][1] - 1.0) < 1e-6, st["belief_world"])
check("belief against truth: 0 m apart here", st["belief_truth_distance_m"] == 0.0, st["belief_truth_distance_m"])
check("depth: the last frame at or before t", st["depth"]["frame_tick"] == 0 and st["depth"]["returns"] == {"f": 1}, st["depth"])
check("the last event before t", st["last_event"]["kind"] == "cliff_stop")
st3 = state(run, frames, 0.3)
check("no truth (a real robot): no distance, no error", st3["truth"] is None and st3["belief_truth_distance_m"] is None)

print("QUERY", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
