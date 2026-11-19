"""Does a turn on the spot start from a stand with a pivot speed? In a challenge scene (fresh simulator per try): standing,
then the follower's own turn commands (kick, hold, a re-kick when a second gains under RESTEP_RAD) to the given side for
6 s, with vx = each given value; how far it turned and moved, from the truth. Takes the simulator down at the end.

    uv run python sim/probes/pivot_start.py ch6-s3 left 3 0 -0.06
"""

import math
import sys
import time
from pathlib import Path

from duck_lab.nav import simreset
from duck_lab.nav.follow import FollowState, step
from duck_lab.nav.run import Navigator

scene_id, side, tries = sys.argv[1], sys.argv[2], int(sys.argv[3])
scene_xml = Path.home() / ".cache" / "duck-sim" / "scenarios" / scene_id / "scene.xml"
sign = 1.0 if side == "left" else -1.0
for vx in [float(v) for v in sys.argv[4:]]:
    for k in range(tries):
        simreset.reset(str(scene_xml))
        try:
            nav = Navigator(calibration="sim", truth=True)
            time.sleep(3.0)
            x0, y0, a0 = nav.body.pose()
            target = [(math.cos(a0 + sign * 2.5), math.sin(a0 + sign * 2.5))]     # a point behind, to the given side: a pivot
            st, start, turned, last = FollowState(), time.monotonic(), 0.0, a0
            while time.monotonic() - start < 6.0:
                x, y, a = nav.body.pose()
                tw, _ = step([(x0 + 2 * target[0][0], y0 + 2 * target[0][1])], (x, y, a), time.monotonic(), st, pivot_vx=vx)
                nav.robot.call("robot.move", {"vx": tw.vx, "vy": 0.0, "vyaw": tw.vyaw})
                turned += math.atan2(math.sin(a - last), math.cos(a - last))
                last = a
                time.sleep(0.1)
            nav.robot.call("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
            x, y, _ = nav.body.pose()
            print(f"vx {vx:+.3f} try {k + 1}: turned {math.degrees(turned):+5.0f} deg in 6 s, moved {math.hypot(x - x0, y - y0):.3f} m",
                  flush=True)
        finally:
            simreset.down()
