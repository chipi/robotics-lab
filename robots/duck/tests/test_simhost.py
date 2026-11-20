"""The host file and the host's reset (RFC-0021 §5 step 1): a host file read, refused when wrong, never defaulted to this
workstation; the sockets it names; `simhost init` and `show`; the reset's refusal of a duck-sim that asks sudo. No
simulator. Run: cd robots/duck && uv run python tests/test_simhost.py"""

import atexit
import contextlib
import io
import json
import os
import shutil
import tempfile
from pathlib import Path

import simhost
from simhost import cli
from simhost.host import HostError

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="simhost-"))
atexit.register(shutil.rmtree, tmp, True)
GOOD = {"host": 1, "kind": "pollen-duck-sim", "robot": "duck-a",
        "pollen": {"microduck": str(tmp / "microduck"), "microduck_rl": str(tmp / "rl")},
        "state": str(tmp / "state"), "truth_port": 7801, "cargo_bin": "~/.cargo/bin"}


def write(d, name="host.json") -> Path:
    p = tmp / name
    p.write_text(json.dumps(d))
    return p


def refused(d) -> str:
    try:
        simhost.load(write(d, "bad.json"))
    except HostError as e:
        return str(e)
    return ""


h = simhost.load(write(GOOD))
check("the sockets are duck-sim's, in the state folder, by the robot's name",
      h.sockets == {"robot": tmp / "state/duck-a.sock", "depth": tmp / "state/duck-a-tof.sock",
                    "map": tmp / "state/duck-a-map.sock", "gate": tmp / "state/duck-a-gate.sock"}, h.sockets)
check("the scenarios and Pollen's scene folder come from the host",
      h.scenarios == tmp / "state/scenarios" and h.scene_dir == tmp / "rl/src/mjlab_microduck/robot/microduck")
check("~ in a path is this user's home", h.cargo_bin == Path(os.path.expanduser("~/.cargo/bin")), h.cargo_bin)
named = simhost.load(write({**GOOD, "sockets": {"robot": "/fwd/duck.sock"}, "truth_port": None}, "named.json"))
check("a socket the file names is used, the others stay duck-sim's",
      named.sockets["robot"] == Path("/fwd/duck.sock") and named.sockets["map"] == tmp / "state/duck-a-map.sock")
check("a host with no truth says so (null port)", named.truth_port is None)
check("as_json reads back as the same host", simhost.parse(h.as_json(), h.source) == h)

for why, d, says in [("an unknown key", {**GOOD, "data": "/x"}, "unknown keys"),
                     ("another version", {**GOOD, "host": 2}, "version 1"),
                     ("another kind", {**GOOD, "kind": "gazebo"}, "kind"),
                     ("a robot with a path in it", {**GOOD, "robot": "../x"}, "robot"),
                     ("one Pollen checkout missing", {**GOOD, "pollen": {"microduck": "/a"}}, "pollen"),
                     ("a port out of range", {**GOOD, "truth_port": 70000}, "truth_port"),
                     ("a port that is a bool", {**GOOD, "truth_port": True}, "truth_port"),
                     ("a socket key not known", {**GOOD, "sockets": {"camera": "/c"}}, "sockets")]:
    msg = refused(d)
    check(f"refused: {why}, the reason named with the file", says in msg and "bad.json" in msg, msg)

os.environ.pop(simhost.ENV, None)
missing = tmp / "none" / "host.json"
try:
    simhost.load(missing)
    msg = ""
except HostError as e:
    msg = str(e)
check("a missing host file is an error that names the file and `simhost init` (no fallback)",
      str(missing) in msg and "simhost init" in msg, msg)
os.environ[simhost.ENV] = str(write(GOOD, "from-env.json"))
check("$ROBOTICS_LAB_HOST is read when no file is given", simhost.where() == tmp / "from-env.json")
check("a file given wins over $ROBOTICS_LAB_HOST", simhost.where(tmp / "host.json") == tmp / "host.json")
os.environ.pop(simhost.ENV)
check("else the default under ~/.config", simhost.where() == Path(os.path.expanduser("~/.config/robotics-lab/host.json")))

out = tmp / "init" / "host.json"
with contextlib.redirect_stdout(io.StringIO()):
    code = cli.main(["--host", str(out), "init", "--microduck", "/p/microduck", "--microduck-rl", "/p/rl"])
check("simhost init writes a host file that loads", code == 0 and simhost.load(out).microduck == Path("/p/microduck"))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    code = cli.main(["--host", str(out), "init", "--microduck", "/q", "--microduck-rl", "/q"])
check("simhost init does not replace a host file without --force",
      code == 1 and simhost.load(out).microduck == Path("/p/microduck"), err.getvalue())
with contextlib.redirect_stdout(io.StringIO()):
    code = cli.main(["--host", str(out), "init", "--microduck", "/q", "--microduck-rl", "/q", "--truth-port", "0", "--force"])
check("--force replaces it; --truth-port 0 is a host with no truth",
      code == 0 and simhost.load(out).microduck == Path("/q") and simhost.load(out).truth_port is None)
shown = io.StringIO()
with contextlib.redirect_stdout(shown):
    code = cli.main(["--host", str(out), "show"])
check("simhost show prints the file read and its sockets", code == 0 and str(out) in shown.getvalue()
      and "duck-a-map.sock" in shown.getvalue(), shown.getvalue()[:200])
err = io.StringIO()
with contextlib.redirect_stderr(err):
    code = cli.main(["--host", str(missing), "show"])
check("a command with no host file exits 2 and says why", code == 2 and "no host file" in err.getvalue(), err.getvalue())

# The host's reset never calls a duck-sim that asks sudo with no terminal (docs/wip/DUCK-SIM-FOR-AGENTS.md).
(tmp / "microduck" / "scripts").mkdir(parents=True)
sim_script = tmp / "microduck" / "scripts" / "duck-sim"
sim_script.write_text('        if sudo systemctl is-active --quiet "$name" 2>/dev/null; then\n')
try:
    simhost.duck_sim(h)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("an unpatched duck-sim (sudo on every down) is refused, the patch named", "duck-sim-sudo-free-down.patch" in msg, msg)
sim_script.write_text('        if systemctl is-active --quiet "$name" 2>/dev/null; then\n')
check("a patched duck-sim is used, from the host's microduck checkout", simhost.duck_sim(h) == str(sim_script))

print()
print("FAIL: " + ", ".join(failures) if failures else "all passed")
raise SystemExit(1 if failures else 0)
