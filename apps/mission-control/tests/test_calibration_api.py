"""A robot's calibration through Mission Control's API (phase 5 item 4a unit A3, RFC-0023 D11, navigator contract 1.3): the procedures and
what each sets, a run of odometry_scale through the navigator (the fake's, arithmetic over the clock), its steps, its value from the
runner's reference or the operator's tape, and keeping it as the next profile version: the table's entry at the speed walked and `scale`
at the speed it was measured at, in the variant the robot runs, with its `measured` line. The refusals: a robot with no profile, bad
parameters, a second run, a held robot, a goal while it runs, a value outside its bounds, a tape where the truth measured, a keep before
anything is measured, a keep the installation would not run. A pointer to the duck's profile behind the fake adapter: no gate, no simulator.
Run: cd apps/mission-control && uv run python tests/test_calibration_api.py"""

import atexit
import json
import os
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from common import FAKE_FILE, Clock, check, finish, installation_file

from mission_control import calibration
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation
from runfile.profilestore import Store

tmp = Path(tempfile.mkdtemp(prefix="mc-calibration-"))
atexit.register(shutil.rmtree, tmp, True)
REPO_FILE = Path(__file__).resolve().parents[3] / "robots" / "duck" / "profile.json"
REPO = json.loads(REPO_FILE.read_text())
STATE = tmp / "inst-state"
FOLDER = STATE / "profiles" / "duck"
inst = tmp / "installation.json"
SCALE, TABLE = "localisation.odometry.scale", "localisation.odometry.by_speed"


def write_installation(profile, variant="sim", state=STATE):
    installation_file(inst, {"duck": {"variant": variant, **({"profile": str(profile)} if profile else {})}}, state=str(state))


def duck(rid, **adapter):
    return RobotConfig({"id": rid, "robot": "duck", "variant": "sim", "adapter": {"type": "fake", **adapter}})


def serving(*configs):
    clock = Clock()
    mc = MissionControl(list(configs), state_dir=tmp / f"state-{len(os.listdir(tmp))}", clock=clock, wall=clock)
    srv = serve(mc, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return mc, clock, f"http://127.0.0.1:{srv.server_address[1]}/api/v1"


write_installation(None)
os.environ[installation.ENV] = str(inst)
mc, clock, BASE = serving(duck("duck-1"), duck("duck-tape", calibration={"truth": False}), RobotConfig(FAKE_FILE))


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def start(rid="duck-1", **params):
    return call("POST", f"/robots/{rid}/calibration", {"procedure": "odometry_scale", "params": {"seconds": 2, **params}})


def finished(rid="duck-1"):
    clock.advance(2.5)
    return call("GET", f"/robots/{rid}/calibration")["calibration"]


# --- the view ---------------------------------------------------------------------------------------------------------------
v = call("GET", "/robots/duck-1/calibration")["calibration"]
p = v["procedures"][0]
check("the view lists odometry_scale: what it sets, the value now (the sim variant's 0.91), the navigator drives it, its guide has four steps",
      [x["id"] for x in v["procedures"]] == ["odometry_scale"] and p["sets"] == SCALE and p["current"] == 0.91 and p["available"] is True
      and [s["id"] for s in p["steps"]] == ["place", "walk", "measure", "keep"] and p["params"]["speed_mps"] == 0.3, p)
check("with no run: none, and why a save cannot be made yet (the installation names no store for the duck)",
      v["run"] is None and v["writable"] is False and "robots.duck.profile" in v["why_not"], (v["run"], v["why_not"]))
check("a robot file that holds the robot itself has no profile to calibrate", call("GET", "/robots/fake-1/calibration")["error"]["code"] == "no_profile")

# --- refusals at the start ----------------------------------------------------------------------------------------------------
check("a speed above the robot's maximum is refused as bad_params, saying so", call("POST", "/robots/duck-1/calibration", {"procedure": "odometry_scale", "params": {"speed_mps": 0.9}})
      ["error"]["code"] == "bad_params")
check("an unknown procedure is 404", call("POST", "/robots/duck-1/calibration", {"procedure": "pivot_creep"})["error"]["code"] == "not_found")
rt = mc.robot("duck-1")
cid = rt.gate.open("operator-laptop")
rt.gate.handle(cid, "gate.acquire")
held = start()
check("a robot held by another client is refused as held, naming the holder", held["error"]["code"] == "held" and held["error"]["holder"] == "operator-laptop", held)
rt.gate.close(cid)

# --- a run, measured by the truth --------------------------------------------------------------------------------------------
r = start()
run = r.get("run", {})
check("a start answers 201 with the run, running, its steps: place done, the walk now",
      run.get("phase") == "running" and run["n"] == 1 and run["params"] == {"speed_mps": 0.3, "seconds": 2.0}
      and [s["status"] for s in run["steps"]] == ["done", "now", "todo", "todo"], r)
check("a second start is refused while it runs", start()["error"]["code"] == "calibration_running")
goal = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 1.0, "y": 0.0}}, "robots": ["duck-1"]})
check("a goal started meanwhile is refused by the navigator, saying a calibration runs", goal.get("run", {}).get("state") == "refused"
      and "calibration" in (goal["run"].get("reason") or ""), goal)
