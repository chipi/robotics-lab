"""A run in Rerun with the robot drawn as itself (RFC-0011): Rerun's own way, its URDF logged once, each joint's transform
logged per frame from the recorded angle, the trunk placed by the run's pose. Runs in a Python that has rerun-sdk (the
duck's: miniview's has not):

    robots/duck/.venv/bin/python apps/observatory/src/miniview/export/rerun_robot.py <data> <run key> <robot.urdf> <out.rrd> [fps]

The trunk's pose and the joints come from the video's track (`miniview.video.track`): the truth's whole pose in the
simulator, the belief with the IMU's tilt in the field. The scene's boxes are logged too (world frame).
"""

import math
import sys
from pathlib import Path

import rerun as rr
from rerun.urdf import UrdfTree

from runfile import keys
from miniview.video import track


def main() -> None:
    data, key, urdf, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    fps = float(sys.argv[5]) if len(sys.argv) > 5 else 30.0
    tr = track(keys.run_dir(data, key), fps)
    if not tr["frames"]:
        raise SystemExit(f"{key}: no poses to draw")
    rr.init(f"robotics_lab_{key.replace('/', '_')}", recording_id=key)
    rr.save(str(out))
    tree = UrdfTree.from_file_path(urdf)
    tree.log_urdf_to_recording()
    root = tree.root_link().name
    joints = {j.name: j for j in tree.joints() if j.joint_type != "fixed"}
    scene_p = data / "scenes" / (tr["run"] or {}).get("scene", "") / "scene.json"
    if scene_p.exists() and tr["frame"] == "world":
        import json
        sc = json.loads(scene_p.read_text())
        boxes = sc.get("boxes", [])
        if boxes:
            rr.log("scene/boxes", rr.Boxes3D(
                centers=[[b["cx"], b["cy"], (b["z0"] + b["z1"]) / 2] for b in boxes],
                half_sizes=[[b["hx"], b["hy"], (b["z1"] - b["z0"]) / 2] for b in boxes],
                quaternions=[rr.Quaternion(xyzw=[0.0, 0.0, math.sin(b.get("yaw", 0.0) / 2), math.cos(b.get("yaw", 0.0) / 2)]) for b in boxes],
                colors=[[190, 190, 200, 90]] * len(boxes)), static=True)
            rr.log("scene/boxes", rr.CoordinateFrame("world"), static=True)   # the boxes are in the world frame, as the robot's root
    for f in tr["frames"]:
        rr.set_time("run", duration=f["t"])
        w, x, y, z = f["quat"]
        rr.log("robot/pose", rr.Transform3D(translation=f["pos"], quaternion=rr.Quaternion(xyzw=[x, y, z, w]),
                                            parent_frame="world", child_frame=root))
        for name, value in f["joints"].items():
            j = joints.get(name)
            if j is not None:
                rr.log(f"robot/joints/{name}", j.compute_transform(value, clamp=False))
    print(f"rerun {out}: {len(tr['frames'])} frames, {len(joints)} joints, pose from the {tr['source']}", flush=True)


if __name__ == "__main__":
    main()
