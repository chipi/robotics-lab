"""A robot's description and its forward kinematics (RFC-0011): from a URDF and joint values, each link's pose.

The computation is the one Rerun's URDF support does (`UrdfJoint.compute_transform`): a joint places its child link at
the joint's origin in the parent link (xyz, then roll-pitch-yaw), then turns it about the joint's axis by the joint's
value (revolute, continuous) or moves it along the axis (prismatic); fixed joints only place. Chained from the root,
with the root's own pose, every link is placed in the world. Plain Python: no array library.

Poses are (position [x, y, z], quaternion [w, x, y, z]).
"""

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

IDENTITY = ([0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0])


def qmul(a: list, b: list) -> list:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return [aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw]


def qrot(q: list, v: list) -> list:
    w, x, y, z = q
    p = qmul(qmul(q, [0.0, *v]), [w, -x, -y, -z])
    return p[1:]


def from_rpy(r: float, p: float, y: float) -> list:
    """URDF's roll-pitch-yaw (R = Rz(yaw) Ry(pitch) Rx(roll)) as a quaternion."""
    cr, sr, cp, sp, cy, sy = math.cos(r / 2), math.sin(r / 2), math.cos(p / 2), math.sin(p / 2), math.cos(y / 2), math.sin(y / 2)
    return [cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy]


def axis_angle(axis: list, a: float) -> list:
    n = math.sqrt(sum(c * c for c in axis)) or 1.0
    s = math.sin(a / 2) / n
    return [math.cos(a / 2), axis[0] * s, axis[1] * s, axis[2] * s]


def compose(a: tuple, b: tuple) -> tuple:
    """a ∘ b: pose b expressed in a's parent frame."""
    pa, qa = a
    pb, qb = b
    r = qrot(qa, pb)
    return [pa[0] + r[0], pa[1] + r[1], pa[2] + r[2]], qmul(qa, qb)


@dataclass
class Visual:
    mesh: str                 # the mesh file, relative to the description's folder
    origin: tuple             # its pose in the link
    rgba: list


@dataclass
class Joint:
    name: str
    type: str                 # revolute, continuous, prismatic, fixed
    parent: str
    child: str
    origin: tuple             # the child link's frame in the parent's, at value 0
    axis: list
    lower: float | None = None
    upper: float | None = None

    def transform(self, value: float = 0.0, clamp: bool = True) -> tuple:
        """The child link's pose in the parent link's frame for this value (radians or metres)."""
        if clamp and self.lower is not None and self.upper is not None and self.type != "continuous":
            value = min(max(value, self.lower), self.upper)
        if self.type in ("revolute", "continuous"):
            return compose(self.origin, ([0.0, 0.0, 0.0], axis_angle(self.axis, value)))
        if self.type == "prismatic":
            return compose(self.origin, ([c * value for c in self.axis], [1.0, 0.0, 0.0, 0.0]))
        return self.origin


@dataclass
class Robot:
    name: str
    root: str
    links: dict = field(default_factory=dict)       # name -> [Visual]
    joints: dict = field(default_factory=dict)      # name -> Joint
    by_child: dict = field(default_factory=dict)    # child link -> Joint
    folder: Path | None = None

    def order(self) -> list:
        """The joints from the root outwards: each after the joint that places its parent."""
        out, seen = [], {self.root}
        pending = list(self.joints.values())
        while pending:
            ready = [j for j in pending if j.parent in seen]
            if not ready:
                raise ValueError(f"{self.name}: joints not connected to the root {self.root}: {[j.name for j in pending]}")
            for j in ready:
                out.append(j)
                seen.add(j.child)
                pending.remove(j)
        return out

    def link_poses(self, values: dict, root_pose: tuple = IDENTITY, clamp: bool = True) -> dict:
        """Every link's pose in the root pose's frame (the world, given the root's world pose); a joint missing from `values`
        is at 0."""
        poses = {self.root: (list(root_pose[0]), list(root_pose[1]))}
        for j in self.order():
            poses[j.child] = compose(poses[j.parent], j.transform(values.get(j.name, 0.0), clamp))
        return poses


def _floats(s: str | None, n: int, default: float = 0.0) -> list:
    return [float(v) for v in s.split()] if s else [default] * n


def _origin(el) -> tuple:
    o = el.find("origin") if el is not None else None
    if o is None:
        return IDENTITY
    xyz, r = _floats(o.get("xyz"), 3), _floats(o.get("rpy"), 3)
    return xyz, from_rpy(*r)


def load(path: Path) -> Robot:
    """A robot from its URDF: links with their mesh visuals, joints with their origin, axis and limits."""
    path = Path(path)
    tree = ET.parse(path).getroot()
    rob = Robot(tree.get("name", path.stem), "", folder=path.parent)
    for link in tree.findall("link"):
        vis = []
        for v in link.findall("visual"):
            mesh = v.find("geometry/mesh")
            if mesh is None:
                continue
            color = v.find("material/color")
            vis.append(Visual(mesh.get("filename"), _origin(v), _floats(color.get("rgba") if color is not None else None, 4, 1.0)))
        rob.links[link.get("name")] = vis
    for j in tree.findall("joint"):
        lim = j.find("limit")
        ax = j.find("axis")
        jt = Joint(j.get("name"), j.get("type"), j.find("parent").get("link"), j.find("child").get("link"), _origin(j),
                   _floats(ax.get("xyz") if ax is not None else None, 3) if ax is not None else [1.0, 0.0, 0.0],
                   float(lim.get("lower")) if lim is not None and lim.get("lower") else None,
                   float(lim.get("upper")) if lim is not None and lim.get("upper") else None)
        rob.joints[jt.name] = jt
        rob.by_child[jt.child] = jt
    roots = [n for n in rob.links if n not in rob.by_child]
    if len(roots) != 1:
        raise ValueError(f"{path}: a URDF has one root link; found {roots}")
    rob.root = roots[0]
    return rob


def describe(rob: Robot) -> dict:
    """The robot as JSON for the API and the pages (RFC-0011): its links with their visuals, its joints, the root."""
    return {"name": rob.name, "root": rob.root,
            "links": [{"name": n, "visuals": [{"mesh": v.mesh, "origin": {"pos": v.origin[0], "quat": v.origin[1]}, "rgba": v.rgba}
                                              for v in vis]} for n, vis in rob.links.items()],
            "joints": [{"name": j.name, "type": j.type, "parent": j.parent, "child": j.child,
                        "origin": {"pos": j.origin[0], "quat": j.origin[1]}, "axis": j.axis, "lower": j.lower, "upper": j.upper}
                       for j in rob.order()]}
