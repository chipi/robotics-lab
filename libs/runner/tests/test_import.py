"""The runner's modules read the robot when a command starts, not when they are imported (phase 5 item 2, part 2): in the runner's own
environment, where no robot is registered and no installation is named, every labrunner module imports, and asking for the robot then
says which is missing; the judge takes the profile it is given (its fall height, footprint and reach). Run: cd libs/runner && uv run python tests/test_import.py"""

import importlib
import json
import os
import pkgutil
import sys
import tempfile
from pathlib import Path

import labrunner
from runfile import installation

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


os.environ[installation.ENV] = os.devnull + ".none"      # no installation file: no robot registered by file
from labrunner import robots  # noqa: E402

check("no robot is registered in this environment (the test's premise)", robots.names() == [], robots.names())
broke = {}
for m in pkgutil.iter_modules(labrunner.__path__):
    try:
        importlib.import_module(f"labrunner.{m.name}")
    except BaseException as e:          # robots.get() exits with SystemExit
        broke[m.name] = f"{type(e).__name__}: {e}"
check("must fail: every labrunner module imports with no robot registered", not broke, broke)
try:
    robots.get()
    check("asking for the robot then says none is registered", False, "no error")
except SystemExit as e:
    check("asking for the robot then says none is registered", "registered: none" in str(e), e)

# the judge takes the profile it is given (a course reads the robot's when it starts): a rover's, no robot installed
from labrunner.judge import Judge  # noqa: E402
from labrunner.scene import Scene, slab, wall  # noqa: E402
from runfile.profile import load_profile  # noqa: E402

rover = {"profile_version": 1, "id": "rover", "label": "Rover", "kind": "rover",
         "factsheet": {"typeSpecification": {"seriesName": "Rover", "mobileRobotKinematics": "DIFFERENTIAL"},
                       "physicalParameters": {"maximumSpeed": 0.5}},
         "control": {}, "footprint": {"radius_m": 0.5, "height_m": 0.2, "overhead_clear_m": 0.3, "goal_clearance_m": 0.3},
         "judge": {"fall_z_m": 0.3, "drop_margin_m": 0.15, "reached_m": 0.6, "bounds_margin_m": 0.05},
         "locomotion": {"cruise_mps": 0.3}, "plugins": {"locomotion": "wheels@1"}, "variants": {"sim": {}, "real": {}}}
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "rover.json").write_text(json.dumps(rover))
    prof = load_profile(Path(tmp) / "rover.json", "sim")
room = Scene("r", "r", [wall("w", 1.0, -1.0, 1.0, 1.0)], [slab("floor", -2.0, 2.0, -2.0, 2.0)], (0.5, 0.0), "reach", 30.0)
j = Judge(room, profile=prof)
hit = j.check(1.0, (0.55, 0.0, 0.0), 0.25)
check("must fail: the judge's fall height is the given profile's (0.3 m: a trunk at 0.25 m fell)", hit and hit["rule"] == "fall", hit)
hit = Judge(room, profile=prof).check(1.0, (0.55, 0.0, 0.0), 0.4)
check("its footprint too (0.5 m: 0.43 m from a wall is contact)", hit and hit["rule"] == "contact", hit)
v = Judge(room, profile=prof).verdict({"status": "reached"}, (0.0, 0.0, 0.0))
check("and its reach (0.6 m: 0.5 m from the goal is reached)", v["pass"], v)

print("RUNNER IMPORT", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
