"""Side-drop gate 2 (docs/wip/SIDE-DROPS.md): a glance at the floor beside the robot, through the cliff check. In a challenge
scene (fresh simulator per scene), standing: the head aimed at the floor GLANCE_Y_M to each side (robot.look, resent with
robot.head), frames collected only once the frame's own sensor yaw is within YAW_TOL_DEG of where the head settles, then
each frame through cliff.depth_points / drop_points with its paired state. Per side: frames used, drop returns (false
drops on flat floor; on a ledge scene, the real one), how far out to the side floor was confirmed, and the floor returns'
height error. Takes the simulator down at the end.

    uv run python sim/probes/glance_floor.py ch1-s1 ch1-s2 ch10-s1
"""

import math
import sys
import time
from pathlib import Path

from cliff_shim import cliff
from duck_lab.nav import simreset
from duck_lab.nav.run import Navigator

GLANCE_X_M, GLANCE_Y_M = 0.25, 0.45          # the floor point aimed at, in the trunk frame (ahead, aside)
FLOOR_Z_M = -0.116                            # the floor below the trunk's origin (stand height)
YAW_TOL_DEG, SETTLE_MAX_S, COLLECT_S = 3.0, 3.0, 1.2


def sensor_yaw(state) -> float:
    q = state["frames"]["tof"]["quat"]
    return math.degrees(math.atan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2)))


for scene_id in sys.argv[1:]:
    simreset.reset(str(Path.home() / ".cache" / "duck-sim" / "scenarios" / scene_id / "scene.xml"))
    try:
        nav = Navigator(calibration="sim", truth=True)
        time.sleep(3.0)
        for side, name in ((1.0, "left"), (-1.0, "right")):
            ans = nav.robot.call("robot.look", {"x": GLANCE_X_M, "y": side * GLANCE_Y_M, "z": FLOOR_Z_M, "neck_pitch": 0.0}) or {}
            head = ans.get("head")
            start, prev_yaw, settled_at, used, seen, recent = time.monotonic(), None, None, [], None, []
            while time.monotonic() - start < SETTLE_MAX_S + COLLECT_S:
                if head:
                    nav.robot.call("robot.head", head)
                fv = nav._fv
                if fv is not None and fv is not seen and fv.ok:
                    seen = fv
                    y = sensor_yaw(fv.state)
                    # settled: the sensor's own yaw has held within YAW_TOL_DEG over the last 5 frames (~0.3 s), past 45 deg.
                    # Not "within a few degrees of the commanded head_yaw": robot.look asked -57 deg for the right and the
                    # sensor sat at -67 (+68 / +68 on the left), so a match to the command never came on that side.
                    recent.append(y)
                    if settled_at is None and len(recent) >= 5 and abs(y) > 45 and max(recent[-5:]) - min(recent[-5:]) < YAW_TOL_DEG:
                        settled_at = time.monotonic()
                    prev_yaw = y
                    if settled_at is not None and time.monotonic() - settled_at <= COLLECT_S:
                        used.append(fv)
                time.sleep(0.03)
            # drop_points ignores drops more than CORRIDOR_DROP_M aside (the cliff stop is for the way ahead), so a side look
            # is judged by depth_points: "below" returns are the hole seen; floor height error only on open floor
            below, lat, zerr, edges, rim = [], [], [], [], []
            for fv in used:
                pts = cliff.depth_points(fv.frame, fv.state)
                b_lat = [side * ay for ax, ay, z, kind in pts if kind == "below"]
                if b_lat:      # the edge, this frame: the farthest floor seen short of the nearest below-floor return
                    f_pts = [(ax, side * ay) for ax, ay, z, kind in pts if kind == "floor" and side * ay < min(b_lat)]
                    if f_pts:
                        far = max(p[1] for p in f_pts)
                        edges.append(far)
                        rim.extend(p for p in f_pts if p[1] > far - 0.04)     # the floor's boundary points, for a line
                for ax, ay, z, kind in pts:
                    if kind == "below":
                        below.append((side * ay, z))
                    elif kind == "floor":
                        lat.append(side * ay)
                        if 0.1 < side * ay < 0.35:              # between the trunk and the nearest wall or edge (0.4 m+)
                            zerr.append(z)
            drops = len(below)
            lat.sort()
            zerr.sort()
            yaw = sensor_yaw(used[-1].state) if used else float("nan")
            if below:
                bl = sorted(b[0] for b in below)
                print(f"   {scene_id} {name} below-floor returns: {len(below)}, aside {bl[0]:.2f}-{bl[-1]:.2f} m, depth median "
                      f"{sorted(b[1] for b in below)[len(below) // 2]:+.2f} m", flush=True)
            if edges:
                edges.sort()
                line = ""
                if len(rim) >= 3:      # a line through the boundary (least squares, aside on ahead) and the trunk's distance to it
                    n = len(rim)
                    mx, my = sum(p[0] for p in rim) / n, sum(p[1] for p in rim) / n
                    sxx = sum((p[0] - mx) ** 2 for p in rim)
                    k = sum((p[0] - mx) * (p[1] - my) for p in rim) / sxx if sxx > 1e-9 else 0.0
                    b = my - k * mx                                    # aside = k * ahead + b
                    line = f"; edge line: trunk {abs(b) / math.sqrt(1 + k * k):.3f} m from it, at {math.degrees(math.atan(k)):+.1f} deg"
                print(f"   {scene_id} {name} edge estimate: median {edges[len(edges) // 2]:.3f} m aside "
                      f"(range {edges[0]:.3f}-{edges[-1]:.3f}, {len(edges)} frames){line}", flush=True)
            if not used:
                print(f"   {scene_id} {name} no frames: head {head}, last sensor yaw {prev_yaw}", flush=True)
            print(f"{scene_id} {name}: clamped {ans.get('clamped')} sensor yaw {yaw:+.0f} deg, {len(used)} frames; below-floor returns {drops}; "
                  f"floor out to {lat[-1] if lat else float('nan'):.2f} m aside (median {lat[len(lat) // 2] if lat else float('nan'):.2f}); "
                  f"floor height error median {1000 * zerr[len(zerr) // 2] if zerr else float('nan'):+.0f} mm, "
                  f"p95 |err| {1000 * sorted(abs(v) for v in zerr)[int(len(zerr) * 0.95)] if zerr else float('nan'):.0f} mm", flush=True)
    finally:
        simreset.down()
