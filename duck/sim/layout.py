"""Dump the apartment's static geoms (world pose, size) and the keyframes to JSON, from MuJoCo itself.

Run with microduck_rl's Python, which has MuJoCo:
    /work/pollen/microduck_rl/.venv/bin/python duck/sim/layout.py > duck/sim/apartment_layout.json

Used by the phase 1 evaluation: goals inside rooms, and the footprint check against walls and
furniture. Only geoms on the world body (the apartment), not the robot's.
"""

import json
import sys
from pathlib import Path

import mujoco
import numpy as np

scene = Path(sys.argv[1] if len(sys.argv) > 1 else
             "/work/pollen/microduck_rl/src/mjlab_microduck/robot/microduck/scene_apartment_backlash.xml")
m = mujoco.MjModel.from_xml_path(str(scene))
d = mujoco.MjData(m)
mujoco.mj_forward(m, d)
types = {mujoco.mjtGeom.mjGEOM_BOX: "box", mujoco.mjtGeom.mjGEOM_CYLINDER: "cylinder",
         mujoco.mjtGeom.mjGEOM_PLANE: "plane", mujoco.mjtGeom.mjGEOM_SPHERE: "sphere",
         mujoco.mjtGeom.mjGEOM_CAPSULE: "capsule"}
geoms = []
for i in range(m.ngeom):
    if m.geom_bodyid[i] != 0:
        continue
    name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) or f"geom{i}"
    xmat = d.geom_xmat[i].reshape(3, 3)
    geoms.append({
        "name": name,
        "type": types.get(m.geom_type[i], int(m.geom_type[i])),
        "pos": [round(float(v), 4) for v in d.geom_xpos[i]],
        "size": [round(float(v), 4) for v in m.geom_size[i]],
        "yaw": round(float(np.arctan2(xmat[1, 0], xmat[0, 0])), 4),
        "collides": bool(m.geom_contype[i] or m.geom_conaffinity[i]),
    })
keys = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_KEY, k) for k in range(m.nkey)]
json.dump({"scene": scene.name, "geoms": geoms, "keyframes": keys}, sys.stdout, indent=1)
