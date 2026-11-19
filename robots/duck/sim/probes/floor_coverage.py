"""How much of the apartment's floor an exploring run's map knows, by the truth: the floor the duck could stand on (the layout's
level-0 floors, cut where it could not be and to what connects to the dock: challenge/floor.py, the challenge stream's) read
cell by cell against the run's final mapd grid (map_grid.json) and start.json, overall and per room (rooms.ROOMS). Free or occupied
cells both count as known.

    .venv/bin/python sim/probes/floor_coverage.py runs/explore-b12-r1 runs/explore-b12-r2 ...

The lattice is computed once (every run starts at the dock). The grid is mapd's, in its own frame: through start.json to the world.
"""

import json
import sys
from pathlib import Path

import legacy_rows

from duck_lab.challenge.floor import coverage_by, known_test, reachable_floor
from duck_lab.nav.evaluate import LAYOUT
from duck_lab.nav.rooms import ROOMS

layout = json.loads(LAYOUT.read_text())
regions = {name: (lambda p, b=b: b[0] <= p[0] <= b[1] and b[2] <= p[1] <= b[3]) for name, b in ROOMS.items()}
runs = [Path(a) for a in sys.argv[1:]]
start = legacy_rows.load(runs[0])[0]
points = reachable_floor(layout, tuple(start["truth"][:2]))
print(f"reachable floor from the dock: {len(points)} cells of 0.05 m; per room "
      + ", ".join(f"{n} {c}" for n, c in coverage_by(points, lambda p: True, regions)["cells"].items()))
for run in runs:
    st, rows = legacy_rows.load(run)
    grid, scale = legacy_rows.final_grid(run, rows)
    cov = coverage_by(points, known_test(grid, st if scale is None else dict(st, scale=scale)), regions)
    print(f"{run.name}: floor known {cov['all'] * 100:5.1f} %   " + "  ".join(f"{n} {v * 100:3.0f} %" for n, v in cov["regions"].items()))
