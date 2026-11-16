"""The setup file and its odometry settings (ADR-0013). Run: make test-unit (or python nxt/tests/test_config.py)."""

import json
import sys
import tempfile
from pathlib import Path

from nxt_lab import config as cfgmod
from nxt_lab.config import Config

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError as e:
        return str(e)
    return None


c = Config()
check("the wheel geometry is unset by default: no pose is recorded until it is calibrated", c.odom_sprocket_diameter_m is None and c.odom_track_width_m is None)
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "config.json"
    cfgmod.save(Config(odom_sprocket_diameter_m=0.043, odom_track_width_m=0.118), path)
    back = cfgmod.load(path)
    check("both values survive a save and a load", back.odom_sprocket_diameter_m == 0.043 and back.odom_track_width_m == 0.118
          and json.loads(path.read_text())["odom_track_width_m"] == 0.118)
    old = {k: v for k, v in Config().to_dict().items() if not k.startswith("odom_")}
    path.write_text(json.dumps(old))
    check("a config.json from before the settings existed loads, with them unset", cfgmod.load(path).odom_track_width_m is None)
check("the page sends an emptied field as null or an empty string: both mean unset",
      Config.from_dict({"odom_sprocket_diameter_m": None, "odom_track_width_m": ""}).odom_track_width_m is None)
check("numbers sent as text are numbers", Config.from_dict({"odom_sprocket_diameter_m": "0.05"}).odom_sprocket_diameter_m == 0.05)
check("zero, a negative width or one over a metre is refused (and it says which setting)",
      all(raises(Config.from_dict, {k: v}) and k in raises(Config.from_dict, {k: v}) for k, v in
          (("odom_sprocket_diameter_m", 0), ("odom_track_width_m", -0.1), ("odom_track_width_m", 2.0))))
check("text that is not a number is refused", raises(Config.from_dict, {"odom_track_width_m": "wide"}) is not None)

print("test_config", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
