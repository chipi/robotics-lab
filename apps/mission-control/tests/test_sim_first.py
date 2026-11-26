"""The simulator-first flag (RFC-0014 §3.4.2, phase 5 item 4b unit B8): a goal flagged `sim_first` runs on the real robot only after a passing run
of the same goal in the simulator, and the real run records which run rehearsed it. Through Mission Control's API, on two stand-ins of the
duck behind the fake adapter (no adapter for the real duck exists yet): `duck-sim`, whose variant the test sets to sim (the installation names
one variant for a robot, so the twin is set by hand), and `duck-real`. A run the navigator tagged `rtf_low` has no verdict and rehearses nothing.
Run: cd apps/mission-control && uv run python tests/test_sim_first.py"""

import atexit
import json
import os
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from common import FAKE_FILE, Clock, check, finish, finish_run, installation_file, run_for

from mission_control import goals, planning
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation

tmp = Path(tempfile.mkdtemp(prefix="mc-sim-first-"))
atexit.register(shutil.rmtree, tmp, True)
inst = installation_file(tmp / "installation.json", state=str(tmp / "inst-state"))
os.environ[installation.ENV] = str(inst)
clock = Clock()
mc = MissionControl([RobotConfig({"id": "duck-sim", "robot": "duck", "adapter": {"type": "fake"}}),
                     RobotConfig({"id": "duck-real", "robot": "duck", "adapter": {"type": "fake", "allow_real_runs": True}}),
                     RobotConfig({"id": "duck-held", "robot": "duck", "adapter": {"type": "fake"}}), RobotConfig(FAKE_FILE)],
                    state_dir=tmp / "state", clock=clock, wall=clock)
mc.robot("duck-sim").cfg.variant = "sim"
srv = serve(mc, "127.0.0.1", 0)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
run_for(mc, clock, 0.5)


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


POINT = {"kind": "point", "params": {"x": 1.0, "y": 0.0}, "name": "to the door", "sim_first": True}


def run(gid, robot, target):
    st, b = call("POST", f"/goals/{gid}/runs", {"robots": [robot], "target": target})
    assert st in (200, 201), (st, b)
    return b["run"]


def done(r):
    return finish_run(mc, clock, r["id"]) if r["state"] in goals.ACTIVE else r


# --- the flag as a field of the goal ---------------------------------------------------------------------------------------------
st, b = call("POST", "/goals", {**POINT, "sim_first": "yes"})
check("must fail: sim_first is true or false: a string is a 422 bad_goal", st == 422 and b["error"]["code"] == "bad_goal", b)
st, b = call("POST", "/goals", POINT)
gid = b["goal"]["id"]
check("a goal takes sim_first and answers it", st == 201 and b["goal"]["sim_first"] is True, b)
st, b2 = call("POST", "/goals", {**POINT, "name": "plain", "sim_first": False})
check("a goal that opts out keeps the field as false (absent now means on, for a real robot)", b2["goal"].get("sim_first") is False, b2)
plain = b2["goal"]["id"]
st, b3 = call("POST", "/goals", {k: v for k, v in POINT.items() if k != "sim_first"} | {"name": "unsaid"})
check("a goal that never heard of it has no field", st == 201 and "sim_first" not in b3["goal"], b3)
unsaid = b3["goal"]["id"]
v = planning.version(planning.validate(POINT))
check("a goal's version is its content: not its name, folder or the flag; any other edit changes it",
      v == planning.version(planning.validate({**POINT, "name": "other", "folder": "x", "sim_first": False}))
      and v != planning.version(planning.validate({**POINT, "params": {"x": 1.1, "y": 0.0}}))
      and v != planning.version(planning.validate({**POINT, "done_when": {"within_m": 0.5}})), v)

# --- the real robot, before any rehearsal ---------------------------------------------------------------------------------------------
r = run(gid, "duck-real", "real")
check("must fail: a sim_first goal is refused on the real robot with no rehearsal, saying what to rehearse and where",
      r["state"] == "refused" and "simulator-first" in r["reason"] and "duck-sim" in r["reason"] and "24 h" in r["reason"], r["reason"])
check("... and the refusal records the rehearsal it lacked: flagged, not rehearsed, the goal's version",
      r["conditions"]["rehearsal"] == {"flagged": True, "state": "not_rehearsed", "run": None, "robot": None, "goal_version": v,
                                       "rehearse_on": "duck-sim"} and r["as_expected"] is False, r["conditions"])
