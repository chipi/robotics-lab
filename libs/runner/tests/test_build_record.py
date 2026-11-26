"""A run's build identity and the depth impairment, from the runner (runfile/build.py, labrunner.remote.Remote): the official run's
record carries the identity and its parts beside the referee's fields, the runner's `--depth-impairment SEED` reaches the payload as
its own option and is the `tof@` part of the identity, and a real robot refuses it before any process starts. No robot's package: a
stand-in registration, no simulator. Run: cd libs/runner && uv run python tests/test_build_record.py"""

import argparse
import atexit
import shutil
import subprocess
import tempfile
import types
from pathlib import Path

from labrunner import remote, robots
from runfile import build

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:400]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="build-record-"))
atexit.register(shutil.rmtree, tmp, True)
own = Path(__file__).resolve().parents[3] / "robots" / "duck" / "profile.json"      # a valid profile, with the simulator's impairment block (off)
fake = types.SimpleNamespace(NAME="rover", PAYLOAD=["rover-payload"], NAVIGATOR_API=["rover-nav"], SIM=tmp, PROFILE=own)
head = subprocess.run(["git", "-C", str(Path(remote.__file__).parent), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

sim_repo = tmp / "rl"
sim_repo.mkdir()
for args in (("init", "-q"), ("commit", "-q", "--allow-empty", "-m", "x")):
    subprocess.run(["git", "-C", str(sim_repo), "-c", "user.name=t", "-c", "user.email=t@e.com", *args], check=True, capture_output=True)
sim_head = subprocess.run(["git", "-C", str(sim_repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
state = tmp / "state"
state.mkdir()
policy = tmp / "velstand.onnx"
policy.write_bytes(b"walk")
(state / "robotd-duck-a.toml").write_text(f'[policy]\nwalk = "{policy}"\n')
host = types.SimpleNamespace(sockets={"robot": tmp / "r.sock", "depth": tmp / "d.sock", "map": tmp / "m.sock"}, truth_port=1,
                             microduck_rl=sim_repo, state=state, robot="duck-a")


class Started(Exception):
    pass


def start(variant="sim", **kw):
    """Remote up to the payload's start: what its command and its official run's record were."""
    seen = {}
    real_get, real_popen, real_copy = robots.get, remote.subprocess.Popen, remote.TruthCopy
    robots.get = lambda name=None: fake
    robots._resolved.clear()
    robots._resolved["rover"] = (None, own)

    def popen(cmd, *a, **k):
        if cmd[0] == "git":          # the build reads the commit with git through the same subprocess module
            return real_popen(cmd, *a, **k)
        seen["cmd"] = cmd
        raise Started()

    def copy(*a, run=None, **k):
        seen["run"] = run
        return types.SimpleNamespace()
    remote.subprocess.Popen, remote.TruthCopy = popen, copy
    out = tmp / f"run{len(list(tmp.glob('run*')))}"
    out.mkdir()
    tempfile.tempdir = str(tmp)
    try:
        remote.Remote(host, out, "apartment", "r", tmp / "data", "rover/apartment/r", truth_log=types.SimpleNamespace(nearest=None),
                      variant=variant, run={"kind": "challenge"}, **kw)
    except Started:
        pass
    except Exception as e:      # noqa: BLE001 - the refusal is the answer
        seen["error"] = e
    finally:
        remote.subprocess.Popen, remote.TruthCopy, robots.get = real_popen, real_copy, real_get
        robots._resolved.clear()
        tempfile.tempdir = None
    return seen


# ---- the official run's record carries the build ---------------------------------------------------------------------------------
seen = start()
b = (seen.get("run") or {}).get("build") or {}
check("the run record has `build`: the string and its parts", {"id", "brain", "ctrl", "walker", "sim", "tof", "seed", "dirty"} <= set(b), b)
check("brain is this checkout's HEAD, 12 characters (-dirty when a tracked file differs)", b.get("brain", "").startswith(head[:12]), (b.get("brain"), head[:12]))
check("ctrl is the local controller of today, rules@1", b.get("ctrl") == "rules@1", b.get("ctrl"))
check("sim is the simulator checkout's HEAD, 8 characters; walker 8 of the policy file's sha256",
      b.get("sim") == sim_head[:8] and b.get("walker") == build.sha8(policy) != "unknown", b)
check("off by default: tof@off-s0, and the payload is not handed the option",
      b.get("id", "").endswith("+tof@off-s0") and "--depth-impairment" not in seen.get("cmd", []), (b.get("id"), seen.get("cmd")))
check("the runner's own fields stay beside it", (seen.get("run") or {}).get("kind") == "challenge" and "judge_truth" in seen["run"], seen.get("run"))

# ---- the impairment, from the runner ------------------------------------------------------------------------------------------------
seen = start(depth_impairment=7)
cmd = seen.get("cmd") or []
check("--depth-impairment SEED reaches the payload as its own option", "--depth-impairment" in cmd and cmd[cmd.index("--depth-impairment") + 1] == "7", cmd)
check("and is the identity's tof part: tof@nvidia-s7", seen["run"]["build"]["id"].endswith("+tof@nvidia-s7")
      and seen["run"]["build"]["tof"] == "nvidia" and seen["run"]["build"]["seed"] == 7, seen["run"]["build"])
seen = start(depth_impairment=0)
check("seed 0 is a seed, not off", "--depth-impairment" in (seen.get("cmd") or []) and seen["run"]["build"]["tof"] == "nvidia", seen.get("cmd"))
seen = start(variant="real", depth_impairment=7)
check("must fail: a real robot refuses it, before any process starts or any run is written",
      isinstance(seen.get("error"), ValueError) and "cmd" not in seen and "run" not in seen, seen.get("error"))
seen = start(variant="real")
check("a real robot with no impairment runs: sim is real, walker unknown", seen["run"]["build"]["sim"] == "real"
      and seen["run"]["build"]["walker"] == "unknown", seen.get("run"))

# ---- the local controller, from the runner -----------------------------------------------------------------------------------------
model = tmp / "policy.onnx"
model.write_bytes(b"a navigation policy")
setting = {"name": "learned", "model": str(model)}
learned = f"learned@{build.sha8(model)}"
seen = start(local_controller=setting)
cmd = seen.get("cmd") or []
check("--local-controller learned --model PATH reaches the payload as its own options",
      "--local-controller" in cmd and cmd[cmd.index("--local-controller") + 1] == "learned" and cmd[cmd.index("--model") + 1] == str(model), cmd)
check("and is the identity's ctrl part: learned@<8 of the model's sha256>", seen["run"]["build"]["ctrl"] == learned
      and f"+ctrl@{learned}+" in seen["run"]["build"]["id"], seen["run"]["build"])
seen = start()
check("with none the payload is not handed it, and ctrl stays rules@1", "--local-controller" not in (seen.get("cmd") or []) and seen["run"]["build"]["ctrl"] == "rules@1")
seen = start(variant="real", local_controller=setting)
check("must fail: a real robot refuses it, before any process starts or any run is written",
      isinstance(seen.get("error"), ValueError) and "cmd" not in seen and "run" not in seen, seen.get("error"))

ap = argparse.ArgumentParser()
remote.add_controller_args(ap)
check("the options are --local-controller {rules,learned} and --model PATH; absent: no setting",
      remote.controller_setting(ap.parse_args([]), ap) is None
      and remote.controller_setting(ap.parse_args(["--local-controller", "rules"]), ap) is None
      and remote.controller_setting(ap.parse_args(["--local-controller", "learned", "--model", str(model)]), ap) == setting)
for argv in (["--local-controller", "learned"], ["--model", str(model)], ["--local-controller", "learned", "--model", str(tmp / "no.onnx")],
             ["--local-controller", "rules", "--model", str(model)]):
    try:
        remote.controller_setting(ap.parse_args(argv), ap)
        refused = False
    except SystemExit:
        refused = True
    check(f"must fail: {' '.join(argv[:2])} ... is refused at the command line", refused, argv)

on_in_profile = types.SimpleNamespace(sensors=types.SimpleNamespace(tof8x8={"impairment": {"enabled": True, "seed": 3}}))
check("a profile version with the impairment on (and no option) is recorded as on, with its seed",
      build.tof(remote.impairment_in_force("sim", None, on_in_profile)) == ("nvidia", 3))
check("the option overrides the profile's setting; a real robot has none", remote.impairment_in_force("sim", 9, on_in_profile) == {"enabled": True, "seed": 9}
      and remote.impairment_in_force("real", None, on_in_profile) is None)

# ---- the command line ------------------------------------------------------------------------------------------------------------
ap = argparse.ArgumentParser()
remote.add_impairment_arg(ap)
check("the option is --depth-impairment SEED (an integer), absent: None", ap.parse_args([]).depth_impairment is None
      and ap.parse_args(["--depth-impairment", "4"]).depth_impairment == 4)
check("run i of a batch has seed + i; a probe (one fixed seed) keeps it",
      [remote.impairment_seed(4, i) for i in range(3)] == [4, 5, 6] and remote.impairment_seed(None, 2) is None
      and remote.impairment_seed(4, 2, probe=True) == 4)

print()
print("BUILD RECORD", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
