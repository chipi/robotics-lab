"""The LDraw tool (robots/ldraw/from_ldraw.py, RFC-0011): an LDraw model to a robot's URDF and STL meshes. No parts library is
needed: a tiny library, a two-link model and its kinematics.json are in fixtures/ldraw/. Checks the flattening (quads, nested
subfiles, case-insensitive and backslash names, low-resolution primitives), the colours (inherited 16 and 24, explicit, alpha),
the winding (BFC clockwise files, mirrored subfiles), the unit and axis conversion, the links and the joint, and the
forward kinematics of the written URDF through observatory.kinematics.
Run: cd apps/observatory && uv run python tests/test_ldraw.py"""

import json
import math
import struct
import sys
import shutil
import atexit
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "robots" / "ldraw"))

import from_ldraw as ldraw  # noqa: E402
from helpers import Checks  # noqa: E402
from observatory import kinematics  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "ldraw"
check = Checks("LDRAW")


def near(a, b, tol=1e-6) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def normal(t) -> list:
    a, b, c = t
    u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    ln = math.sqrt(sum(x * x for x in n)) or 1.0
    return [x / ln for x in n]


def centroid(tris) -> list:
    pts = [p for t in tris for p in t]
    return [sum(p[i] for p in pts) / len(pts) for i in range(3)]


lib = ldraw.Library(FIX / "library")
check("the library: its colours (code, rgb, alpha) and parts by lower-case name, subparts as s/, low-resolution primitives as 8/",
      lib.rgba(4)[:3] == (201 / 255, 26 / 255, 9 / 255) and abs(lib.rgba(47)[3] - 128 / 255) < 1e-9 and lib.rgba(14)[3] == 1.0
      and {"box.dat", "s/tri.dat", "cyl.dat", "8/cyl.dat"} <= set(lib.index), sorted(lib.index))
check("a direct colour (0x2RRGGBB) is its own rgb; an unknown code is grey",
      lib.rgba(0x2FF8000)[:3] == (1.0, 128 / 255, 0.0) and lib.rgba(999) == ldraw.GREY)

# the flattening of single parts
src = ldraw.Source(FIX / "robot" / "model.ldr", lib, None, "low")
src.missing = set()
cube = ldraw.flatten(src, "BOX.DAT", {})
check("a cube of six quads is twelve triangles, colour 16 (inherit); the name is case-insensitive",
      len(cube) == 12 and {c for c, _ in cube} == {16} and not src.missing, (len(cube), src.missing))
cc = [sum(p[i] for _, t in cube for p in t) / 36 for i in range(3)]
check("every face of the cube is wound counter-clockwise seen from outside (normal away from the centre)",
      all(sum(n * (c - m) for n, c, m in zip(normal(t), centroid([t]), cc)) > 0 for _, t in cube))
mir = ldraw.flatten(src, "mirror.dat", {})
check("a subpart reached by a backslash name, mirrored in x, keeps its winding (still facing -y, up in LDraw); explicit colour 2 stays; "
      "a clockwise (BFC CW) triangle is turned counter-clockwise; colour 24 inherits",
      len(mir) == 2 and mir[0][0] == 2 and mir[1][0] == 16 and all(near(normal(t), [0, -1, 0]) for _, t in mir)
      and sorted(mir[0][1]) == [(10, 0, 0), (30, 0, 0), (30, 0, 20)], mir)
low = len(ldraw.flatten(ldraw.Source(FIX / "robot" / "model.ldr", lib, None, "low"), "disc.dat", {}))
std = len(ldraw.flatten(ldraw.Source(FIX / "robot" / "model.ldr", lib, None, "standard"), "disc.dat", {}))
check("detail low takes the primitive's 8/ version (2 triangles), standard the full one (4)", (low, std) == (2, 4), (low, std))
check("a part with no file in the library or the model is reported, not fatal",
      ldraw.flatten(src, "nope.dat", {}) == [] and "nope.dat" in src.missing)

# the walk: leaf parts with their world matrix, colour, path
insts = list(ldraw.walk(src))
check("the walk: four leaf parts (base cube, arm cube, mirror part, cable cube), the colour resolved down the references",
      [(i.part, i.colour) for i in insts] == [("box", 14), ("box", 4), ("mirror", 4), ("box", 0)], [(i.part, i.colour) for i in insts])
