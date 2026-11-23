"""The installation file (phase 5 step 1, runfile/installation.py): a good file read with its paths expanded and its robots keyed by
name; where it is looked for (given, $ROBOTICS_LAB_INSTALLATION, the default); every wrong shape an error naming the file and what is
wrong; a missing file an error, or None when not required. No robot's package.
Run: cd libs/runfile && uv run python tests/test_installation.py"""

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

from helpers import Checks
from runfile import installation as I

check = Checks("INSTALLATION")
tmp = Path(tempfile.mkdtemp(prefix="installation-"))
atexit.register(shutil.rmtree, tmp, True)


def write(d, name="installation.json"):
    p = tmp / name
    p.write_text(json.dumps(d))
    return p


GOOD = {"installation": 1, "data": "~/lab/data", "index": "/srv/index.sqlite", "observatory": "http://127.0.0.1:8070",
        "state": "~/.local/state/robotics-lab",
        "robots": {"duck": {"navigator": "127.0.0.1:8061", "gate": "~/.cache/duck-sim/duck-a-gate.sock",
                            "profile": "~/.local/state/robotics-lab/profiles/duck/current.json"},
                   "ev3": {}}}
inst = I.load(write(GOOD))
home = Path(os.path.expanduser("~"))
check("a good file: its folders, with ~ expanded", inst.data == home / "lab/data" and inst.index == Path("/srv/index.sqlite")
      and inst.state == home / ".local/state/robotics-lab", (inst.data, inst.index, inst.state))
check("the Observatory's URL as written", inst.observatory == "http://127.0.0.1:8070")
duck = inst.robot("duck")
check("a robot by its registered name: its navigator's address and its profile's path",
      duck.navigator == "127.0.0.1:8061" and duck.profile == home / ".local/state/robotics-lab/profiles/duck/current.json", duck)
check("its gate's socket, with ~ expanded (Mission Control's way to the robot)",
      duck.gate == home / ".cache/duck-sim/duck-a-gate.sock", duck)
check("a robot with nothing set: no navigator, no gate, its own profile",
      inst.robot("ev3") == I.Robot("ev3") and inst.robot("ev3").gate is None)
check("a robot this machine does not run: None", inst.robot("turtlebot3") is None)
reg = I.load(write({"installation": 1, "robots": {"rover": {"registration": "~/robots/rover/registration.json"}}}, "reg.json"))
check("a robot's registration file, with ~ expanded (the operator's decision a)",
      reg.robot("rover").registration == home / "robots/rover/registration.json" and duck.registration is None, reg.robot("rover"))
try:
    var = I.load(write({"installation": 1, "robots": {"rover": {"variant": "real"}, "duck": {}}}, "variant.json"))
    got = (var.robot("rover").variant, var.robot("duck").variant)
except I.InstallationError as e:
    got = str(e)
check("must fail: a robot's profile variant, as written; none when not named (the runner's default depends on its host)",
      got == ("real", None), got)
pl = I.load(write({"installation": 1, "robots": {"nxt-shooterbot": {"placement": "workstation", "connections": {"nxt-web": "http://127.0.0.1:8000"}},
                                                  "duck": {}}}, "placement.json"))
check("a robot's placement and its connections' addresses, as written; none when not named",
      pl.robot("nxt-shooterbot").placement == "workstation" and pl.robot("nxt-shooterbot").connections == {"nxt-web": "http://127.0.0.1:8000"}
      and pl.robot("duck").placement is None and pl.robot("duck").connections == {}, pl.robot("nxt-shooterbot"))
check("the source is the file read", inst.source == tmp / "installation.json")
minimal = I.load(write({"installation": 1}, "minimal.json"))
check("only the version is required: a machine running nothing", minimal.robots == {} and minimal.data is None and minimal.state is None)

# where it is looked for
os.environ.pop(I.ENV, None)
check("default: ~/.config/robotics-lab/installation.json", I.where() == home / ".config/robotics-lab/installation.json")
os.environ[I.ENV] = str(tmp / "from-env.json")
check("$ROBOTICS_LAB_INSTALLATION when set", I.where() == tmp / "from-env.json")
check("a path given beats the variable", I.where(tmp / "given.json") == tmp / "given.json")
os.environ.pop(I.ENV)

# missing
try:
    I.load(tmp / "nope.json")
    missing = None
except I.InstallationError as e:
    missing = str(e)
check("a missing file is an error naming it and how to write one", missing and "nope.json" in missing and "no installation file" in missing,
      missing)
check("not required: a missing file is None", I.load(tmp / "nope.json", required=False) is None)

# wrong shapes
CASES = [
    ("not an object", [1, 2], "not a JSON object"),
    ("an unknown key", {**GOOD, "telemetry": {}}, "unknown keys ['telemetry']"),
    ("another version", {**GOOD, "installation": 2}, "this reader knows version 1"),
    ("no version", {k: v for k, v in GOOD.items() if k != "installation"}, "'installation' is None"),
    ("an empty data folder", {**GOOD, "data": ""}, "'data' must be a non-empty string"),
    ("the Observatory not a URL", {**GOOD, "observatory": "127.0.0.1:8070"}, "http(s) URL"),
    ("robots not an object", {**GOOD, "robots": ["duck"]}, "'robots' must be an object"),
    ("a robot name with a slash", {**GOOD, "robots": {"duck/a": {}}}, "registered robot's name"),
    ("an unknown key in a robot", {**GOOD, "robots": {"duck": {"socket": "/x"}}}, "robots.duck: unknown keys ['socket']"),
    ("a navigator with no port", {**GOOD, "robots": {"duck": {"navigator": "localhost"}}}, "host:port"),
    ("an empty profile path", {**GOOD, "robots": {"duck": {"profile": ""}}}, "robots.duck.profile must be a path"),
    ("an empty gate socket", {**GOOD, "robots": {"duck": {"gate": ""}}}, "robots.duck.gate must be the path of the gate's socket"),
    ("a map socket (Mission Control reads the map through the navigator API)", {**GOOD, "robots": {"duck": {"map": "/m.sock"}}},
     "robots.duck: unknown keys ['map']"),
    ("a placement that is not a name", {**GOOD, "robots": {"duck": {"placement": 3}}}, "robots.duck.placement must be a name"),
    ("connections that are not an object", {**GOOD, "robots": {"duck": {"connections": "http://x"}}}, "robots.duck.connections must be an object"),
    ("a connection that is not an http(s) URL", {**GOOD, "robots": {"duck": {"connections": {"nxt-web": "127.0.0.1:8000"}}}},
     "robots.duck.connections.nxt-web must be an http(s) URL"),
    ("an empty variant", {**GOOD, "robots": {"duck": {"variant": ""}}}, "robots.duck.variant must be the name of a profile variant"),
    ("a registration that is not a path", {**GOOD, "robots": {"duck": {"registration": 7}}},
     "robots.duck.registration must be the path of the robot's registration file"),
]
for i, (name, d, why) in enumerate(CASES):
    p = write(d, f"bad{i}.json")
    try:
        I.load(p)
        said = "accepted"
    except I.InstallationError as e:
        said = str(e)
    check(f"refused, saying why: {name}", why in said and str(p) in said, said)
bad_json = tmp / "broken.json"
bad_json.write_text("{")
try:
    I.load(bad_json)
    said = "accepted"
except I.InstallationError as e:
    said = str(e)
check("not JSON: an error naming the file", "not JSON" in said and "broken.json" in said, said)

check.done()
