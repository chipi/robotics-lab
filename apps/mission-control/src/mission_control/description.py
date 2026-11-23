"""A robot's description for the page's body (RFC-0011, RFC-0024 step 2): its URDF's links with their mesh visuals and its joints, as the
Observatory's /api/v1/robots/{robot} gives them (observatory.kinematics.describe: the same JSON, so the one body component in
libs/web/body draws either), and its meshes. The robot's folder is the one its registration file sits in (the profile's, for a robot
registered by entry point); `robot.urdf` and the meshes it names are beside the file. Standard library only; the pages do the
forward kinematics."""

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from runfile import registry


def folder(robot: str) -> Path | None:
    """The folder of a registered robot's description, or None when it has none (or is not registered here)."""
    try:
        mod = registry.module(robot)
    except LookupError:
        return None
    reg = getattr(mod, "REGISTRATION", None)
    where = Path(reg).parent if reg else Path(mod.PROFILE).parent
    return where if (where / "robot.urdf").is_file() else None


def _floats(text: str | None, n: int, default: float = 0.0) -> list:
    return [float(v) for v in text.split()] if text else [default] * n


def _quat(r: float, p: float, y: float) -> list:
    """[w, x, y, z] of a URDF's roll, pitch, yaw (about fixed x, y, z: yaw applied last)."""
    cr, sr, cp, sp, cy, sy = math.cos(r / 2), math.sin(r / 2), math.cos(p / 2), math.sin(p / 2), math.cos(y / 2), math.sin(y / 2)
    return [cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy]


def _origin(el) -> dict:
    o = el.find("origin") if el is not None else None
    if o is None:
        return {"pos": [0.0, 0.0, 0.0], "quat": [1.0, 0.0, 0.0, 0.0]}
    return {"pos": _floats(o.get("xyz"), 3), "quat": _quat(*_floats(o.get("rpy"), 3))}


def describe(robot: str, robot_id: str) -> dict | None:
    """The description of the registered robot `robot` for the page of the robot `robot_id`: each visual's mesh as a URL path under the
    API (robots/<id>/meshes/<the mesh's path in the folder, one URL-encoded segment>), the meshes that are not there listed as missing
    (`make robots` writes them), the joints from the root outwards. None when the robot has no description."""
    where = folder(robot)
    return None if where is None else describe_folder(where, robot_id)


def describe_folder(where: Path, robot_id: str) -> dict:
    """`describe` for the description in a folder."""
    tree = ET.parse(where / "robot.urdf").getroot()
    links, joints, children = [], [], set()
    for link in tree.findall("link"):
        visuals = []
        for v in link.findall("visual"):
            mesh = v.find("geometry/mesh")
            if mesh is None:
                continue
            color = v.find("material/color")
            visuals.append({"mesh": mesh.get("filename"), "origin": _origin(v), "rgba": _floats(color.get("rgba") if color is not None else None, 4, 1.0),
                            "url": f"robots/{robot_id}/meshes/{quote(mesh.get('filename'), safe='')}"})
        links.append({"name": link.get("name"), "visuals": visuals})
    for j in tree.findall("joint"):
        lim, ax = j.find("limit"), j.find("axis")
        joints.append({"name": j.get("name"), "type": j.get("type"), "parent": j.find("parent").get("link"), "child": j.find("child").get("link"),
                       "origin": _origin(j), "axis": _floats(ax.get("xyz"), 3) if ax is not None else [1.0, 0.0, 0.0],
                       "lower": float(lim.get("lower")) if lim is not None and lim.get("lower") else None,
                       "upper": float(lim.get("upper")) if lim is not None and lim.get("upper") else None})
        children.add(joints[-1]["child"])
    roots = [l["name"] for l in links if l["name"] not in children]
    if len(roots) != 1:
        raise ValueError(f"{where / 'robot.urdf'}: a URDF has one root link; found {roots}")
    seen, ordered, pending = {roots[0]}, [], list(joints)
    while pending:
        ready = [j for j in pending if j["parent"] in seen]
        if not ready:
            raise ValueError(f"{where.name}: joints not connected to the root {roots[0]}: {[j['name'] for j in pending]}")
        for j in ready:
            ordered.append(j)
            seen.add(j["child"])
            pending.remove(j)
    missing = sorted({v["mesh"] for l in links for v in l["visuals"] if not (where / v["mesh"]).is_file()})
    return {"name": tree.get("name", where.name), "root": roots[0], "links": links, "joints": ordered, "meshes_missing": missing}


def mesh_file(robot: str, rel: str) -> Path | None:
    """A mesh of the robot's description: an .stl inside its folder, never a path outside it."""
    where = folder(robot)
    if where is None or not rel.lower().endswith(".stl"):
        return None
    where = where.resolve()
    p = (where / rel).resolve()
    return p if where in p.parents and p.is_file() else None