check("a part's world matrix and its path of (file, line)",
      near(insts[1].matrix[3::4], [0, -40, 100]) and insts[1].path == (("model.ldr", 3), ("arm.ldr", 1)), (insts[1].matrix, insts[1].path))

# axes and units
m = ldraw.mmul([ldraw.LDU, 0, 0, 0, 0, ldraw.LDU, 0, 0, 0, 0, ldraw.LDU, 0], ldraw.ros())
x, y, z = ldraw.apply(m, (100, -50, -200))
check("1 LDU = 0.4 mm; LDraw's -z (forward) is the robot's x, +x (left) its y, -y (up) its z: (100, -50, -200) LDU is (0.08, 0.04, 0.02) m",
      near((x, y, z), (0.08, 0.04, 0.02)), (x, y, z))
turned = ldraw.apply(ldraw.mmul([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0], ldraw.ros(90)), (0, 0, -1))
check("yaw_deg turns about the robot's z: forward turned 90 degrees is the robot's y", near(turned, (0, 1, 0), 1e-9), turned)
pitched = ldraw.apply(ldraw.mmul([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0], ldraw.ros(0, 90)), (0, 0, -1))
check("pitch_deg turns about y, positive lowering the nose: forward at 90 degrees points down", near(pitched, (0, 0, -1), 1e-9), pitched)

# the robot
tmp = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, tmp, True)
summary = ldraw.build(FIX / "robot", lib, tmp)
check("the summary: four parts, the cable dropped, nothing missing, the whole robot 52 x 16 x 24 mm (the arm 100 LDU back and 40 up, the mirrored "
      "triangle 30 LDU to the left), stand_z 4 mm (the base cube's centre above the lowest point)",
      summary["parts"] == 4 and summary["dropped"] == 1 and summary["missing"] == []
      and near(summary["size_m"], [0.052, 0.016, 0.024], 1e-6) and abs(summary["stand_z"] - 0.004) < 1e-9, summary)
files = sorted(p.name for p in (tmp / "meshes").glob("*.stl"))
check("one mesh per link and colour: base yellow, arm red and green", files == ["arm_c2.stl", "arm_c4.stl", "base_c14.stl"], files)
base, arm4, arm2 = (ldraw.read_stl(tmp / "meshes" / n) for n in ("base_c14.stl", "arm_c4.stl", "arm_c2.stl"))
check("the triangles: base 12 (one cube), arm 12 + 1 red (cube, the clockwise triangle) and 1 green", (len(base), len(arm4), len(arm2)) == (12, 13, 1),
      (len(base), len(arm4), len(arm2)))
bp = [p for t in base for p in t]
check("the base cube is 8 mm each way (20 LDU), centred on its link frame in x and y",
      all(abs(max(p[i] for p in bp) - min(p[i] for p in bp) - 0.008) < 1e-7 for i in range(3))
      and near(centroid(base)[:2], [0, 0], 1e-7), centroid(base))
check("the base link's frame is the root's bounding-box centre: the cube's centre is at z = 0 in it", abs(centroid(base)[2]) < 1e-7, centroid(base))
check("the mirrored subpart's triangle faces up in the robot frame (+z), as in the model",
      normal(arm2[0])[2] > 0.999, normal(arm2[0]))
data = (tmp / "meshes" / "arm_c4.stl").read_bytes()
check("the STL is binary: 80-byte header, a count, 50 bytes a triangle, a unit normal each",
      len(data) == 84 + 50 * 13 and struct.unpack_from("<I", data, 80)[0] == 13
      and abs(sum(c * c for c in struct.unpack_from("<3f", data, 84)) - 1) < 1e-5)

