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

# the telemetry and runs blocks (docs/wip/TELEMETRY-RETENTION-DESIGN.md)
TRACES = "https://vtraces.example.ts.net/insert/opentelemetry/v1/traces"
METRICS = "https://vm.example.ts.net/opentelemetry/v1/metrics"
LOGS = "http://127.0.0.1:9428/insert/opentelemetry/v1/logs"
check("no telemetry block: off, and runs archive after 30 days", inst.telemetry is None and inst.archive_after_days == 30, inst)
tel = I.load(write({**GOOD, "telemetry": {"environment": "dev", "traces": TRACES, "metrics": METRICS, "logs": LOGS,
                                          "metrics_interval_s": 60}, "runs": {"archive_after_days": 7}}, "tel.json"))
check("a full telemetry block: the environment, the three URLs as given, the interval",
      tel.telemetry == I.Telemetry("dev", TRACES, METRICS, LOGS, 60) and tel.archive_after_days == 7, tel.telemetry)
one = I.load(write({"installation": 1, "telemetry": {"environment": "check_1-x", "metrics": METRICS}}, "one.json"))
check("one signal URL is enough; the others None, the interval 15", one.telemetry == I.Telemetry("check_1-x", None, METRICS, None, 15), one.telemetry)
edge = [I.load(write({"installation": 1, "telemetry": {"environment": "dev", "logs": LOGS, "metrics_interval_s": n}}, f"e{n}.json")).telemetry
        .metrics_interval_s for n in (5, 300)]
check("the interval's bounds 5 and 300 are accepted", edge == [5, 300], edge)
check("an empty runs block keeps the default of 30", I.load(write({"installation": 1, "runs": {}}, "runs0.json")).archive_after_days == 30)
try:
    tel.telemetry.environment = "x"
    frozen = False
except Exception:
    frozen = True
check("the telemetry block is frozen", frozen)

# wrong shapes
CASES = [
    ("not an object", [1, 2], "not a JSON object"),
    ("an unknown key", {**GOOD, "metrics": {}}, "unknown keys ['metrics']"),
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
    ("an empty telemetry block", {**GOOD, "telemetry": {}}, "telemetry: needs 'environment'"),
    ("telemetry not an object", {**GOOD, "telemetry": "on"}, "'telemetry' must be an object"),
    ("telemetry without an environment", {**GOOD, "telemetry": {"traces": TRACES}}, "telemetry: needs 'environment'"),
    ("telemetry with an environment and no signal URL", {**GOOD, "telemetry": {"environment": "dev"}}, "at least one of 'traces', 'metrics', 'logs'"),
    ("an environment with a capital", {**GOOD, "telemetry": {"environment": "Dev", "traces": TRACES}}, "telemetry.environment must match"),
    ("an environment with a space", {**GOOD, "telemetry": {"environment": "my env", "traces": TRACES}}, "telemetry.environment must match"),
    ("an empty environment", {**GOOD, "telemetry": {"environment": "", "traces": TRACES}}, "telemetry.environment must match"),
    ("an environment that is not a string", {**GOOD, "telemetry": {"environment": 3, "traces": TRACES}}, "telemetry.environment must match"),
    ("a signal URL that is not http(s)", {**GOOD, "telemetry": {"environment": "dev", "logs": "ftp://x/y"}}, "telemetry.logs must be an http(s) URL"),
    ("a signal URL with no host", {**GOOD, "telemetry": {"environment": "dev", "metrics": "vm.example/v1/metrics"}}, "telemetry.metrics must be an http(s) URL"),
    ("a signal URL that is not a string", {**GOOD, "telemetry": {"environment": "dev", "traces": 7}}, "telemetry.traces must be an http(s) URL"),
    ("an interval below 5", {**GOOD, "telemetry": {"environment": "dev", "metrics": METRICS, "metrics_interval_s": 4}}, "metrics_interval_s must be an integer from 5 to 300"),
    ("an interval above 300", {**GOOD, "telemetry": {"environment": "dev", "metrics": METRICS, "metrics_interval_s": 301}}, "metrics_interval_s must be an integer from 5 to 300"),
    ("an interval that is a bool", {**GOOD, "telemetry": {"environment": "dev", "metrics": METRICS, "metrics_interval_s": True}}, "metrics_interval_s must be an integer from 5 to 300"),
    ("an interval that is a float", {**GOOD, "telemetry": {"environment": "dev", "metrics": METRICS, "metrics_interval_s": 15.5}}, "metrics_interval_s must be an integer from 5 to 300"),
    ("an unknown key in telemetry", {**GOOD, "telemetry": {"environment": "dev", "traces": TRACES, "token": "x"}}, "telemetry: unknown keys ['token']"),
    ("runs not an object", {**GOOD, "runs": 30}, "'runs' must be an object"),
    ("an unknown key in runs", {**GOOD, "runs": {"keep_days": 3}}, "runs: unknown keys ['keep_days']"),
    ("archive_after_days of 0", {**GOOD, "runs": {"archive_after_days": 0}}, "runs.archive_after_days must be an integer of 1 or more"),
    ("archive_after_days negative", {**GOOD, "runs": {"archive_after_days": -5}}, "runs.archive_after_days must be an integer of 1 or more"),
    ("archive_after_days a bool", {**GOOD, "runs": {"archive_after_days": True}}, "runs.archive_after_days must be an integer of 1 or more"),
    ("archive_after_days a string", {**GOOD, "runs": {"archive_after_days": "30"}}, "runs.archive_after_days must be an integer of 1 or more"),
    ("archive_after_days a float", {**GOOD, "runs": {"archive_after_days": 30.0}}, "runs.archive_after_days must be an integer of 1 or more"),
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
