"""A recorded glance, replayed from the run's own depth frames (format 2): the same selection the navigator made (the frames
once the sensor's yaw had settled, for LOOK_COLLECT_S; Navigator.glance_at), the same points (cliff.depth_points with the
paired state, placed with the pose the frame was used with), the same edge (side_drops.edge_from_glance). Prints the rim it
makes now against the one recorded, and, per frame, what the sensor aimed at and how many floor and below-floor returns it
placed, with the truth's side: STAIRS' top edge is y = -0.70 (apartment_layout.json stair_1) for explore-b11-r2.

    .venv/bin/python sim/probes/glance_from_run.py apartment/explore-b11-r2 [N]       # the N-th glance (0-based), default all

The run's depth frames carry the pose and the paired state (replay.state_of); the head's pitch, not recorded, is the sensor's
own orientation in the state.
"""

import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

from duck_lab import replay
from duck_lab.nav import cliff
from duck_lab.nav.run import LOOK_COLLECT_S, LOOK_MAX_S, LOOK_SETTLE_FRAMES, LOOK_YAW_TOL_DEG, load_tof
from duck_lab.nav.side_drops import below_counts, edge_from_glance, head_settled

DATA = Path("/work/robotics-lab/data")


def sensor_dir(rec: dict) -> tuple:
    w, x, y, z = rec["state"]["tof"]["quat"]
    return (math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))),
            math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))))


def glances(records: list) -> list:
    return [(t, p["raw"]) for t, k, p in records if k == "event" and p.get("kind") == "glance" and "rim_points" in p.get("raw", {})]


def replay_glance(records: list, t_end: float, raw: dict, cal: dict | None = None, sensor_origin: bool = False) -> dict:
    """What the glance that ended at t_end (run seconds) saw, from the frames in its window: {rim, below, floor, frames,
    used}. used: per frame used, (t, sensor yaw, pitch, floor returns, below returns, pose). The edge is traced from the
    trunk's place (what the glance was recorded with), or, sensor_origin, from the sensor's."""
    cliff.configure(**(cal or replay.calibration_of(records)))
    t0 = t_end - raw["time_s"]
    dirs, settled, used, frames, sensors = [], None, [], [], []
    frames_in = [(t, p) for t, k, p in records if k == "depth_frame" and t0 <= t <= t_end and p.get("state") and p.get("pose")]
    # the navigator reads the newest frame once per tick (10 Hz; frames come at 15 Hz), a frame once: sample the same way
    sampled, last = [], None
    for tt in sorted(t for t, k, _ in records if k == "tick" and t0 <= t <= t_end):
        newest = max(((t, p) for t, p in frames_in if t <= tt + 0.01), key=lambda e: e[0], default=None)
        if newest is not None and newest is not last:
            sampled.append(newest)
            last = newest
    for t, p in sampled:
        if t - t0 >= LOOK_MAX_S or (settled is not None and t - settled >= LOOK_COLLECT_S):
            break
        dirs.append(sensor_dir(p))
        if settled is None and head_settled(dirs, LOOK_SETTLE_FRAMES, LOOK_YAW_TOL_DEG):
            settled = t
        if settled is None:
            continue
        pose = p["pose"]
        c, s = math.cos(pose[2]), math.sin(pose[2])
        fr = {k2: p[k2] for k2 in ("rows", "cols", "distance_mm", "status")}
        rel = cliff.depth_points(fr, replay.state_of(p))
        pts = [(pose[0] + c * ax - s * ay, pose[1] + s * ax + c * ay, kind) for ax, ay, h, kind in rel
               if kind == "floor" or (kind == "below" and below_counts(h, math.hypot(ax, ay)))]
        sx, sy = cliff.sensor_offset(replay.state_of(p))
        sensors.append((pose[0] + c * sx - s * sy, pose[1] + s * sx + c * sy))
        frames.append(pts)
        used.append((t, *dirs[-1], sum(1 for q in pts if q[2] == "floor"), sum(1 for q in pts if q[2] == "below"), pose))
    origin = tuple(raw["pose"][:2])
    bearing = math.atan2(raw["target"][1] - origin[1], raw["target"][0] - origin[0])
    if sensor_origin and sensors:
        origin = (sum(q[0] for q in sensors) / len(sensors), sum(q[1] for q in sensors) / len(sensors))
    rim, below, floor = edge_from_glance(frames, origin, bearing)
    return {"rim": rim, "below": below, "floor": floor, "frames": len(frames), "used": used}


def main() -> None:
    name = sys.argv[1]
    only = int(sys.argv[2]) if len(sys.argv) > 2 else None
    records = list(Follower(DATA / "runs" / "duck" / name, keep_raw=True).poll())
    cliff.configure(**replay.calibration_of(records))
    for n, (t, raw) in enumerate(glances(records)):
        if only is not None and n != only:
            continue
        out = replay_glance(records, t, raw)
        print(f"glance {n} at {t:.1f} s, target {raw['target']}, pose {[round(v, 3) for v in raw['pose']]}, status {raw['status']}")
        print(f"  recorded: {len(raw['rim_points'])} rim points, y {min((q[1] for q in raw['rim_points']), default=float('nan')):.3f}"
              f"..{max((q[1] for q in raw['rim_points']), default=float('nan')):.3f}; frames {raw['frames']}")
        print(f"  replayed: {len(out['rim'])} rim points, y {min((q[1] for q in out['rim']), default=float('nan')):.3f}"
              f"..{max((q[1] for q in out['rim']), default=float('nan')):.3f}; frames {out['frames']}")
        for u in out["used"]:
            print(f"    t {u[0]:7.2f} sensor yaw {u[1]:+6.1f} pitch {u[2]:+6.1f}: floor {u[3]:3d} below {u[4]:3d}")
        for q in sorted(out["rim"]):
            print(f"    rim ({q[0]:+.3f}, {q[1]:+.3f})")


if __name__ == "__main__":
    main()
