"""Each zone's recorded distance against the floor as MuJoCo has it: Pollen's model posed as it truly was (the truth's whole
pose, the measured joints), each zone's ray cast from the `tof` site the way the simulator's tof.py casts it, to the floor
plane z = 0 (flat-floor scenes; zones whose ray would hit the floor within MAX_M). Prints, per zone row, the median of
recorded / predicted distance (1.0: the readings are the distance along the ray), and the angle between each zone's true ray
and the ray cliff.py believed (with the pitch offset tof_truth_export.py ran with).

    uv run python sim/probes/tof_truth_export.py <data> <run key> 0 30 frames.json
    /work/pollen/microduck_rl/.venv/bin/python sim/probes/tof_rays.py frames.json [model.xml]
"""

import json
import math
import sys

import mujoco
import numpy as np

MAX_M = 1.0
MODEL = sys.argv[2] if len(sys.argv) > 2 else "/work/pollen/microduck_rl/src/mjlab_microduck/robot/microduck/robot_allcollisions_backlash.xml"
rows = json.loads(open(sys.argv[1]).read())
m = mujoco.MjModel.from_xml_path(MODEL)
d = mujoco.MjData(m)
site = next(i for i in range(m.nsite) if "tof" in (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_SITE, i) or ""))
free = m.jnt_qposadr[next(j for j in range(m.njnt) if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE)]

half = np.radians(45.0) / 2.0
edges = np.linspace(-half, half, 9)
centres = (edges[:-1] + edges[1:]) / 2.0
dirs = np.array([[np.cos(-centres[r]) * np.cos(-centres[c]), np.cos(-centres[r]) * np.sin(-centres[c]), np.sin(-centres[r])]
                 for r in range(8) for c in range(8)])

ratio = {r: [] for r in range(8)}
angle = {r: [] for r in range(8)}
for row in rows:
    d.qpos[:] = 0.0
    x, y, _ = row["truth"]
    d.qpos[free:free + 3] = [x, y, row["truth_3d"]["z"]]
    d.qpos[free + 3:free + 7] = row["truth_3d"]["quat"]
    for name, a in row["joints"].items():
        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
        if j >= 0:
            d.qpos[m.jnt_qposadr[j]] = a
    mujoco.mj_kinematics(m, d)
    origin, rot = d.site_xpos[site], d.site_xmat[site].reshape(3, 3)
    world = (rot @ dirs.T).T
    for z in range(64):
        w = world[z]
        b = np.array(row["believed_dirs"][z])
        angle[z // 8].append(math.degrees(math.asin(-w[2])) - math.degrees(math.asin(-b[2])))
        if w[2] >= -0.05 or row["status"][z] != 5 or row["distance_mm"][z] <= 0:
            continue
        t = -origin[2] / w[2]
        if t > MAX_M:
            continue
        ratio[z // 8].append(row["distance_mm"][z] / 1000.0 / t)
print(f"{len(rows)} frames; per zone row (0 = top): median recorded/predicted floor distance, and true minus believed ray "
      f"angle below the horizontal (deg)")
for r in range(8):
    rs, an = sorted(ratio[r]), sorted(angle[r])
    print(f"  row {r}: ratio {rs[len(rs) // 2]:.3f} ({len(rs)} zones)" if rs else f"  row {r}: no floor zones", end="")
    print(f"   angle {an[len(an) // 2]:+.2f}")
