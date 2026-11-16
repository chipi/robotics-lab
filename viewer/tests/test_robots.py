"""The robots the pages draw (RFC-0011 §3.3-3.4): the listing, a description with its mesh URLs, a mesh served with an ETag,
what is missing said rather than failed, and no path out of a robot's folder. A throwaway robots folder with a two-link arm;
no duck meshes needed. Run: cd viewer && uv run python tests/test_robots.py"""

import json
import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ["MINIVIEW_ROBOTS"] = str(TMP / "robots")
os.environ.setdefault("MINIVIEW_INDEX", str(TMP / "index.sqlite"))

from helpers import Checks, catalog, get, serve  # noqa: E402
from miniview import robots  # noqa: E402

check = Checks("ROBOTS")

ARM = """<robot name="arm">
  <link name="base"><visual><geometry><mesh filename="meshes/base.stl"/></geometry></visual></link>
  <link name="upper"><visual><geometry><mesh filename="meshes/upper.stl"/></geometry></visual></link>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
</robot>"""

arm = TMP / "robots" / "arm"
(arm / "meshes").mkdir(parents=True)
(arm / "robot.urdf").write_text(ARM)
(arm / "robot.json").write_text(json.dumps({"label": "Test arm", "backend": "none"}))
(arm / "meshes" / "base.stl").write_bytes(b"solid base\nendsolid base\n")      # upper.stl left out: a missing mesh
(TMP / "robots" / "notarobot").mkdir()                                          # a folder with no description
(TMP / "secret.stl").write_bytes(b"outside")

check("the robots root is the environment's", robots.ROOT == TMP / "robots", robots.ROOT)

httpd, base = serve(catalog(TMP / "data"))
try:
    code, ls, _ = get(base, "/api/v1/robots")
    check("the listing: robots with a description only, with what each has",
          code == 200 and [r["name"] for r in ls] == ["arm"] and ls[0]["label"] == "Test arm" and ls[0]["joints"] == 1
          and ls[0]["links"] == 2 and ls[0]["meshes"] == 2 and ls[0]["meshes_missing"] == 1 and ls[0]["backend"] == "none", ls)

    code, d, _ = get(base, "/api/v1/robots/arm")
    vis = {lk["name"]: lk["visuals"][0] for lk in d["links"]}
    check("the description: links, joints from the root out, each mesh as a URL under the API",
          code == 200 and d["root"] == "base" and [j["name"] for j in d["joints"]] == ["shoulder"]
          and d["joints"][0]["lower"] == -1.5 and vis["base"]["url"] == "robots/arm/meshes/base.stl", d)
    check("a missing mesh is said, not failed", d["meshes_missing"] == ["meshes/upper.stl"], d.get("meshes_missing"))

    code, body, hdrs = get(base, "/api/v1/" + vis["base"]["url"])
    check("a mesh is served, with an ETag", code == 200 and "solid base" in body and hdrs["ETag"], (code, dict(hdrs)))
    code, _, _ = get(base, "/api/v1/" + vis["base"]["url"], headers={"If-None-Match": hdrs["ETag"]})
    check("the client's copy: 304", code == 304, code)

    refused = {p: get(base, p)[0] for p in ("/api/v1/robots/nope", "/api/v1/robots/notarobot", "/api/v1/robots/arm/meshes/upper.stl",
                                             "/api/v1/robots/arm/robot.urdf", "/api/v1/robots/arm/..%2F..%2Fsecret.stl",
                                             "/api/v1/robots/arm/meshes/..%2F..%2F..%2Fsecret.stl")}
    check("unknown robot, a folder with no description, a missing mesh, a file that is not a mesh, a path out of the folder: 404",
          set(refused.values()) == {404}, refused)
finally:
    httpd.shutdown()

check.done()
