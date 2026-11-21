"""Does a backward speed during a pivot cancel the duck's creep? In a challenge scene (fresh simulator per case): a half
turn on the spot to the right at TURN_RAD_S with vx = each given value, and how far the trunk moved (from the truth),
along the start heading and sideways, and how far it turned. Takes the simulator down at the end.

    uv run python sim/probes/pivot_counter.py ch5-s3 0 -0.035 -0.05
"""

import math
import sys
import time
from pathlib import Path

import simhost
from duck_lab.profile import load as load_profile

_LOCO = load_profile("sim").locomotion
KICK_RAD_S, KICK_S, TURN_RAD_S = _LOCO.kick_rad_s, _LOCO.kick_s, _LOCO.hold_rad_s
from duck_lab.nav.run import Navigator, host_links
from simhost.truth import Body  # noqa: E402 - the probe's own truth, to measure with (the navigator has none)

scene_id = sys.argv[1]
scene_xml = simhost.load().scenarios / scene_id / "scene.xml"
for vx in [float(v) for v in sys.argv[2:]]:
    simhost.reset(simhost.load(), str(scene_xml))
    try:
        nav = Navigator(**host_links(simhost.load()), calibration="sim")
        truth = Body(simhost.load().truth_port)
        time.sleep(3.0)
        x0, y0, a0 = truth.pose()
        turned, last, start = 0.0, a0, time.monotonic()
        while turned < math.pi and time.monotonic() - start < 15.0:
            rate = KICK_RAD_S if time.monotonic() - start < KICK_S else TURN_RAD_S
            nav.robot.call("robot.move", {"vx": vx, "vy": 0.0, "vyaw": -rate})
            time.sleep(0.05)
            a = truth.pose()[2]
            turned += -math.atan2(math.sin(a - last), math.cos(a - last))
            last = a
        nav.robot.call("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
        time.sleep(1.0)
        x, y, _ = truth.pose()
        dx, dy = x - x0, y - y0
        along = dx * math.cos(a0) + dy * math.sin(a0)
        side = -dx * math.sin(a0) + dy * math.cos(a0)
        print(f"vx {vx:+.3f}: turned {math.degrees(turned):4.0f} deg in {time.monotonic() - start:4.1f} s; moved {math.hypot(dx, dy):.3f} m "
              f"(along the start heading {along:+.3f}, to the left {side:+.3f})", flush=True)
    finally:
        simhost.down(simhost.load())