check("the robot was not moved or held: no goal runs on it", mc.get_robot("duck-real")["goal_run"] is None)
r = run(unsaid, "duck-real", "real")
check("must fail: a goal that says nothing is simulator-first by default on a real robot: refused, the rehearsal records flagged",
      r["state"] == "refused" and "simulator-first" in r["reason"] and r["conditions"]["rehearsal"]["flagged"] is True, r["conditions"])
r = done(run(plain, "duck-real", "real"))
check("a goal with sim_first false runs on the real robot unrehearsed, and its run says so (the opt-out, not a refusal)",
      r["state"] == "reached" and r["conditions"]["rehearsal"]["flagged"] is False and r["conditions"]["rehearsal"]["state"] == "not_rehearsed", r["conditions"])
r = done(run(gid, "duck-sim", "sim"))
check("a sim run of the flagged goal is not held to the flag, and records no rehearsal (it is the rehearsal)",
      r["state"] == "reached" and "rehearsal" not in r["conditions"] and r["as_expected"] is True, r["conditions"])
sim_run = r["id"]
r = run(gid, "duck-sim", "real")
check("must fail: the sim robot cannot rehearse itself: target real on it has no simulator twin, so it is refused",
      r["state"] == "refused" and r["conditions"]["rehearsal"]["rehearse_on"] is None and "a simulated robot of the same kind" in r["reason"], r["reason"])

# --- after the rehearsal ------------------------------------------------------------------------------------------------------------------
r = done(run(gid, "duck-real", "real"))
check("after a passing sim run of the same goal the real run starts and ends as expected, and records the run that rehearsed it",
      r["state"] == "reached" and r["as_expected"] is True and r["conditions"]["rehearsal"]["state"] == "rehearsed"
      and r["conditions"]["rehearsal"]["run"] == sim_run and r["conditions"]["rehearsal"]["robot"] == "duck-sim"
      and r["conditions"]["rehearsal"]["flagged"] is True, r["conditions"])
first_real = r["id"]
r = done(run(gid, "duck-real", "real"))
check("the rehearsal is not used up: a second real run names the same sim run", r["conditions"]["rehearsal"]["run"] == sim_run, r["conditions"])
st, b = call("PUT", f"/goals/{gid}", {**POINT, "name": "renamed", "folder": "doors"})
r = done(run(gid, "duck-real", "real"))
check("renaming the goal or moving it to a folder keeps its rehearsal", st == 200 and r["state"] == "reached" and r["conditions"]["rehearsal"]["run"] == sim_run, r["reason"])
st, b = call("PUT", f"/goals/{gid}", {**POINT, "params": {"x": 1.2, "y": 0.0}})
r = run(gid, "duck-real", "real")
check("must fail: editing what the goal asks for (the point moved 0.2 m) is a new version: refused again, no rehearsal found",
      st == 200 and r["state"] == "refused" and r["conditions"]["rehearsal"]["run"] is None
      and r["conditions"]["rehearsal"]["goal_version"] != v, r["conditions"])
st, b = call("PUT", f"/goals/{gid}", POINT)
r = done(run(gid, "duck-real", "real"))
check("put back as it was, it is the version that was rehearsed: allowed", r["state"] == "reached" and r["conditions"]["rehearsal"]["run"] == sim_run, r["conditions"])

# --- what is not a rehearsal ---------------------------------------------------------------------------------------------------------------
far = call("POST", "/goals", {"kind": "point", "params": {"x": 2.0, "y": 0.0}, "name": "far", "sim_first": True})[1]["goal"]["id"]
r = run(far, "duck-sim", "sim")
mc.cancel_run(r["id"])
r = done(call("GET", f"/goal-runs/{r['id']}")[1]["run"])
check("a sim run that did not end as expected (cancelled)", r["state"] == "cancelled" and r["as_expected"] is False, r["state"])
r = run(far, "duck-real", "real")
check("must fail: ... rehearses nothing", r["state"] == "refused" and r["conditions"]["rehearsal"]["run"] is None, r["reason"])

slow = call("POST", "/goals", {"kind": "point", "params": {"x": 2.0, "y": 0.1}, "name": "slow", "sim_first": True})[1]["goal"]["id"]
r = run(slow, "duck-sim", "sim")
run_for(mc, clock, 0.3)
mc._anomaly(mc.robot("duck-sim"), {"n": 1, "t": 1.0, "anomaly": "rtf_low", "severity": "minor", "source": "harness",
                                   "summary": "the simulator ran at 0.72 of real time", "values": {"rtf": 0.72}})
r = done(r)
check("a sim run the runner tagged rtf_low ends in the state the navigator gave, with no verdict: as_expected null, no_verdict says why",
      r["state"] == "reached" and r["as_expected"] is None and r["no_verdict"].startswith("rtf_low: the simulator ran at 0.72"), (r["state"], r["as_expected"], r["no_verdict"]))