check("keeping before anything is measured is refused", call("POST", "/robots/duck-1/calibration/keep", {})["error"]["code"] == "no_value")
cancelled = call("POST", "/robots/duck-1/calibration/cancel")["run"]
check("a cancel ends it cancelled", cancelled["phase"] == "cancelled" and "cancelled" in cancelled["reason"] and cancelled["value"] is None, cancelled)
check("a finished run can be discarded", call("DELETE", "/robots/duck-1/calibration")["discarded"] == 1
      and call("GET", "/robots/duck-1/calibration")["calibration"]["run"] is None)

start()
run = finished()["run"]
check("done with the runner's reference: measured, the value is reference over odometry (0.6 / 0.66 = 0.909), plausible, the steps one by one",
      run["phase"] == "measured" and run["measured"]["odom_m"] == 0.66 and run["reference"]["by"] == "truth" and run["reference"]["distance_m"] == 0.6
      and run["value"] == 0.909 and run["plausible"] is True and run["current"] == 0.91
      and [s["status"] for s in run["steps"]] == ["done", "done", "done", "now"], run)
check("what keeping it changes: the table's entry at 0.3 and `scale`, the speed it was measured at",
      run["writes"] == [{"path": f"{TABLE}.0.3", "from": 0.911, "to": 0.909}, {"path": SCALE, "from": 0.91, "to": 0.909}], run["writes"])
refused = call("POST", "/robots/duck-1/calibration/keep", {})
check("a keep the installation would not run is refused saying what to set, and nothing is written",
      refused["error"]["code"] == "profile_not_writable" and "robots.duck.profile" in refused["error"]["message"] and not FOLDER.exists(), refused)
check("a tape is refused where the runner measured by the truth", call("POST", "/robots/duck-1/calibration/reference", {"distance_m": 0.6})["error"]["code"] == "reference_by_truth")

write_installation(FOLDER)
kept = call("POST", "/robots/duck-1/calibration/keep", {})
check("keep: 201, the run is kept as version 2, from the next goal", kept.get("run", {}).get("kept", {}).get("version") == 2
      and kept["run"]["phase"] == "kept" and kept["run"]["kept"]["applies"] == "from the next goal", kept)
saved = json.loads((FOLDER / "2.json").read_text())
odo = saved["variants"]["sim"]["localisation"]["odometry"]
check("version 2 holds the value in the sim variant: scale and the table's 0.3 entry, the rest of the table and the old why kept",
      odo["scale"] == 0.909 and odo["by_speed"] == {"0.2": 0.849, "0.3": 0.909, "0.4": 0.93} and odo["at_speed_mps"] == 0.3
      and odo["why"] == REPO["variants"]["sim"]["localisation"]["odometry"]["why"], odo)
check("its measured line says when, by what, the numbers, and what it replaced, and keeps the line before it",
      odo["measured"].startswith("1970-01-01, Mission Control's calibration procedure odometry_scale (run 2, replacing version the robot file): "
                                 "the robot walked straight at 0.3 m/s for 2 s; the odometry read 0.66 m, the simulator's truth, read by the runner 0.6 m; "
                                 "reference over odometry 0.909.") and odo["measured"].endswith(
                                     "Before this: " + REPO["variants"]["sim"]["localisation"]["odometry"]["measured"]), odo["measured"][:260])
check("nothing else in the profile changed", {k: v for k, v in saved.items() if k != "variants"} == {k: v for k, v in REPO.items() if k != "variants"}
      and saved["variants"]["real"] == REPO["variants"]["real"], None)
v = call("GET", "/robots/duck-1/calibration")["calibration"]
check("Mission Control now runs version 2: the value now is the kept one, and the kept run still says what it changed",
      v["procedures"][0]["current"] == 0.909 and v["run"]["kept"]["writes"][1] == {"path": SCALE, "from": 0.91, "to": 0.909}
      and call("GET", "/robots/duck-1/profile")["profile"]["current"] == 2, v["run"]["kept"])
check("a kept run is kept once", call("POST", "/robots/duck-1/calibration/keep", {})["error"]["code"] == "already_kept")
check("the Calibration view's `measured` row is the new line (a profile diff names it)", call("GET", "/robots/duck-1/profile/diff?a=1&b=2&notes=1")["diff"]["notes_changed"] == 1)

# --- a speed that is not the one the scale was measured at: the table only -----------------------------------------------------
start(speed_mps=0.2)
run = finished()["run"]
check("at 0.2 m/s the value goes to the table's 0.2 entry only: `scale` is the table's value at 0.3, and stays",
      [w["path"] for w in run["writes"]] == [f"{TABLE}.0.2"] and run["value"] == 0.909, run["writes"])
