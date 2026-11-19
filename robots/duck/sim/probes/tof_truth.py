"""The depth sensor's pose from the servo angles against the cliff check's belief: Pollen's model posed in MuJoCo with the
truth's whole trunk pose and the measured servo joints, its `tof` site's height and how far down its optical axis points,
beside what cliff.sensor_pose believed from robotd's state. Not the sensor's whole true pose: the model's passive backlash
hinges (one after each servo) are left at 0, and the recorded floor says the head looks ~2.5 deg further down than this
(floor_fit.py, tof_rays.py). Run with MuJoCo's Python on tof_truth_export.py's JSON:

    /work/pollen/microduck_rl/.venv/bin/python sim/probes/tof_truth.py frames.json [model.xml]
"""

import json
import math
import sys

import mujoco

MODEL = sys.argv[2] if len(sys.argv) > 2 else "/work/pollen/microduck_rl/src/mjlab_microduck/robot/microduck/robot_allcollisions_backlash.xml"
rows = json.loads(open(sys.argv[1]).read())
m = mujoco.MjModel.from_xml_path(MODEL)
d = mujoco.MjData(m)
site = next(i for i in range(m.nsite) if "tof" in (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_SITE, i) or ""))
free = m.jnt_qposadr[next(j for j in range(m.njnt) if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE)]
print(" time   true height  believed   true down°  believed down°   diff°   drop?")
for r in rows:
    d.qpos[:] = 0.0
    x, y, _ = r["truth"]
    d.qpos[free:free + 3] = [x, y, r["truth_3d"]["z"]]
    d.qpos[free + 3:free + 7] = r["truth_3d"]["quat"]
    for name, a in r["joints"].items():
        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
        if j >= 0:
            d.qpos[m.jnt_qposadr[j]] = a
    mujoco.mj_kinematics(m, d)
    rot = d.site_xmat[site].reshape(3, 3)
    down = math.degrees(math.asin(-rot[2, 0]))           # the site's +x (its optical axis) below the horizontal
    b = r["believed"]
    print(f"{r['t']:6.2f}    {d.site_xpos[site][2]:.3f}      {b['height']:.3f}     {down:+7.2f}     {b['pitch_down_deg']:+7.2f}      "
          f"{b['pitch_down_deg'] - down:+6.2f}   {'DROP' if r['drop'] else ''}")
