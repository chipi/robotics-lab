"""How the duck came close to a landmark (or any layout geom): per second over a window, the truth's distance to the geom's
outline, the command, how many remembered obstacle points lie on the geom (world, through the start's map-to-world) and
how near the belief put the nearest of them, and the events.

    .venv/bin/python sim/probes/approach_trace.py runs/explore-b7-r2 lm_office 100 130
"""

import json
import math
import sys
from pathlib import Path

import legacy_rows

from duck_lab.nav.evaluate import LAYOUT, footprint_distance
from duck_lab.nav.frames import compose, inverse


def main() -> None:
    run, name, t0, t1 = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
    g = next(x for x in json.loads(LAYOUT.read_text())["geoms"] if x["name"] == name)
    st, rows = legacy_rows.load(run)
    wfm = compose(st["truth"], inverse(st["map"]))
    world, events, last_s = None, [], None
    for r in rows:
        t = r.get("t", 0)
        if r.get("event") == "world":
            world = r
        if not t0 <= t <= t1:
            continue
        if r.get("event"):
            events.append(f'{r["event"]}' + (f'({r.get("why")})' if r.get("why") else ""))
            continue
        if not r.get("truth") or (last_s is not None and t - last_s < 1.0):
            continue
        last_s = t
        on = []
        for b in (world or {}).get("blocked", []):
            wx, wy, _ = compose(wfm, (b[0], b[1], 0.0))
            if footprint_distance((wx, wy), g) < 0.05:
                on.append(math.dist(b[:2], r["pose"][:2]) if r.get("pose") else None)
        near = min((d for d in on if d is not None), default=None)
        print(f't {t:6.1f} truth->{name} {footprint_distance(r["truth"], g):.3f} m  cmd ({r.get("vx")}, {r.get("vyaw")})  '
              f'points on it {len(on):3d}, nearest from belief {near if near is None else round(near, 3)}  '
              f'nearest_mm {r.get("nearest_mm")}  {" ".join(events)}')
        events = []


if __name__ == "__main__":
    main()
