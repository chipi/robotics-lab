"""The NXT registered like the duck (phase 5 item 4d, unit D4): its registration and stand-in profile (robots/nxt-shooterbot), a robot file
that points at them, the variants sim and real, the two speeds and nxt-web's address read from the profile and the installation instead of
the robot file, and the old robot file (robots.nxt/nxt-1.json, which holds the robot itself) still loading as it did. No nxt-web runs here
and no brick is touched; the page is test_nxt_page.py.
Run: make test-control"""

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

from common import check, finish

from mission_control import description
from mission_control.robots import ConfigError, RobotConfig, load_robot_files
from mission_control.nxt import NxtAdapter
from runfile import installation
from runfile.profile import validate_profile

ROOT = Path(__file__).resolve().parents[3]
CONTROL = ROOT / "apps" / "mission-control"
FOLDER = ROOT / "robots" / "nxt-shooterbot"
tmp = Path(tempfile.mkdtemp(prefix="mc-nxt-registered-"))
atexit.register(shutil.rmtree, tmp, True)
URL = "http://127.0.0.1:18765"


def install(name="installation.json", registration=FOLDER / "registration.json", **robot):
    p = tmp / name
    p.write_text(json.dumps({"installation": 1, "robots": {"nxt-shooterbot": {"registration": str(registration), **robot}}}))
    os.environ[installation.ENV] = str(p)
    return p


POINTER = json.loads((CONTROL / "robots.nxt-registered" / "nxt-1.json").read_text())

# --- the profile: valid in both variants, the numbers where the adapter file had them ----------------------------------------------
raw = validate_profile(json.loads((FOLDER / "profile.json").read_text()))
check("the stand-in profile validates, with a sim and a real variant", sorted(raw["variants"]) == ["real", "sim"])
check("the two numbers are the profile's: 0.3 m/s forward and 1.5 rad/s turning, said to be assumed",
      raw["locomotion"]["cruise_mps"] == 0.3 and raw["locomotion"]["yaw_max_rad_s"] == 1.5 and raw["locomotion"]["measured"].startswith("assumed"))
check("its one plugin is a label: nxt-tracks@1", raw["plugins"] == {"locomotion": "nxt-tracks@1"})

# --- a robot file that points at it ------------------------------------------------------------------------------------------------
install(variant="sim", placement="workstation", connections={"nxt-web": URL})
sim = RobotConfig(POINTER)
real_ids = lambda cfg: [s["id"] for s in cfg.capabilities["sensors"]]
check("the pointer file's robot is the profile's: kind, label, the fire action, control", sim.kind == "nxt-shooterbot" and sim.label == "NXT Shooterbot"
      and sim.factsheet["protocolFeatures"]["mobileRobotActions"][0]["actionType"] == "fire" and sim.control["deadman_s"] == 0.6, (sim.kind, sim.label))
check("in the sim variant only the ultrasonic is declared: the colour sensor is not simulated", real_ids(sim) == ["ultrasonic"] and sim.variant == "sim", real_ids(sim))
check("the range entry: its port, its source connection and its range, no cone (the cone is the sim's parameter until D1)",
      sim.capabilities["sensors"][0] == {"id": "ultrasonic", "kind": "range", "port": "4", "source": "nxt-web", "range_m": 2.55}, sim.capabilities["sensors"])
check("it has no navigator, as the old file said", not sim.capabilities.get("navigator"))

install("real.json", variant="real", placement="workstation", connections={"nxt-web": URL})
real = RobotConfig(POINTER)
check("in the real variant the colour sensor is declared too", real_ids(real) == ["ultrasonic", "colour"] and real.variant == "real", real_ids(real))
install("novariant.json")
check("with no variant named the pointer file's robot runs as real (the nxt-web adapter has no host to ask)", RobotConfig(POINTER).variant == "real")

