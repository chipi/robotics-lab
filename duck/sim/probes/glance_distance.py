"""How near can a glance look and still read flat floor as floor? (stream A, 2026-11-17: look before you step aimed the
navigator's glance at spots 0.10-0.20 m from the duck in challenge 7 seed 1 — no drop in that scene — and both glances
reported a drop, 27 and 30 below-floor returns; the start was fenced in and the leg refused.)

In a challenge scene with flat floor round the start (fresh simulator), standing: Navigator.glance_at — the code look before
you step uses — at spots DISTANCES from the duck, at BEARINGS from its heading, TRIALS times each; per spot the glance's
status (floor / drop / unseen) and its below-floor returns. Takes the simulator down at the end.

    .venv/bin/python sim/probes/glance_distance.py ch7-s1 [ch1-s1 ...]
"""

import math
import sys
import time
from pathlib import Path

from duck_lab.nav import simreset
from duck_lab.nav.run import Navigator

DISTANCES = (0.12, 0.16, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50)
BEARINGS = (0, 45, 90, 120, -90)          # degrees from the heading, left positive
TRIALS = 1

for scene_id in sys.argv[1:]:
    simreset.reset(str(Path.home() / ".cache" / "duck-sim" / "scenarios" / scene_id / "scene.xml"))
    try:
        nav = Navigator(calibration="sim", truth=True)
        time.sleep(3.0)
        for _ in range(30):                      # the localizer has no pose before mapd's first fix
            if nav.fix() and nav.loc.pose() is not None:
                break
            time.sleep(0.5)
        print(f"== {scene_id}")
        for b in BEARINGS:
            row = []
            for d in DISTANCES:
                for _ in range(TRIALS):
                    pose = nav.loc.pose()
                    a = pose[2] + math.radians(b)
                    out = nav.glance_at((pose[0] + d * math.cos(a), pose[1] + d * math.sin(a)), pose)
                    row.append(f"{d:.2f}:{out.get('status', '?')[:5]}/{out.get('below', '?')}")
            print(f"bearing {b:4d}: " + "  ".join(row), flush=True)
    finally:
        try:
            nav.close()
        except Exception:  # noqa: BLE001
            pass
        simreset.down(str(Path.home() / ".cache" / "duck-sim" / "scenarios" / scene_id / "scene.xml"))
