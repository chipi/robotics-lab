"""Forward kinematics from a URDF (RFC-0011): a two-link arm with known poses, and the duck's description against MuJoCo
itself (robots/duck/fk_fixture.json: every link's pose MuJoCo computed for random joint angles). Run: make test-viewer"""

import json
import math
import sys
import tempfile
from pathlib import Path

from miniview import kinematics as kin

REPO = Path(__file__).resolve().parents[3]
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


def close(a, b, tol=1e-5):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def same_rotation(qa, qb, tol=1e-5):
    """q and -q are the same rotation."""
    return close(qa, qb, tol) or close(qa, [-v for v in qb], tol)


# ---- a two-link planar arm: lengths 1 and 0.5, both joints about z ----------------------------------------------------
ARM = """<?xml version="1.0"?>
<robot name="arm">
  <link name="base"/>
  <link name="upper"/>
  <link name="fore"/>
  <link name="tool"/>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 0 1"/><limit lower="-3" upper="3" effort="1" velocity="1"/></joint>
  <joint name="elbow" type="revolute"><parent link="upper"/><child link="fore"/>
    <origin xyz="1 0 0" rpy="0 0 0"/><axis xyz="0 0 1"/><limit lower="-1" upper="1" effort="1" velocity="1"/></joint>
  <joint name="tool_fixed" type="fixed"><parent link="fore"/><child link="tool"/><origin xyz="0.5 0 0" rpy="0 0 0"/></joint>
</robot>
"""
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "arm.urdf"
    p.write_text(ARM)
    arm = kin.load(p)
check("the root is the link no joint has as its child", arm.root == "base", arm.root)
poses = arm.link_poses({"shoulder": math.pi / 2, "elbow": -1.0})
check("shoulder 90°: the elbow is at (0, 1, 0.1)", close(poses["fore"][0], [0, 1, 0.1]), poses["fore"])
check("elbow -1 rad after shoulder 90°: the tool 0.5 m on, heading 90° - 1 rad",
      close(poses["tool"][0], [0.5 * math.sin(1.0), 1 + 0.5 * math.cos(1.0), 0.1])
      and same_rotation(poses["tool"][1], kin.axis_angle([0, 0, 1], math.pi / 2 - 1.0)), poses["tool"])
poses = arm.link_poses({"elbow": 2.0})
check("a value past the limit is clamped (elbow 2 rad -> 1 rad)", close(poses["tool"][0], [1 + 0.5 * math.cos(1), 0.5 * math.sin(1), 0.1]), poses["tool"])
root = ([1.0, 2.0, 0.0], kin.axis_angle([0, 0, 1], math.pi))
poses = arm.link_poses({}, root)
check("the root's own pose carries the whole arm (turned 180° at (1, 2)): the tool at (-0.5, 2, 0.1)",
      close(poses["tool"][0], [-0.5, 2.0, 0.1]), poses["tool"])
d = kin.describe(arm)
check("describe: the links and the joints from the root outwards", [j["name"] for j in d["joints"]] == ["shoulder", "elbow", "tool_fixed"]
      and {lk["name"] for lk in d["links"]} == {"base", "upper", "fore", "tool"}, d["joints"])

# ---- the duck: our kinematics against MuJoCo's ------------------------------------------------------------------------
duck = kin.load(REPO / "robots" / "duck" / "robot.urdf")
fx = json.loads((REPO / "robots" / "duck" / "fk_fixture.json").read_text())
check("the duck's description: its root is MuJoCo's root body, 15 links, 14 driven joints",
      duck.root == fx["root"] and len(duck.links) == 15 and sum(j.type == "revolute" for j in duck.joints.values()) == 14,
      (duck.root, len(duck.links)))
worst_p, worst_q = 0.0, 0.0
for case in fx["cases"]:
    ours = duck.link_poses(case["joints"])
    for link, want in case["links"].items():
        got = ours[link]
        worst_p = max(worst_p, max(abs(a - b) for a, b in zip(got[0], want["pos"])))
        dq = min(max(abs(a - b) for a, b in zip(got[1], want["quat"])), max(abs(a + b) for a, b in zip(got[1], want["quat"])))
        worst_q = max(worst_q, dq)
check(f"every link of the duck where MuJoCo puts it, for {len(fx['cases'])} sets of random joint angles "
      "(position within 1e-5 m, orientation within 1e-5)", worst_p < 1e-5 and worst_q < 1e-5, (worst_p, worst_q))
check("the duck's visuals: every link's meshes named, 70 in all", sum(len(v) for v in duck.links.values()) == 70,
      sum(len(v) for v in duck.links.values()))

print("KINEMATICS", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