# --- the adapter: speeds from the profile, address from the installation -----------------------------------------------------------
install(variant="sim", placement="workstation", connections={"nxt-web": URL})
a = NxtAdapter(RobotConfig(POINTER))
check("the adapter takes 0.3 m/s and 1.5 rad/s from the profile; the robot file names neither", (a.max_vx, a.max_vyaw) == (0.3, 1.5) and "full_speed_mps" not in POINTER["adapter"], (a.max_vx, a.max_vyaw))
check("full forward and a half turn make the track percents the old file's numbers did", a.tracks(0.3, 0.0) == (100, 100) and a.tracks(0.0, 1.5) == (-50, 50), (a.tracks(0.3, 0.0), a.tracks(0.0, 1.5)))
check("nxt-web's address is the installation's connection, not a localhost in the code", a.url == URL, a.url)
install("noconn.json", variant="sim")
check("with the installation naming no connection the adapter keeps its old default", NxtAdapter(RobotConfig(POINTER)).url == "http://127.0.0.1:8000")
install(variant="sim", connections={"nxt-web": URL})
named = NxtAdapter(RobotConfig({**POINTER, "adapter": {**POINTER["adapter"], "url": "http://127.0.0.1:9999", "full_speed_mps": 0.25}}))
check("an adapter block that names a url or a speed still wins over the profile and the installation", (named.url, named.max_vx, named.max_vyaw) == ("http://127.0.0.1:9999", 0.25, 1.5), (named.url, named.max_vx))

# a profile of another number: the adapter reads the profile, not a constant of its own
other = tmp / "nxt-other"
other.mkdir()
prof = json.loads((FOLDER / "profile.json").read_text())
prof["locomotion"]["cruise_mps"], prof["locomotion"]["yaw_max_rad_s"] = 0.2, 2.0
(other / "profile.json").write_text(json.dumps(prof))
(other / "registration.json").write_text(json.dumps({"registration": 1, "name": "nxt-shooterbot", "profile": "profile.json"}))
install("other.json", registration=other / "registration.json", variant="sim")
b = NxtAdapter(RobotConfig(POINTER))
check("a profile with other speeds drives the adapter's", (b.max_vx, b.max_vyaw) == (0.2, 2.0), (b.max_vx, b.max_vyaw))

# --- the old file loads as it did --------------------------------------------------------------------------------------------------
for label, setup in (("no installation names the NXT", lambda: os.environ.__setitem__(installation.ENV, str(tmp / "absent.json"))),
                     ("the installation registers it", lambda: install("old.json", variant="sim", connections={"nxt-web": URL}))):
    setup()
    old = load_robot_files(CONTROL / "robots.nxt")[0]
    oa = NxtAdapter(old)
    check(f"the old nxt-1.json loads and keeps its own numbers and address when {label}",
          old.id == "nxt-1" and old.robot is None and old.capabilities["sensors"] == [] and (oa.max_vx, oa.max_vyaw, oa.url) == (0.3, 1.5, "http://127.0.0.1:8000"),
          (old.id, oa.max_vx, oa.max_vyaw, oa.url))

# --- the registration's own words --------------------------------------------------------------------------------------------------
reg = json.loads((FOLDER / "registration.json").read_text())
check("the registration names where the NXT's software can run: the workstation", reg["placements"] == ["workstation"])
install("miss.json", registration=tmp / "nowhere.json")
try:
    RobotConfig(POINTER)
    said = "loaded"
except ConfigError as exc:
    said = str(exc)
check("must fail: a pointer file with its registration file missing is refused naming the file", "nowhere.json" in said, said)

# --- the description ---------------------------------------------------------------------------------------------------------------
install(variant="sim")
d = description.describe("nxt-shooterbot", "nxt-1")
check("the registration finds the NXT's description (its robot.urdf is beside it): the chassis as root, the tracks and the shooter",
      d is not None and d["root"] == "chassis" and {j["name"] for j in d["joints"]} >= {"left", "right", "shooter"}, d and (d["root"], [j["name"] for j in d["joints"]]))
check("each visual's mesh is under the API as robots/nxt-1/meshes/<file>", all(v["url"].startswith("robots/nxt-1/meshes/") for l in d["links"] for v in l["visuals"]))
built = not d["meshes_missing"]
print(("built meshes: all " + str(sum(len(l["visuals"]) for l in d["links"])) + " visuals have their STL") if built
      else f"meshes not built ({len(d['meshes_missing'])} missing; `make robots-lego` writes them): the page test skips")
check("a mesh outside the folder is never served", description.mesh_file("nxt-shooterbot", "../registration.json") is None
      and description.mesh_file("nxt-shooterbot", "../../duck/profile.json") is None)
finish("test_nxt_registered")
