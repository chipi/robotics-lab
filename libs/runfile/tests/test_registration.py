"""A robot registered by the installation file (phase 5 step 1, the operator's decision a, runfile.registry): a registration file
named by `robots.<name>.registration` is the robot, with nothing installed beside the reader; the entry points stay the fallback.
The duck's own registration file is read here, in runfile's environment, where the duck's package is not installed.
Run: cd libs/runfile && uv run python tests/test_registration.py"""

import atexit
import json
import shutil
import tempfile
from importlib.metadata import entry_points
from pathlib import Path

from helpers import Checks, small_profile
from runfile import installation, registry
from runfile.registry import RegistrationError

check = Checks("REGISTRATION")
tmp = Path(tempfile.mkdtemp(prefix="registration-"))
atexit.register(shutil.rmtree, tmp, True)
REPO = Path(__file__).resolve().parents[3]

rover = tmp / "rover"
(rover / "sim").mkdir(parents=True)
(rover / "profile.json").write_text(json.dumps(small_profile()))
GOOD = {"registration": 1, "name": "rover", "profile": "profile.json",
        "payload": [".venv/bin/python", "-m", "rover.payload"], "navigator_api": ["python3", "-m", "rover.server"], "sim": "sim"}


def reg(d, name="registration.json"):
    p = rover / name
    p.write_text(json.dumps(d) if not isinstance(d, str) else d)
    return p


def inst(robots_):
    p = tmp / f"installation-{len(list(tmp.glob('installation-*')))}.json"
    p.write_text(json.dumps({"installation": 1, "robots": robots_}))
    return installation.load(p)


installed = {ep.name for ep in entry_points(group=registry.GROUP)}
check("no robot's package is installed in runfile's environment (what this test proves registration without)", "duck" not in installed,
      installed)
check("no installation: only the entry points", registry.names(None) == sorted(installed))

i = inst({"rover": {"registration": str(reg(GOOD))}})
check("a robot named by a registration file is registered", "rover" in registry.names(i), registry.names(i))
r = registry.module("rover", i)
check("it reads as a robot: its name, its profile beside the file", r.NAME == "rover" and r.PROFILE == rover / "profile.json", r)
check("a command's program given as a relative path is the file's folder's; a plain program name is kept",
      r.PAYLOAD == [str(rover / ".venv/bin/python"), "-m", "rover.payload"] and r.NAVIGATOR_API == ["python3", "-m", "rover.server"], r)
check("its simulator files beside it", r.SIM == rover / "sim")
check("the profile it runs, with no profile named: its own, from the registration (no package needed)",
      registry.profile_file("rover", i) == rover / "profile.json")
no_sim = dict(GOOD)
no_sim.pop("sim")
check("a robot with no simulator files: SIM is None", registry.module("rover", inst({"rover": {"registration": str(reg(no_sim, "r2.json"))}})).SIM is None)
try:
    registry.module("ghost", i)
    said = "found"
except LookupError as e:
    said = str(e)
check("an unregistered name is a LookupError naming both ways of registering", "robots.ghost.registration" in said and "rover" in said, said)

for name, d, why in (
        ("another robot's name", {**GOOD, "name": "duck"}, "registers 'duck', but the installation names it for 'rover'"),
        ("an unknown key", {**GOOD, "host": "x"}, "unknown keys ['host']"),
        ("another version", {**GOOD, "registration": 2}, "this reader knows version 1"),
        ("a profile that does not exist", {**GOOD, "profile": "nope.json"}, "does not exist"),
        ("no profile", {k: v for k, v in GOOD.items() if k != "profile"}, "'profile' must be"),
        ("a command that is not a list", {**GOOD, "payload": "python -m x"}, "'payload' must be a command"),
        ("an empty command", {**GOOD, "navigator_api": []}, "'navigator_api' must be a command"),
        ("not JSON", "{", "not JSON")):
    try:
        registry.module("rover", inst({"rover": {"registration": str(reg(d, "bad.json"))}}))
        said = "accepted"
    except RegistrationError as e:
        said = str(e)
    check(f"must fail: a registration with {name} is refused, naming the file", why in said and "bad.json" in said, said)
try:
    registry.module("rover", inst({"rover": {"registration": str(tmp / "missing.json")}}))
    said = "accepted"
except RegistrationError as e:
    said = str(e)
check("must fail: a registration file that does not exist is refused (no fallback to an entry point)", "no registration file" in said, said)

duck = REPO / "robots/duck/registration.json"
i = inst({"duck": {"registration": str(duck)}})
d = registry.module("duck", i)
check("the duck's own registration file registers the duck where its package is not installed",
      "duck" in registry.names(i) and d.PROFILE == REPO / "robots/duck/profile.json" and d.SIM == REPO / "robots/duck/sim"
      and d.PAYLOAD == [str(REPO / "robots/duck/.venv/bin/python"), "-m", "duck_lab.payload"]
      and d.NAVIGATOR_API[1:] == ["-m", "duck_lab.nav.server"], d)
check("... and its profile is the one this machine runs when the installation names none", registry.profile_file("duck", i) == d.PROFILE)

check.done()
