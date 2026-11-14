"""The duck's size as the simulator models it: the extent of every collision mesh, standing (STAND
keyframe), in the trunk's frame (x forward, y left, z up from the floor).

    /work/pollen/microduck_rl/.venv/bin/python duck/sim/measure_duck.py

Used for the evaluation's contact distance and height cut-off (duck/src/duck_lab/nav/evaluate.py).
"""

import json
import sys

import mujoco
import numpy as np

scene = (sys.argv[1] if len(sys.argv) > 1 else
         "/work/pollen/microduck_rl/src/mjlab_microduck/robot/microduck/scene_backlash.xml")
m = mujoco.MjModel.from_xml_path(scene)
d = mujoco.MjData(m)
mujoco.mj_resetDataKeyframe(m, d, mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "STAND"))
mujoco.mj_forward(m, d)

trunk = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "trunk_base")
t_pos, t_mat = d.xpos[trunk], d.xmat[trunk].reshape(3, 3)
pts = []
for g in range(m.ngeom):
    if m.geom_bodyid[g] == 0 or not (m.geom_contype[g] or m.geom_conaffinity[g]):
        continue
    if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
        mid = m.geom_dataid[g]
        v = m.mesh_vert[m.mesh_vertadr[mid]:m.mesh_vertadr[mid] + m.mesh_vertnum[mid]]
        world = v @ d.geom_xmat[g].reshape(3, 3).T + d.geom_xpos[g]
    else:
        world = d.geom_xpos[g][None, :] + np.array([[0, 0, 0]])
    pts.append(world)
pts = np.vstack(pts)
local = (pts - t_pos) @ t_mat           # into the trunk's frame
z_floor = pts[:, 2].min()
out = {
    "length_m": round(float(local[:, 0].max() - local[:, 0].min()), 3),
    "width_m": round(float(local[:, 1].max() - local[:, 1].min()), 3),
    "height_m": round(float(pts[:, 2].max() - z_floor), 3),
    "trunk_height_m": round(float(t_pos[2] - z_floor), 3),
    "front_of_trunk_m": round(float(local[:, 0].max()), 3),
    "back_of_trunk_m": round(float(-local[:, 0].min()), 3),
    "left_of_trunk_m": round(float(local[:, 1].max()), 3),
    "right_of_trunk_m": round(float(-local[:, 1].min()), 3),
    "footprint_radius_m": round(float(np.hypot(local[:, 0], local[:, 1]).max()), 3),
}
json.dump(out, sys.stdout, indent=1)
print()
