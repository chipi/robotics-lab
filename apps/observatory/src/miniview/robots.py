"""The robots the pages can draw (RFC-0011 §3.3-3.4): one folder per robot under the robots root, its description
(`robot.urdf`, its meshes beside it) and its registry entry (`robot.json`: what it is, the simulator model and the real
robot's backend it has). Read only.

The root is $MINIVIEW_ROBOTS, else the repository's `robots/`.
"""

import json
import os
from pathlib import Path

from miniview import kinematics

ROOT = Path(os.environ.get("MINIVIEW_ROBOTS", Path(__file__).resolve().parents[4] / "robots"))


def _entry(folder: Path) -> dict:
    try:
        return json.loads((folder / "robot.json").read_text())
    except FileNotFoundError:
        return {}


def names(root: Path = ROOT) -> list:
    return sorted(p.name for p in root.iterdir() if (p / "robot.urdf").is_file()) if root.is_dir() else []


def listing(root: Path = ROOT) -> list:
    """Every robot with a description, and what it has."""
    out = []
    for name in names(root):
        folder, e = root / name, _entry(root / name)
        rob = kinematics.load(folder / "robot.urdf")
        meshes = {v.mesh for vis in rob.links.values() for v in vis}
        missing = sorted(m for m in meshes if not (folder / m).is_file())
        out.append({"name": name, "label": e.get("label", name), "description": True, "links": len(rob.links),
                    "joints": sum(j.type != "fixed" for j in rob.joints.values()), "meshes": len(meshes),
                    "meshes_missing": len(missing), "simulator": e.get("simulator"), "backend": e.get("backend")})
    return out


def description(name: str, root: Path = ROOT) -> dict | None:
    """The robot's description for the pages (kinematics.describe), each visual's mesh as a URL path under the API, and
    which meshes are missing (`make robots` writes them)."""
    if name not in names(root):
        return None
    folder = root / name
    rob = kinematics.load(folder / "robot.urdf")
    desc = kinematics.describe(rob)
    missing = set()
    for lk in desc["links"]:
        for v in lk["visuals"]:
            if not (folder / v["mesh"]).is_file():
                missing.add(v["mesh"])
            v["url"] = f"robots/{name}/{v['mesh']}"
    e = _entry(folder)
    desc.update(label=e.get("label", name), meshes_missing=sorted(missing), stand_z=e.get("stand_z"))
    return desc


def mesh(name: str, rel: list, root: Path = ROOT) -> Path | None:
    """A mesh file of the robot's description, never a path outside its folder."""
    if name not in names(root) or not rel or not rel[-1].lower().endswith(".stl"):
        return None
    folder = (root / name).resolve()
    p = (folder / "/".join(rel)).resolve()
    return p if folder in p.parents and p.is_file() else None
