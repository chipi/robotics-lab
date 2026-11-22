"""The duck's registration file (robots/duck/registration.json, the operator's decision a) says what its entry point's module says,
and a registration the installation names wins over the entry point of the same name. Run in the duck's environment, where the
entry point is installed. Run: cd robots/duck && uv run python tests/test_registration_file.py"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from duck_lab import robot
from runfile import installation, registry

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="duck-registration-"))
try:
    inst_file = tmp / "installation.json"
    inst_file.write_text(json.dumps({"installation": 1, "robots": {"duck": {"registration": str(robot.ROOT / "registration.json")}}}))
    inst = installation.load(inst_file)
    by_file, by_entry = registry.module("duck", inst), registry.module("duck", None)
    check("the entry point is the duck's module (the fallback)", by_entry is robot)
    check("the file names the same profile and simulator files", by_file.PROFILE == by_entry.PROFILE and by_file.SIM == by_entry.SIM,
          (by_file.PROFILE, by_file.SIM))
    check("... and the same navigator commands, run by the duck's own environment's Python",
          by_file.PAYLOAD[1:] == by_entry.PAYLOAD[1:] and by_file.NAVIGATOR_API[1:] == by_entry.NAVIGATOR_API[1:]
          and Path(by_file.PAYLOAD[0]) == robot.ROOT / ".venv/bin/python", (by_file.PAYLOAD, by_entry.PAYLOAD))
    check("that Python is this environment's (the tests run in it)", Path(by_file.PAYLOAD[0]).resolve() == Path(sys.executable).resolve()
          or Path(by_file.PAYLOAD[0]).exists(), (by_file.PAYLOAD[0], sys.executable))

    other = tmp / "duck-elsewhere"
    other.mkdir()
    shutil.copy(robot.PROFILE, other / "profile.json")
    (other / "registration.json").write_text(json.dumps({"registration": 1, "name": "duck", "profile": "profile.json",
                                                         "payload": ["python3", "-m", "x"], "navigator_api": ["python3", "-m", "y"]}))
    inst_file.write_text(json.dumps({"installation": 1, "robots": {"duck": {"registration": str(other / "registration.json")}}}))
    r = registry.module("duck", installation.load(inst_file))
    check("must fail: a registration the installation names wins over the entry point of the same name",
          r is not robot and r.PROFILE == other / "profile.json" and r.PAYLOAD == ["python3", "-m", "x"], r)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("DUCK REGISTRATION", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
