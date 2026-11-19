"""Freeze a recorded glance's inputs for a unit test (tests/test_side_drops.py): the frames the navigator pooled (map-frame
points and their kinds, as glance_from_run replays them), where it stood, what it aimed at, and the real drop's box.

    .venv/bin/python sim/probes/glance_fixture.py apartment/explore-b11-r2 0 > tests/fixtures/glance_b11_r2.json

Written for the apartment's stairwell (explore_run.STAIRS: x -0.40..0, y -1.40..-0.70, the opening; its top edge is y -0.70).
"""

import json
import sys
from pathlib import Path

from runfile.mcapio import Follower

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glance_from_run as g  # noqa: E402
from duck_lab.nav.explore_run import STAIRS  # noqa: E402

run, n = sys.argv[1], int(sys.argv[2])
records = list(Follower(g.DATA / "runs" / "duck" / run, keep_raw=True).poll())
t, raw = g.glances(records)[n]
seen = {}
original = g.edge_from_glance


def capture(frames, origin, bearing):
    seen.update(frames=frames, origin=origin, bearing=bearing)
    return original(frames, origin, bearing)


g.edge_from_glance = capture
out = g.replay_glance(records, t, raw)
print(json.dumps({
    "run": run, "glance": n, "t": round(t, 1), "recorded_rim": raw["rim_points"], "recorded_status": raw["status"],
    "pose": raw["pose"], "target": raw["target"], "bearing": seen["bearing"], "hole": list(STAIRS),
    "frames": [[[round(x, 3), round(y, 3), k] for x, y, k in pts] for pts in seen["frames"]],
}, separators=(",", ":")))
