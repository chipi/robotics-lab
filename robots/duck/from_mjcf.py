"""The duck's robot description (RFC-0011) from Pollen's MuJoCo model: robot.urdf, its meshes, and a kinematics fixture.

Run with a Python that has MuJoCo (Pollen's simulator's):
    /work/pollen/microduck_rl/.venv/bin/python robots/duck/from_mjcf.py [model.xml]

Everything comes from MuJoCo's *compiled* model, so it is what MuJoCo simulates: each body is a link, its frame
relative to its parent's (`body_pos`, `body_quat`); its driven hinge is the URDF joint (axis in the body's frame; the
passive backlash hinges on the same bodies are left at rest, as fixed); a body without a hinge hangs by a fixed joint.
A link's visuals are its visual geoms (group 2), each mesh written as an STL from the compiled vertices (MuJoCo
re-centres meshes, so the original files would sit wrong), with its pose in the link and its colour.

Writes, next to this file: robot.urdf (committed), meshes/*.stl (generated, not committed: 23 MB), and
fk_fixture.json (committed): for a few sets of joint angles, every link's pose as MuJoCo computes it, which
miniview's kinematics must reproduce (apps/observatory/tests/test_kinematics.py).
"""

import json
import math
import random
import struct
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
MODEL = Path(sys.argv[1] if len(sys.argv) > 1 else
             "/work/pollen/microduck_rl/src/mjlab_microduck/robot/microduck/robot_allcollisions_backlash.xml")
VISUAL_GROUP = 2


def rpy(q) -> tuple:
    """A quaternion (w, x, y, z) as URDF's roll, pitch, yaw (R = Rz(yaw) Ry(pitch) Rx(roll))."""
    w, x, y, z = (float(v) for v in q)
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return roll, pitch, yaw


def origin(pos, quat) -> str:
    r, p, y = rpy(quat)
    return f'<origin xyz="{pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f}" rpy="{r:.6f} {p:.6f} {y:.6f}"/>'


def write_stl(path: Path, verts: np.ndarray, faces: np.ndarray) -> None:
    with open(path, "wb") as fh:
        fh.write(b"robotics-lab from MuJoCo".ljust(80, b" "))
        fh.write(struct.pack("<I", len(faces)))
        for f in faces:
            a, b, c = verts[f[0]], verts[f[1]], verts[f[2]]
            n = np.cross(b - a, c - a)
            ln = np.linalg.norm(n)
            n = n / ln if ln > 0 else n
            fh.write(struct.pack("<12fH", *n, *a, *b, *c, 0))


def main() -> None:
    m = mujoco.MjModel.from_xml_path(str(MODEL))
    name = lambda kind, i: mujoco.mj_id2name(m, kind, i)  # noqa: E731
    (HERE / "meshes").mkdir(exist_ok=True)
    root = next(b for b in range(1, m.nbody) if m.body_parentid[b] == 0)
    links, joints, driven = [], [], {}
    written = set()
    for b in range(1, m.nbody):
        bname = name(mujoco.mjtObj.mjOBJ_BODY, b)
        visuals = []
        for g in range(m.ngeom):
            if m.geom_bodyid[g] != b or m.geom_group[g] != VISUAL_GROUP or m.geom_type[g] != mujoco.mjtGeom.mjGEOM_MESH:
                continue
            mid = m.geom_dataid[g]
            mname = name(mujoco.mjtObj.mjOBJ_MESH, mid) or f"mesh{mid}"
            if mname not in written:
                v0, nv = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
                f0, nf = m.mesh_faceadr[mid], m.mesh_facenum[mid]
                write_stl(HERE / "meshes" / f"{mname}.stl", m.mesh_vert[v0:v0 + nv], m.mesh_face[f0:f0 + nf])
                written.add(mname)
            rgba = m.mat_rgba[m.geom_matid[g]] if m.geom_matid[g] >= 0 else m.geom_rgba[g]
            visuals.append(f'    <visual>\n      {origin(m.geom_pos[g], m.geom_quat[g])}\n'
                           f'      <geometry><mesh filename="meshes/{mname}.stl"/></geometry>\n'
                           f'      <material name="{mname}_{g}"><color rgba="{" ".join(f"{float(v):.3f}" for v in rgba)}"/></material>\n'
                           f'    </visual>')
        links.append(f'  <link name={quoteattr(bname)}>\n' + "\n".join(visuals) + ("\n" if visuals else "") + '  </link>')
        if b == root:
            continue
        hinges = [j for j in range(m.njnt) if m.jnt_bodyid[j] == b and m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE
                  and not name(mujoco.mjtObj.mjOBJ_JOINT, j).startswith("passive_")]
        parent = name(mujoco.mjtObj.mjOBJ_BODY, m.body_parentid[b])
        o = origin(m.body_pos[b], m.body_quat[b])
        if hinges:
            j = hinges[0]
            jname = name(mujoco.mjtObj.mjOBJ_JOINT, j)
            lo, hi = (float(v) for v in m.jnt_range[j]) if m.jnt_limited[j] else (-math.pi, math.pi)
            ax = m.jnt_axis[j]
            joints.append(f'  <joint name={quoteattr(jname)} type="revolute">\n    <parent link={quoteattr(parent)}/>\n'
                          f'    <child link={quoteattr(bname)}/>\n    {o}\n    <axis xyz="{ax[0]:.6f} {ax[1]:.6f} {ax[2]:.6f}"/>\n'
                          f'    <limit lower="{lo:.6f}" upper="{hi:.6f}" effort="10" velocity="10"/>\n  </joint>')
            driven[jname] = int(m.jnt_qposadr[j])
        else:
            joints.append(f'  <joint name={quoteattr(bname + "_fixed")} type="fixed">\n    <parent link={quoteattr(parent)}/>\n'
                          f'    <child link={quoteattr(bname)}/>\n    {o}\n  </joint>')
    urdf = ('<?xml version="1.0"?>\n<!-- Generated by robots/duck/from_mjcf.py from Pollen\'s MuJoCo model; do not edit. -->\n'
            '<robot name="duck">\n' + "\n".join(links) + "\n" + "\n".join(joints) + "\n</robot>\n")
    (HERE / "robot.urdf").write_text(urdf)

    # the fixture: MuJoCo's own link poses for some joint angles, the root at the origin
    d = mujoco.MjData(m)
    rng = random.Random(7)
    cases = []
    for _ in range(4):
        d.qpos[:] = 0.0
        d.qpos[3] = 1.0                                       # the free joint's quaternion: identity
        values = {}
        for jname, adr in driven.items():
            j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jname)
            lo, hi = m.jnt_range[j] if m.jnt_limited[j] else (-1.0, 1.0)
            values[jname] = round(rng.uniform(max(lo, -1.0), min(hi, 1.0)), 4)
            d.qpos[adr] = values[jname]
        mujoco.mj_kinematics(m, d)
        poses = {name(mujoco.mjtObj.mjOBJ_BODY, b): {"pos": [round(float(v), 7) for v in d.xpos[b]],
                                                     "quat": [round(float(v), 7) for v in d.xquat[b]]} for b in range(1, m.nbody)}
        cases.append({"joints": values, "links": poses})
    (HERE / "fk_fixture.json").write_text(json.dumps({"root": name(mujoco.mjtObj.mjOBJ_BODY, root), "cases": cases}, indent=1))
    print(f"robot.urdf: {len(links)} links, {len(joints)} joints ({len(driven)} driven); {len(written)} meshes; "
          f"fixture: {len(cases)} cases")


if __name__ == "__main__":
    main()