urdf = (tmp / "robot.urdf").read_text()
rob = kinematics.load(tmp / "robot.urdf")
check("the URDF loads through miniview.kinematics: two links, the root first, one revolute joint with its limits, rgba from LDConfig",
      rob.root == "base" and set(rob.links) == {"base", "arm"} and list(rob.joints) == ["elbow"]
      and rob.joints["elbow"].type == "revolute" and (rob.joints["elbow"].lower, rob.joints["elbow"].upper) == (-1.0, 1.0)
      and near(rob.links["base"][0].rgba, [242 / 255, 205 / 255, 55 / 255, 1.0], 1e-3) and near(rob.links["arm"][0].rgba[:3], [201 / 255, 26 / 255, 9 / 255], 1e-3), urdf[:600])
j = rob.joints["elbow"]
check("the joint: the pivot (0, -40, 100) LDU is (-0.04, 0, 0.016) m from the root's frame; its axis, LDraw's x, is the robot's y",
      near(j.origin[0], [-0.04, 0.0, 0.016], 1e-6) and near(j.axis, [0, 1, 0], 1e-6), (j.origin, j.axis))
missing = [v.mesh for vis in rob.links.values() for v in vis if not (tmp / v.mesh).is_file()]
check("every mesh the URDF names exists", missing == [] and len([v for vis in rob.links.values() for v in vis]) == 3, missing)

# forward kinematics: a vertex of the arm moves as the joint says
vertex = next(p for t in arm2 for p in t if abs(p[0] + 0.008) < 1e-6)        # the green triangle's corner 20 LDU behind the pivot, 30 LDU left
th = 0.5
poses = rob.link_poses({"elbow": th})
pos, quat = poses["arm"]
w = kinematics.qrot(quat, list(vertex))
got = [pos[i] + w[i] for i in range(3)]
want = [-0.04 + vertex[0] * math.cos(th) + vertex[2] * math.sin(th), vertex[1], 0.016 - vertex[0] * math.sin(th) + vertex[2] * math.cos(th)]
check("FK at 0.5 rad: the arm's vertex is where a rotation about the joint's axis through its pivot puts it", near(got, want, 1e-6) and abs(got[0] - (-0.04)) > 1e-3, (got, want))
check("FK at 0: the arm's frame is at the pivot, the base's at the root", near(rob.link_poses({})["arm"][0], [-0.04, 0.0, 0.016], 1e-6)
      and near(rob.link_poses({})["base"][0], [0, 0, 0]))
check("a joint past its limit is clamped (2 rad is 1 rad)", near(rob.link_poses({"elbow": 2.0})["arm"][1], rob.link_poses({"elbow": 1.0})["arm"][1], 1e-9))

# selectors
mk = lambda **k: ldraw.Instance("x.dat", ldraw.IDENT, 4, k.get("path", (("a.ldr", 1), ("b.ldr", 5))), k.get("files", ("a.ldr", "31313 - b.ldr", "x.dat")), ())  # noqa: E731
i = mk()
check("selectors: a submodel by its short name (exact, not a prefix), its lines, a part by regex, a colour, a list is all of them",
      ldraw.matches({"submodel": "b"}, i) and not ldraw.matches({"submodel": "c"}, i) and not ldraw.matches({"submodel": "31313"}, i)
      and ldraw.matches({"submodel": "b", "lines": [5, 5]}, i) is not None and not ldraw.matches({"submodel": "a", "lines": [2, 9]}, i)
      and ldraw.matches({"part": "X"}, i) and not ldraw.matches({"part": "y"}, i) and ldraw.matches({"colour": 4}, i) and not ldraw.matches({"colour": 1}, i)
      and ldraw.matches([{"submodel": "b"}, {"part": "x"}], i) and not ldraw.matches([{"submodel": "b"}, {"part": "y"}], i)
      and ldraw.matches({"submodel": "b*"}, i), None)
check("the deeper submodel is the more specific selector", ldraw.matches({"submodel": "b"}, i) > ldraw.matches({"submodel": "a"}, i))

# errors say what is wrong
bad = json.loads((FIX / "robot" / "kinematics.json").read_text())
bad["links"]["arm"] = {"include": [{"submodel": "arm"}]}
bad["links"].pop("base")
try:
    ldraw.assign(bad, insts)
    check("a part no link takes, with no `rest` link, is an error naming it", False)
except ValueError as e:
    check("a part no link takes, with no `rest` link, is an error naming it", "no link takes" in str(e) and "base.ldr" in str(e), str(e))

check.done()
