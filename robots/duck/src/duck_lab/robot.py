"""The duck as the platform finds it (RFC-0022): registered in the entry-point group `robotics_lab.robots` (pyproject.toml),
read by a runner (labrunner.robots) that never imports the navigator. Names only: importing this loads nothing else."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # robots/duck
NAME = "duck"
PROFILE = ROOT / "profile.json"
PAYLOAD = [sys.executable, "-m", "duck_lab.payload"]                 # the navigator, for a course (the payload contract)
NAVIGATOR_API = [sys.executable, "-m", "duck_lab.nav.server"]        # the navigator, for Mission Control (the navigator API)
SIM = ROOT / "sim"           # the simulator's files built for the duck: the apartment's layout and objects, phase 1's goals
# The operator's sites (RFC-0016 revision 3): the navigator's memory between runs, read and saved by it (DUCK_SITES overrides)
SITES = Path(os.environ.get("DUCK_SITES", ROOT / "sites"))
