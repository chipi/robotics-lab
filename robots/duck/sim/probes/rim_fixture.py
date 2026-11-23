"""Write tests/fixtures/ch22_rim_pick.json: one recorded explorer pick of challenge 22 (the grid, pose, avoid list and obstacle
points) with the cells the true hole covers marked, the stand-in for "floor the depth sensor never saw" (the ticks do not
carry the navigator's floor_seen). test_explore.py replays the pick with the rim rule.

    uv run python sim/probes/rim_fixture.py RUN_DIR PICK_T_S
"""

import json
import math
import sys
from pathlib import Path

from duck_lab.nav.frames import compose, inverse
from labrunner import challenges

OUT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ch22_rim_pick.json"


def main() -> None:
    run, want = Path(sys.argv[1]), float(sys.argv[2])
    hole = challenges.build("22", 1).drops()[0]
    start = json.loads((run / "start.json").read_text())
    w_from_m = compose(tuple(start["truth"]), inverse(tuple(start["map"])))
    rows = [json.loads(line) for line in (run / "ticks.jsonl").read_text().splitlines() if line.strip()]
    t0 = json.loads((run / "truth.jsonl").open().readline())["wall_ns"]
    pick = min((r for r in rows if r.get("event") == "pick" and r.get("target")), key=lambda r: abs((r["wall_ns"] - t0) / 1e9 - want))
    g = pick["grid"]
    c, s = math.cos(-hole.yaw), math.sin(-hole.yaw)
    mask = []
    for y in range(g["height"]):
        for x in range(g["width"]):
            wx, wy, _ = compose(w_from_m, (g["origin"][0] + (x + 0.5) * g["res_m"], g["origin"][1] + (y + 0.5) * g["res_m"], 0.0))
            dx, dy = wx - hole.cx, wy - hole.cy
            mask.append("1" if abs(c * dx - s * dy) <= hole.hx and abs(s * dx + c * dy) <= hole.hy else "0")
    keep = ("pose", "avoid", "obstacles", "retired", "reached", "target")
    OUT.write_text(json.dumps({"source": f"{run.name} pick at {(pick['wall_ns'] - t0) / 1e9:.1f} s", "grid": {k: g[k] for k in ("res_m", "origin", "width", "height", "cells")},
                               **{k: pick[k] for k in keep}, "hole": "".join(mask)}, separators=(",", ":")))
    print(OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
