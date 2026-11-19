"""The prototype's data (UX round 1: the left panel regrouped, the Explore view): a snapshot of one real run and the robot's
description, so the prototype runs from files (locally or published). Run with miniview's Python:

    cd viewer && uv run python web/proto/make_data.py <data folder> <run key>

Writes web/proto/data/ (not committed): run.json (the run's summary and streams as the API serves them, and the joints'
angles over time at 10 Hz), robot.json (the description: links, visuals, joints from the root out), meshes/*.stl.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MINIVIEW_INDEX", str(Path(tempfile.mkdtemp()) / "index.sqlite"))
from runfile import keys
from miniview import kinematics  # noqa: E402
from runfile.catalog import Catalog  # noqa: E402
from runfile.mcapio import Follower  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
data, key = Path(sys.argv[1]), sys.argv[2]
out = HERE / "data"
(out / "meshes").mkdir(parents=True, exist_ok=True)

ld = Catalog(data).get(key)
run = ld.data.run
joints, last = [], -1.0
for t, kind, p in Follower(keys.run_dir(data, key)).poll():
    if kind == "signals" and t - last >= 0.1:
        js = {k.removeprefix("joint_"): v for k, v in p["values"].items() if k.startswith("joint_") and v is not None}
        if js:
            joints.append({"t": round(t, 3), "v": {k: round(v, 4) for k, v in js.items()}})
            last = t
summary = {k: run.get(k) for k in ("key", "id", "scene", "robot", "kind", "status", "verdict", "t0", "t1", "ticks", "samples")}
summary["streams"] = run.get("streams", [])
summary["signals"] = run.get("signals", [])
summary["events"] = run.get("events", [])
(out / "run.json").write_text(json.dumps({"run": summary, "joints": joints}))

robot = kinematics.load(REPO / "robots" / "duck" / "robot.urdf")
desc = kinematics.describe(robot)
(out / "robot.json").write_text(json.dumps(desc))
meshes = {v["mesh"] for lk in desc["links"] for v in lk["visuals"]}
for m in meshes:
    shutil.copy(robot.folder / m, out / m)
print(f"data: {key}, {len(summary['streams'])} streams, {len(summary['signals'])} signals, {len(joints)} joint samples; "
      f"robot {desc['name']}: {len(desc['links'])} links, {len(desc['joints'])} joints, {len(meshes)} meshes")

vendor = HERE / "vendor"
shutil.copytree(HERE.parent / "three" / "vendor", vendor, dirs_exist_ok=True)     # the pages' three.js, so the prototype stands alone
print(f"vendor: {sorted(p.name for p in vendor.iterdir())}")
