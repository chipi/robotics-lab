"""Contacts with the lm_* landmarks in exploring runs (RFC-0016: the judge counts them since 2026-11-18): for each, the
landmark, when, what the duck was doing (the command, the last events), and the remembered obstacle points near the
landmark at the time (placed in the world through the start's map-to-world): seen or not, and how far off.

    .venv/bin/python sim/probes/landmark_contacts.py runs/explore-b6-r1 runs/explore-b6-r2 ...
"""

import json
import math
import sys
from pathlib import Path

import legacy_rows

from labrunner import geometry
from labrunner.geometry import footprint_distance

FOOTPRINT_M = geometry.profile().footprint.radius_m
LAYOUT = geometry.layout_path()
from duck_lab.nav.frames import compose, inverse


def main() -> None:
    marks = [g for g in json.loads(LAYOUT.read_text())["geoms"] if g["name"].startswith("lm_")]
    for run in map(Path, sys.argv[1:]):
        st, rows = legacy_rows.load(run)
        world_from_map = compose(st["truth"], inverse(st["map"]))
        inside, recent, world = None, [], None
        for r in rows:
            if r.get("event"):
                recent = (recent + [f'{r["t"]:.1f} {r["event"]}'])[-4:]
                if r["event"] == "world":
                    world = r
                continue
            if not r.get("truth"):
                continue
            g = min(marks, key=lambda g: footprint_distance(r["truth"], g))
            d = footprint_distance(r["truth"], g)
            if d < FOOTPRINT_M and inside != g["name"]:
                inside = g["name"]
                pts = []
                for b in (world or {}).get("blocked", []):
                    wx, wy, _ = compose(world_from_map, (b[0], b[1], 0.0))
                    pts.append(footprint_distance((wx, wy), g))
                near = sorted(pts)[:3]
                print(f'{run.name} t {r["t"]:.1f}: {g["name"]} {d:.3f} m from the trunk; cmd vx {r.get("vx")} vyaw '
                      f'{r.get("vyaw")}; nearest_mm {r.get("nearest_mm")}; remembered points nearest its outline (world): '
                      f'{[round(v, 3) for v in near]} of {len(pts)}; events: {recent}')
            elif d >= FOOTPRINT_M + 0.02:
                inside = None


if __name__ == "__main__":
    main()