kept = call("POST", "/robots/duck-1/calibration/keep", {})["run"]
odo = json.loads((FOLDER / "3.json").read_text())["variants"]["sim"]["localisation"]["odometry"]
check("version 3: by_speed 0.2 changed, scale and the 0.3 entry untouched, and the table still agrees with scale", kept["kept"]["version"] == 3
      and odo["by_speed"] == {"0.2": 0.909, "0.3": 0.909, "0.4": 0.93} and odo["scale"] == 0.909, odo)

# --- no truth: the operator's tape ---------------------------------------------------------------------------------------------
start("duck-tape")
run = finished("duck-tape")["run"]
check("without a runner truth, done waits for the tape: no reference, no value, step three now", run["phase"] == "needs_tape" and run["reference"] is None
      and run["value"] is None and [s["status"] for s in run["steps"]] == ["done", "done", "now", "todo"], run)
check("keeping with no tape is refused", call("POST", "/robots/duck-tape/calibration/keep", {})["error"]["code"] == "no_value")
check("a tape of 0 or text is refused", call("POST", "/robots/duck-tape/calibration/reference", {"distance_m": 0})["error"]["code"] == "invalid"
      and call("POST", "/robots/duck-tape/calibration/reference", {"distance_m": "0.6"})["error"]["code"] == "invalid")
run = call("POST", "/robots/duck-tape/calibration/reference", {"distance_m": 0.1})["run"]
check("a tape of 0.1 m gives 0.152: outside 0.5 to 1.5, not plausible", run["value"] == 0.152 and run["plausible"] is False and run["reference"]["by"] == "operator", run)
implausible = call("POST", "/robots/duck-tape/calibration/keep", {})
check("an implausible value is refused, nothing written (version 3 is still the last)", implausible["error"]["code"] == "implausible"
      and not (FOLDER / "4.json").exists(), implausible)
run = call("POST", "/robots/duck-tape/calibration/reference", {"distance_m": 0.57})["run"]
check("the tape entered again replaces it: 0.57 / 0.66 = 0.864 by the operator's tape", run["value"] == 0.864 and run["phase"] == "measured", run)
kept = call("POST", "/robots/duck-tape/calibration/keep", {})["run"]
note = json.loads((FOLDER / "4.json").read_text())["variants"]["sim"]["localisation"]["odometry"]["measured"]
check("kept as version 4, the line names the operator's tape", kept["kept"]["version"] == 4 and "the operator's tape 0.57 m" in note, note[:200])
check("a run is discarded before a new one; running cannot be discarded", start("duck-tape")["run"]["n"] == 2
      and call("DELETE", "/robots/duck-tape/calibration")["error"]["code"] == "calibration_running")

# --- the real variant: `{}` in the profile, no table ----------------------------------------------------------------------------
STATE2 = tmp / "inst-state-real"
Store(STATE2 / "profiles").seed("duck", REPO_FILE)       # a store the installation names is made before anything reads it
write_installation(STATE2 / "profiles" / "duck", variant="real", state=STATE2)
mc2, clock, BASE = serving(RobotConfig({"id": "duck-real", "robot": "duck", "variant": "real", "adapter": {"type": "fake"}}))
v = call("GET", "/robots/duck-real/calibration")["calibration"]
check("the real variant: the scale now is 1.0 (the base's), no table", v["variant"] == "real" and v["procedures"][0]["current"] == 1.0)
start("duck-real")
run = finished("duck-real")["run"]
check("its value goes to `scale` only", [w["path"] for w in run["writes"]] == [SCALE] and run["writes"][0]["from"] == 1.0, run["writes"])
kept = call("POST", "/robots/duck-real/calibration/keep", {})
real = json.loads((STATE2 / "profiles" / "duck" / "2.json").read_text())
odo = real["variants"]["real"]["localisation"]["odometry"]
check("the real variant of version 2 carries scale, a measured line and a why of its own: the profile validates, sim untouched",
      kept["run"]["kept"]["version"] == 2 and odo["scale"] == 0.909 and odo["measured"].startswith("1970-01-01, Mission Control's calibration procedure")
      and "why" in odo and real["variants"]["sim"] == REPO["variants"]["sim"], odo)

# --- the rule itself -------------------------------------------------------------------------------------------------------------
check("_writes: a profile with no table gets `scale`; a table with no at_speed_mps gets its entry only",
      calibration._writes({"scale": 1.0}, 0.3, 0.9) == [(SCALE, 1.0, 0.9)] and calibration._writes({"by_speed": {"0.3": 0.9}}, 0.3, 0.8) == [(f"{TABLE}.0.3", 0.9, 0.8)])

finish("test_calibration_api")
