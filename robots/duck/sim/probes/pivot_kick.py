"""Which kick starts a turn on the spot reliably without creeping forward? In a challenge scene (fresh simulator per
try): from a stand, the kick (KICK_RAD_S for KICK_S) with each given forward speed, then the hold (TURN_RAD_S) at the
simulator's pivot speed (-0.06) to 3 s; from the truth, the yaw gained at 1 s and at 3 s and how far the trunk moved
along its start heading during the kick. Takes the simulator down at the end.

    uv run python sim/probes/pivot_kick.py ch4-s1 6 0 -0.03 -0.06
"""

import math
import sys
import time
from pathlib import Path

from duck_lab.nav import simreset
from duck_lab.nav.follow import KICK_RAD_S, KICK_S, TURN_RAD_S
from duck_lab.nav.run import Navigator

HOLD_VX = -0.06
scene_id, tries = sys.argv[1], int(sys.argv[2])
scene_xml = Path.home() / ".cache" / "duck-sim" / "scenarios" / scene_id / "scene.xml"
for kick_vx in [float(v) for v in sys.argv[3:]]:
    for k in range(tries):
        simreset.reset(str(scene_xml))
        try:
            nav = Navigator(calibration="sim", truth=True)
            time.sleep(3.0)
            x0, y0, a0 = nav.body.pose()
            start, turned, last, at1, along1 = time.monotonic(), 0.0, a0, None, None
            while time.monotonic() - start < 3.0:
                kicking = time.monotonic() - start < KICK_S
                nav.robot.call("robot.move", {"vx": kick_vx if kicking else HOLD_VX, "vy": 0.0,
                                              "vyaw": KICK_RAD_S if kicking else TURN_RAD_S})
                time.sleep(0.05)
                x, y, a = nav.body.pose()
                turned += math.atan2(math.sin(a - last), math.cos(a - last))
                last = a
                if at1 is None and not kicking:
                    at1, along1 = turned, (x - x0) * math.cos(a0) + (y - y0) * math.sin(a0)
            nav.robot.call("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
            print(f"kick vx {kick_vx:+.3f} try {k + 1}: {math.degrees(at1):+4.0f} deg at 1 s, {math.degrees(turned):+4.0f} deg at 3 s; "
                  f"forward in the kick {along1 * 1000:+4.0f} mm", flush=True)
        finally:
            simreset.down()