shown = call("GET", f"/goal-runs/{r['id']}")[1]["run"]
check("... and the run's anomalies list it", [a["anomaly"] for a in shown["anomalies"]] == ["rtf_low"], shown.get("anomalies"))
r = run(slow, "duck-real", "real")
check("must fail: ... and it rehearses nothing: the real run is refused", r["state"] == "refused" and r["conditions"]["rehearsal"]["run"] is None, r["reason"])
r = done(run(slow, "duck-sim", "sim"))
check("a good sim run of the same goal after it does rehearse (the newest passing one)", r["as_expected"] is True and r["no_verdict"] is None, r)
rehearsed = run(slow, "duck-real", "real")
check("... the real run is allowed, and names that run, not the one with no verdict", rehearsed["conditions"]["rehearsal"]["run"] == r["id"], rehearsed["conditions"])
done(rehearsed)

old = call("POST", "/goals", {"kind": "point", "params": {"x": 0.5, "y": 0.5}, "name": "old", "sim_first": True})[1]["goal"]["id"]
done(run(old, "duck-sim", "sim"))
clock.advance(goals.REHEARSAL_MAX_AGE_S + 1)
run_for(mc, clock, 0.5)
r = run(old, "duck-real", "real")
check("must fail: a rehearsal older than 24 h is not one: refused", r["state"] == "refused" and r["conditions"]["rehearsal"]["run"] is None, r["reason"])

site = call("POST", "/sites", {"name": "Home", "kind": "apartment"})[1]["site"]["id"]
there = call("POST", "/goals", {"kind": "point", "params": {"x": 0.4, "y": 0.4}, "name": "there", "sim_first": True})[1]["goal"]["id"]
st, b = call("POST", f"/goals/{there}/runs", {"robots": ["duck-sim"], "target": "sim", "site": site})
done(b["run"])
r = run(there, "duck-real", "real")
check("must fail: a rehearsal in another site (the sim run had one, the real run has none) is not one", r["state"] == "refused", r["reason"])
st, b = call("POST", f"/goals/{there}/runs", {"robots": ["duck-real"], "target": "real", "site": site})
check("... in the same site it is one", b["run"]["conditions"]["rehearsal"]["state"] == "rehearsed", b["run"]["conditions"])
done(b["run"])

# --- other robots, other doors ---------------------------------------------------------------------------------------------------------------
st, b = call("POST", f"/goals/{gid}/runs", {"robots": ["fake-1"], "target": "real"})
check("the fake robot is still not a real robot: a 422, not a rehearsal question", st == 422, b)
r = run(gid, "fake-1", "sim")
check("a fake robot (no registered kind) on the simulator target carries no rehearsal record and is not held to the flag",
      r["state"] != "refused" and "rehearsal" not in r["conditions"], r["conditions"])
st, b = call("POST", "/goal-runs", {"goal": {**POINT, "name": "adhoc"}, "robots": ["duck-real"], "target": "real"})
check("an ad-hoc goal with the flag is held to it too: refused, nothing rehearsed", b["run"]["state"] == "refused", b["run"]["reason"])
st, b = call("POST", "/goal-runs", {"goal": {**POINT, "name": "adhoc"}, "robots": ["duck-real", "duck-sim"], "share": "each", "target": "real"})
kids = {k["robot"]: k for k in b["run"]["children"]}
check("a group on the real target: each robot is held on its own (the real one refused, the sim one has no twin: refused too)",
      kids["duck-real"]["state"] == "refused" and kids["duck-sim"]["state"] == "refused", {k: v["reason"][:60] for k, v in kids.items()})

# --- a real robot whose file does not allow real runs (B6): the refusal comes first, and simulator-first stays on top of it ----------------------------
r = run(plain, "duck-held", "real")
check("must fail: a robot of the real variant whose file has no allow_real_runs refuses even a goal with no flag, naming the key and the review",
      r["state"] == "refused" and "allow_real_runs" in r["reason"] and "REAL-DUCK-SAFETY-REVIEW" in r["reason"], r["reason"])
r = run(gid, "duck-held", "real")
check("... and a flagged goal that has a passing rehearsal is refused all the same: the rehearsal is not the permission",
      r["state"] == "refused" and "allow_real_runs" in r["reason"], r["reason"])
r = run(gid, "duck-sim", "real")
check("a robot of the sim variant is not asked for the key, whatever the run's target says (it moves no real robot)",
      "allow_real_runs" not in (r["reason"] or ""), r["reason"])
finish("sim_first")
