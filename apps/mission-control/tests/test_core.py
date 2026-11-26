"""Mission Control's core against the fake robot (RFC-0014 steps 1 and 3 for the fake): robots, their
status and lock, goals of every kind, guardrails at three levels, every outcome, the library, the
sites' objects, the event stream, the rates. The gate of RFC-0017 stands in front of the fake. A fake clock
drives it all, except the one test of a hung robot, which needs real threads.
Run: cd apps/mission-control && uv run python tests/test_core.py"""

import math
import tempfile
import threading
import time
from pathlib import Path

from common import Clock, check, finish, finish_run, make_mc, robot_file, run_for

from mission_control.core import MissionControl
from mission_control.errors import ApiError
from mission_control.robots import ConfigError, RobotConfig

POINT = {"kind": "point", "params": {"x": 2.0, "y": 0.0}}


def refusal(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except ApiError as exc:
        return exc
    return None


def boot(*files, state_dir=None):
    clock = Clock()
    mc = make_mc(clock, *files, state_dir=state_dir)
    run_for(mc, clock, 0.2)
    return mc, clock


def fake(mc, rid="fake-1"):
    return mc.robots[rid].adapter.robot


def start(mc, goal, rid="fake-1", **body):
    return mc.run_adhoc({"goal": goal, "robots": [rid], **body})


def kinds(mc, kind):
    return [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == kind]


# --- robots: list, status, online as a measured fact -----------------------------------------------
mc, clock = boot()
listed = mc.list_robots()
check("the robot list: id, label, kind, online, lock, last-seen age", listed[0]["id"] == "fake-1" and listed[0]["online"] is True
      and listed[0]["lock"]["holder"] is None and listed[0]["last_seen_age_s"] is not None and listed[0]["kind"] == "fake", listed)
view = mc.get_robot("fake-1")
check("one robot: capabilities, status (pose, battery, mode), rates, robot-level guardrails",
      view["capabilities"]["navigator"] and view["status"]["pose"]["frame"] == "site" and view["status"]["battery_pct"] == 100.0
      and view["rates"]["state_hz"] == 2.0 and view["guardrails"] == [] and view["goal_run"] is None)
check("an unknown robot is a 404", refusal(mc.get_robot, "nope").status == 404)

# --- the battery rule applies to every robot that reports a percent: one view field, one alarm ----------------------------------------------
check("a full battery: the view says not low, with the rule's two numbers", view["battery"] == {"pct": 100.0, "low": False, "low_pct": 20, "clear_pct": 25}, view.get("battery"))
mc_b, clock_b = boot()
lows = lambda: [e["anomaly"] for e in kinds(mc_b, "anomaly") if e["anomaly"]["anomaly"] == "low_battery"]
fake(mc_b)._moved_m = 170.0                      # 100 - 0.5 * 170 = 15 %
run_for(mc_b, clock_b, 1.0)
v = mc_b.get_robot("fake-1")
check("a fake robot at 15 %: the view says low, and one low_battery alarm (major, source robot) was raised",
      v["battery"] == {"pct": 15.0, "low": True, "low_pct": 20, "clear_pct": 25} and len(lows()) == 1 and lows()[0]["severity"] == "major" and lows()[0]["source"] == "robot", (v["battery"], lows()))
check("the page's alarm view carries it", v["alarms"]["worst"] is not None and v["alarms"]["worst"]["anomaly"]["anomaly"] == "low_battery", v["alarms"])
n = len(lows())
run_for(mc_b, clock_b, 5.0)
check("held low, it is not raised on every poll (a 30 s gap)", len(lows()) == n, (n, len(lows())))
run_for(mc_b, clock_b, 30.0)
check("and again after 30 s while it stays low", len(lows()) == n + 1, (n, len(lows())))
fake(mc_b)._moved_m = 156.0                      # 22 %
run_for(mc_b, clock_b, 1.0)
check("at 22 % it is still low (hysteresis)", mc_b.get_robot("fake-1")["battery"]["low"] is True)
fake(mc_b)._moved_m = 148.0                      # 26 %
run_for(mc_b, clock_b, 1.0)
n = len(lows())
run_for(mc_b, clock_b, 40.0)
check("over 25 % it clears: not low, and nothing more is raised", mc_b.get_robot("fake-1")["battery"]["low"] is False and len(lows()) == n, (mc_b.get_robot("fake-1")["battery"], n, len(lows())))

fake(mc).set_offline(True)
run_for(mc, clock, 3.0)
check("a robot that stops answering is offline once its last answer is older than the bound", mc.get_robot("fake-1")["online"] is False)
check("the change is an event, with the error", kinds(mc, "robot-offline")[0]["error"].startswith("ConnectionError"))
check("offline: a goal is an error, never queued", refusal(start, mc, POINT).status == 503 and mc.list_runs() == [])
check("offline: a drive is not queued either: the lock is still free", mc.get_robot("fake-1")["lock"]["holder"] is None)
fake(mc).set_offline(False)
run_for(mc, clock, 1.0)
check("it is online again after it answers", mc.get_robot("fake-1")["online"] is True and len(kinds(mc, "robot-online")) == 2)

# --- the lock over sessions, the gate underneath ----------------------------------------------------
s1 = mc.robot("fake-1").acquire("script")
check("acquire gives a session and a lease", len(s1["session"]) == 16 and s1["lease_id"] == 1 and s1["expires_in_s"] == 20.0)
check("the robot's lock field mirrors the gate: who and since", mc.get_robot("fake-1")["lock"]["holder"] == "script")
e = refusal(mc.robot("fake-1").acquire, "other")
check("a second client is refused with who holds it", e.status == 409 and e.code == "held" and "script since" in str(e), e and str(e))
mc.robot("fake-1").drive(s1["session"], 0.3, 0.0)
run_for(mc, clock, 0.6)
check("the holder drives", fake(mc).x > 0.03 and mc.get_robot("fake-1")["status"]["pose"]["x"] > 0.03, mc.get_robot("fake-1")["status"]["pose"])
check("a drive with no or a made-up session is refused", refusal(mc.robot("fake-1").drive, None, 0.1, 0).code == "no_lease"
      and refusal(mc.robot("fake-1").drive, "deadbeef", 0.1, 0).code == "no_lease")
e = refusal(mc.robot("fake-1").acquire, "intruder", takeover=True)
check("takeover is refused to a name not on the robot's list", e.status == 403 and e.code == "not_allowed")
check("a peer did not eject the holder", mc.get_robot("fake-1")["lock"]["holder"] == "script")
mc.stop("fake-1", "other-laptop")
e = refusal(mc.robot("fake-1").drive, s1["session"], 0.3, 0.0)
check("STOP from anyone ends the lease and latches: the holder's next drive is refused with why",
      e.code == "lease_ended" and "stopped_by other-laptop" in str(e), e and str(e))
check("the robot is free after STOP", mc.get_robot("fake-1")["lock"]["holder"] is None)
s2 = mc.robot("fake-1").acquire("script")
mc.robot("fake-1").drive(s2["session"], 0.3, 0.0)
s3 = mc.robot("fake-1").acquire("operator-laptop", takeover=True)
e = refusal(mc.robot("fake-1").drive, s2["session"], 0.3, 0.0)
check("the operator's takeover ends the other's control, and the old session is told why",
      e.code == "lease_ended" and "taken_over_by operator-laptop" in str(e), e and str(e))
check("and the robot was stopped before the new holder's first command", fake(mc).vx == 0.0)
mc.robot("fake-1").renew(s3["session"])
mc.robot("fake-1").release(s3["session"])
check("release frees it", mc.get_robot("fake-1")["lock"]["holder"] is None)
lock_events = [e["event"] for e in kinds(mc, "lock")]
check("the gate's log is on the event stream: acquired, refused, stop, taken_over, released",
      all(x in lock_events for x in ("acquired", "refused", "stop", "taken_over", "released")), lock_events)
check("the fake's own state raises no someone_else_drives, and the gate says once what it does not watch",
      "someone_else_drives" not in [e.get("event") for e in kinds(mc, "lock")]
      and [e["fields"] for e in kinds(mc, "lock") if e.get("event") == "not_watched"].count(["autonomous", "move.source", "move.applied"]) <= 1)
s4 = mc.robot("fake-1").acquire("agent-x")
mc.robots["fake-1"].gate.observe_state({"autonomous": True})
al = [e for e in kinds(mc, "anomaly") if e["anomaly"]["anomaly"] == "someone_else_drives"]
check("something else driving (autonomous) is an alarm on the stream, critical, in the robot's view; the lease ended",
      len(al) == 1 and al[0]["anomaly"]["severity"] == "critical" and al[0]["robot"] == "fake-1"
      and mc.get_robot("fake-1")["alarms"]["worst"]["anomaly"]["anomaly"] == "someone_else_drives"
      and mc.get_robot("fake-1")["lock"]["holder"] is None, al)

# --- a point goal ------------------------------------------------------------------------------------
mc, clock = boot(robot_file(guardrails=[{"name": "max_speed", "mps": 0.4}]))
run = start(mc, POINT)
check("a run starts running and holds the robot through the gate, as its navigator",
      run["state"] == "running" and mc.get_robot("fake-1")["lock"]["holder"] == "fake-navigator" and mc.get_robot("fake-1")["goal_run"] == run["id"])
e = refusal(mc.robot("fake-1").acquire, "script")
check("another client cannot drive a robot a goal run holds", e.code == "held" and "fake-navigator" in str(e))
check("a second goal on it is refused as busy", refusal(start, mc, POINT).code == "robot_busy")
run_for(mc, clock, 3.0)
mid = mc.get_run(run["id"])
check("progress while it runs: time used, distance left, pose, the guardrails it runs with",
      mid["progress"]["distance_left_m"] < 2.0 and mid["progress"]["elapsed_s"] > 0 and mid["progress"]["guardrails_ok"] == ["max_speed"], mid["progress"])
done = finish_run(mc, clock, run["id"])
pose = {"x": fake(mc).x, "y": fake(mc).y}
check("it reaches within 0.25 m of the point (truth: the fake's own pose)", done["state"] == "reached"
      and math.hypot(pose["x"] - 2.0, pose["y"]) <= 0.25, (done["state"], pose))
check("the run records the outcome as expected, its end time, and that it saved no goal", done["as_expected"] is True and done["ended_at"]
      and done["goal_id"] is None and mc.list_goals() == [])
check("the run carries the merged guardrails it ran with, readable alone",
      done["guardrails"] == [{"name": "max_speed", "mps": 0.4, "from": ["robot"]}] and done["goal"]["kind"] == "point")
check("it says which conditions the robot could not check: none", done["conditions"]["not_checkable"] == [])
check("the lock is free again, the robot stopped", mc.get_robot("fake-1")["lock"]["holder"] is None and fake(mc).vx == 0.0)
check("the navigator's decisions are with the run, each with a reason", [d["text"] for d in done["decisions"]][:2]
      == ["goal point started", "heading for (2, 0)"] and done["decisions"][-1]["text"].startswith("ended reached"), done["decisions"])
check("the Observatory run key is None: the fake writes no run (RFC-0014 §3.4.3 needs the duck's navigator)", done["run_key"] is None and done["watch"] is None)

# the robot-level speed cap holds in the navigator
mc, clock = boot(robot_file(guardrails=[{"name": "max_speed", "mps": 0.2}]))
run = start(mc, {"kind": "point", "params": {"x": 1.0, "y": 0.0}})
top = 0.0
for _ in range(400):
    run_for(mc, clock, 0.1)
    top = max(top, abs(fake(mc).vx))
    if mc.get_run(run["id"])["state"] != "running":
        break
check("a speed cap clamps the navigator's commands", mc.get_run(run["id"])["state"] == "reached" and 0.1 < top <= 0.2 + 1e-9, top)
mc, clock = boot(robot_file(guardrails=[{"name": "max_speed", "mps": 0.2}]))
run = start(mc, {"kind": "point", "params": {"x": 1.0, "y": 0.0}, "must_not": [{"name": "max_speed", "mps": 0.5}]})
check("a goal cannot loosen the robot's cap: the run says the cap it ran with", mc.get_run(run["id"])["guardrails"][0]["mps"] == 0.2)

# --- outcomes ----------------------------------------------------------------------------------------
mc, clock = boot()
r = start(mc, {"kind": "point", "params": {"x": 9.0, "y": 0.0}})
check("refused: the navigator says there is no path, with the reason", r["state"] == "refused" and "outside the world" in r["reason"], r["reason"])
check("refused is an ended run, the robot is free", r["ended_at"] and mc.get_robot("fake-1")["lock"]["holder"] is None and mc.get_robot("fake-1")["goal_run"] is None)
check("expect 'reach' and refused: not as expected", r["as_expected"] is False)
r = start(mc, {"kind": "point", "params": {"x": 9.0, "y": 0.0}, "expect": "refuse"})
check("expect 'refuse' and refused: as expected (ADR-0015's refuse)", r["state"] == "refused" and r["as_expected"] is True)
r = start(mc, {"kind": "point", "params": {"x": 3.0, "y": 1.5}})
check("a point inside the fridge is refused", "inside a fridge" in r["reason"], r["reason"])
r = start(mc, {"kind": "point", "params": {"x": 3.9, "y": 2.9}, "done_when": {"within_s": 2}})
r = finish_run(mc, clock, r["id"])
check("timeout: the time limit of the goal is spent before it is reached", r["state"] == "timeout" and "time limit of 2 s" in r["reason"], r["reason"])
check("and the robot is stopped and free", fake(mc).vx == 0.0 and mc.get_robot("fake-1")["lock"]["holder"] is None)

# a guardrail broken: contact
run = start(mc, {"kind": "point", "params": {"x": 3.5, "y": -2.0}, "must_not": ["contact"]})
run_for(mc, clock, 2.0)
fake(mc).inject("contact", True)
r = finish_run(mc, clock, run["id"], 10)
check("stopped_by_guardrail: a broken guardrail ends the run and says which", r["state"] == "stopped_by_guardrail"
      and r["broken"]["name"] == "contact" and r["as_expected"] is False, r)
check("it is not 'failed': the decision with its reason is recorded", any("guardrail broken" in d["text"] and d.get("guardrail") == "contact" for d in r["decisions"]))
check("the robot was stopped safely and is free", fake(mc).vx == 0.0 and mc.get_robot("fake-1")["lock"]["holder"] is None)
run = start(mc, {"kind": "point", "params": {"x": 1.0, "y": 0.0}})
r = finish_run(mc, clock, run["id"])
check("the same fault does not stop a run whose guardrails do not list contact", r["state"] == "reached", r["state"])
fake(mc).inject("contact", False)

# stuck: the navigator notices wheels that do not turn
fake(mc).wheels_locked = True
run = start(mc, {"kind": "point", "params": {"x": 2.0, "y": 0.0}, "must_not": ["stall"]})
r = finish_run(mc, clock, run["id"], 20)
check("stuck (written 'stall' in the RFC's example) stops the run", r["state"] == "stopped_by_guardrail" and r["broken"]["name"] == "stuck", r["broken"])
run = start(mc, {"kind": "point", "params": {"x": 2.0, "y": 0.0}, "done_when": {"within_s": 8}})
r = finish_run(mc, clock, run["id"], 20)
check("without 'stuck' in its guardrails the run goes on, says so once, and ends timeout at its time limit",
      r["state"] == "timeout" and sum("stuck" in d["text"] for d in r["decisions"]) == 1, [d["text"] for d in r["decisions"]])
fake(mc).wheels_locked = False

# the time limit as a guardrail (the site's, here)
home = mc.sites.create("Home", "apartment")
mc.assign_site("fake-1", "home")
mc.sites.set_guardrails("home", [{"name": "time_limit", "seconds": 3}])
run = start(mc, {"kind": "point", "params": {"x": 3.5, "y": 2.5}})
r = finish_run(mc, clock, run["id"], 20)
check("a site's time limit is a guardrail: stopped_by_guardrail, not failed", r["state"] == "stopped_by_guardrail" and r["broken"]["name"] == "time_limit"
      and r["guardrails"][0]["from"] == ["site"], r)
mc.sites.set_guardrails("home", [])

# no-go areas: lethal in the planner
fake(mc).x, fake(mc).y = 0.0, 0.0
mc.sites.create_area("home", "Stairwell", None, [[1.0, -1.0], [1.5, -1.0], [1.5, 3.0], [1.0, 3.0]])
mc.sites.set_guardrails("home", [{"name": "no_go_area", "area": "Stairwell"}])
r = start(mc, {"kind": "point", "params": {"x": 3.0, "y": 1.0}})
check("a path through the site's no-go area is refused, the area named", r["state"] == "refused" and "stairwell" in r["reason"], r["reason"])
r = start(mc, {"kind": "point", "params": {"x": 3.0, "y": 1.0}, "must_not": []})
check("a goal with no guardrails of its own is still bound by the site's", r["state"] == "refused")
check("the merged list shows the no-go area from the site", r["guardrails"] == [{"name": "no_go_area", "area": "stairwell", "from": ["site"]}], r["guardrails"])
run = start(mc, {"kind": "point", "params": {"x": -2.0, "y": 1.0}})
r = finish_run(mc, clock, run["id"])
check("a path that stays out of it runs", r["state"] == "reached")
mc.sites.set_guardrails("home", [])

# a start pose (phase 5 item 4b unit B7, contract 1.5): where the operator says the robot stands on the map when the run starts
SP = {"x": -2.0, "y": 0.5, "yaw": 0.0}
run = start(mc, {"kind": "point", "params": {"x": -3.0, "y": 0.5}}, start_pose=SP)
check("a run with a start pose keeps it with the run (its conditions)", run["state"] == "running" and run["conditions"]["start_pose"] == SP, run["conditions"])
check("the robot stands where it was placed (the fake's world is the site)", fake(mc).pose() == (-2.0, 0.5, 0.0), fake(mc).pose())
r = finish_run(mc, clock, run["id"])
check("the run says it was placed, as a decision, and goes on to reach its point from there",
      r["state"] == "reached" and any(d["rule"] == "placed" and "placed by the operator at (-2.00, 0.50)" in d["text"] for d in r["decisions"]), (r["state"], r["decisions"][:2]))
run = start(mc, {"kind": "point", "params": {"x": -3.0, "y": 0.5}}, start_pose={"x": -2.0, "y": 0.5, "yaw": 2 * math.pi + 0.5})
check("a yaw is taken modulo a turn", abs(run["conditions"]["start_pose"]["yaw"] - 0.5) < 1e-9, run["conditions"])
finish_run(mc, clock, run["id"])
run = start(mc, {"kind": "point", "params": {"x": -3.0, "y": 0.5}})
check("a run with none has none among its conditions", "start_pose" not in run["conditions"], run["conditions"])
finish_run(mc, clock, run["id"])
check("the dock the first run set says it came from the robot's own pose (no start pose was sent)",
      mc.sites.get("home")["dock_pose"]["set_from"] == "robot_pose", mc.sites.get("home")["dock_pose"])
mc.sites.create("Annex", "garage")
mc.assign_site("fake-1", "annex")
run = start(mc, {"kind": "point", "params": {"x": -3.0, "y": 0.5}}, start_pose=SP)
finish_run(mc, clock, run["id"])
dock = mc.sites.get("annex")["dock_pose"]
check("the first placed start a site sees is its dock, and the dock says so (set_from placed_start, the pose and the robot)",
      dock["set_from"] == "placed_start" and (dock["x"], dock["y"], dock["yaw"]) == (SP["x"], SP["y"], SP["yaw"]) and dock["robot"] == "fake-1", dock)
run = start(mc, {"kind": "point", "params": {"x": -3.0, "y": 0.5}}, start_pose={"x": -1.0, "y": 0.0, "yaw": 0.0})
finish_run(mc, clock, run["id"])
check("a later placed start does not move the dock or its record", mc.sites.get("annex")["dock_pose"] == dock, mc.sites.get("annex")["dock_pose"])
mc.assign_site("fake-1", "home")
mc.sites.set_guardrails("home", [{"name": "no_go_area", "area": "Stairwell"}])
for label, pose, why in (("inside the site's no-go area", {"x": 1.2, "y": 1.0, "yaw": 0.0}, "no-go area stairwell"),
                         ("outside the world", {"x": 9.0, "y": 0.0, "yaw": 0.0}, "outside the world"),
                         ("inside the fridge", {"x": 3.0, "y": 1.5, "yaw": 0.0}, "inside a fridge")):
    r = start(mc, POINT, start_pose=pose)
    check(f"must fail: a start pose {label} is refused, saying why, and the robot is free", r["state"] == "refused" and why in r["reason"]
          and mc.get_robot("fake-1")["lock"]["holder"] is None, r["reason"])
mc.sites.set_guardrails("home", [])
for label, pose in (("without a yaw", {"x": 1.0, "y": 2.0}), ("with a string", {"x": "1", "y": 2.0, "yaw": 0.0}),
                    ("with a NaN", {"x": float("nan"), "y": 2.0, "yaw": 0.0}), ("in another frame", {"x": 1.0, "y": 2.0, "yaw": 0.0, "frame": "map"}),
                    ("with an extra key", {"x": 1.0, "y": 2.0, "yaw": 0.0, "z": 1}), ("that is a list", [1.0, 2.0, 0.0])):
    exc = refusal(start, mc, POINT, start_pose=pose)
    check(f"must fail: a start pose {label} is a 422 bad_start_pose and creates no run", exc is not None and exc.code == "bad_start_pose"
          and exc.status == 422, exc and exc.code)
exc = refusal(mc.run_adhoc, {"goal": POINT, "team": "all", "start_pose": SP})
check("a start pose is one robot's: with a team (or several robots) it is a 422 bad_start_pose", exc is not None and exc.code == "bad_start_pose", exc and exc.code)

# cancelled: by the operator, by STOP; interrupted: by a takeover, by the robot going silent
run = start(mc, {"kind": "point", "params": {"x": 3.5, "y": -2.0}})
run_for(mc, clock, 1.0)
r = mc.cancel_run(run["id"])
check("cancel: the run ends cancelled, the robot is stopped and free", r["state"] == "cancelled" and fake(mc).vx == 0.0
      and mc.get_robot("fake-1")["lock"]["holder"] is None, r["state"])
check("cancelling an ended run is refused", refusal(mc.cancel_run, run["id"]).code == "run_ended")
run = start(mc, {"kind": "point", "params": {"x": 3.5, "y": -2.0}})
run_for(mc, clock, 1.0)
res = mc.stop("fake-1", "page")
r = mc.get_run(run["id"])
check("STOP: the run is cancelled at once (the latch), with who stopped it", r["state"] == "cancelled" and "stopped by page" in r["reason"], r["reason"])
check("the STOP is confirmed: the robot answered", res == {"robot": "fake-1", "confirmed": True, "online": True})
# The page test failed 1 run in 4 (2026-11-20): STOP ALL ended a run "interrupted". The gate's lease-lost callback and Mission
# Control's ticker race; when the ticker's step() reaches the gate first, it is refused with lease_ended. Held back here, so
# step() always meets the refusal first: the STOP must still read as a STOP.
run = start(mc, {"kind": "point", "params": {"x": 3.5, "y": -2.0}})
run_for(mc, clock, 1.0)
nav = mc.robot("fake-1").navigator
late, nav._lease_lost = nav._lease_lost, lambda r, params: None
try:
    mc.stop("fake-1", "page")
finally:
    nav._lease_lost = late
r = mc.get_run(run["id"])
check("STOP with the lease-lost callback late: still cancelled, with who stopped it (not interrupted)",
      r["state"] == "cancelled" and "stopped by page" in (r["reason"] or ""), (r["state"], r["reason"]))
run = start(mc, {"kind": "point", "params": {"x": 3.5, "y": -2.0}})
run_for(mc, clock, 1.0)
tk = mc.robot("fake-1").acquire("operator-laptop", takeover=True)
run_for(mc, clock, 0.3)
r = mc.get_run(run["id"])
check("takeover: the run is interrupted, not cancelled", r["state"] == "interrupted" and "taken over by operator-laptop" in r["reason"], r["reason"])
check("the new holder holds the robot", mc.get_robot("fake-1")["lock"]["holder"] == "operator-laptop")
mc.robot("fake-1").release(tk["session"])
run = start(mc, {"kind": "point", "params": {"x": 3.5, "y": -2.0}})
run_for(mc, clock, 1.0)
fake(mc).set_offline(True)
r = finish_run(mc, clock, run["id"], 5)
check("a robot that stops answering interrupts the run", r["state"] == "interrupted" and "stopped answering" in r["reason"], r["reason"])
fake(mc).set_offline(False)
run_for(mc, clock, 1.0)
check("STOP to an offline robot is accepted but cannot be confirmed (RFC-0014 §3.8)",
      (fake(mc).set_offline(True), mc.stop("fake-1", "page"))[1] == {"robot": "fake-1", "confirmed": False, "online": mc.get_robot("fake-1")["online"]})
fake(mc).set_offline(False)
run_for(mc, clock, 1.0)

# STOP's `confirmed` is the gate's reply, whether the robot answered robot.stop (RFC-0014 §3.8): a robot that takes the zero move
# but not the stop is accepted and not confirmed, on the reply and on the bus
rt = mc.robots["fake-1"]
real_call = rt.link._call


def stop_refused(method, params=None):
    if method == "robot.stop":
        raise TimeoutError("robot.stop: no answer")
    return real_call(method, params)


rt.link._call = stop_refused
res = mc.stop("fake-1", "page")
rt.link._call = real_call
stop_events = [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "stop"]
check("STOP when only robot.stop fails: confirmed False (the robot did not answer it), not inferred from the call returning",
      res["confirmed"] is False and stop_events and stop_events[-1]["confirmed"] is False, (res, stop_events[-1:]))
res = mc.stop("fake-1", "page")
stop_events = [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "stop"]
check("STOP with a working robot: confirmed True, on the reply and on the bus",
      res["confirmed"] is True and stop_events[-1]["confirmed"] is True, (res, stop_events[-1:]))

# a gate that cannot speak our protocol (ProtocolError from its hello) is a STOP not confirmed, never a 500
from robotgate import ProtocolError  # noqa: E402
real_open = rt.gate.open


def bad_protocol(*a, **k):
    raise ProtocolError("the gate speaks protocol 99")


rt.gate.open = bad_protocol
try:
    res = mc.stop("fake-1", "page")
except Exception as exc:                   # noqa: BLE001
    res = exc
rt.gate.open = real_open
check("STOP when the gate's protocol is not ours: accepted, confirmed False, no exception",
      isinstance(res, dict) and res["confirmed"] is False, res)

# the NXT's gate: nxt-web answers 409 to /api/stop when the brick does not (not connected, a link error); STOP is still taken
import http.server  # noqa: E402
from mission_control.nxt import NxtGate  # noqa: E402
from mission_control.robots import Link  # noqa: E402


class StopHandler(http.server.BaseHTTPRequestHandler):
    status, body = 200, b'{"ok": true}'

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(StopHandler.status)
        self.send_header("Content-Length", str(len(StopHandler.body)))
        self.end_headers()
        self.wfile.write(StopHandler.body)

    def log_message(self, *a):
        pass


nxt_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StopHandler)
threading.Thread(target=nxt_srv.serve_forever, daemon=True).start()
ng = NxtGate(f"http://127.0.0.1:{nxt_srv.server_address[1]}", Link(lambda m, p: {}, clock), None)
ncid = ng.open("page")
reply = ng.handle(ncid, "robot.stop", {})
check("NXT: nxt-web answered /api/stop: confirmed", reply.get("ok") is True and reply.get("confirmed") is True, reply)
StopHandler.status, StopHandler.body = 409, b'{"ok": false, "error": "RuntimeError: not connected"}'
try:
    reply = ng.handle(ncid, "robot.stop", {})
except Exception as exc:                   # noqa: BLE001
    reply = exc
check("NXT: nxt-web took the STOP but the brick did not answer (409): accepted, not confirmed, the reason said, no exception",
      isinstance(reply, dict) and reply.get("ok") is True and reply.get("confirmed") is False and "not connected" in str(reply.get("errors")), reply)
nxt_srv.shutdown()
nxt_srv.server_close()

# --- sites, objects and the object goals -------------------------------------------------------------
mc, clock = boot()
mc.sites.create("Home", "apartment")
check("an object goal needs a site: refused when the robot has none and the run names none",
      "site" in start(mc, {"kind": "go_to_object", "params": {"kind": "fridge"}})["reason"])
mc.assign_site("fake-1", "home")
check("the robot is at one site, shown on it", mc.get_robot("fake-1")["site"] == "home")

run = start(mc, {"kind": "go_to_object", "params": {"kind": "fridge"}, "must_not": ["contact"]})
r = finish_run(mc, clock, run["id"], 200)
fr = fake(mc)
fridge = fr.world["objects"][0]
gap = math.hypot(fridge["x"] - fr.x, fridge["y"] - fr.y) - max(fridge["hx"], fridge["hy"])
face = abs(math.degrees((math.atan2(fridge["y"] - fr.y, fridge["x"] - fr.x) - fr.yaw + math.pi) % (2 * math.pi) - math.pi))
check("go_to_object with an empty map: it explored, found the fridge and stood within 0.35 m of it, facing it (truth)",
      r["state"] == "reached" and gap <= 0.35 and face <= 45.0, (r["state"], r["reason"], gap, face))
texts = [d["text"] for d in r["decisions"]]
check("the decisions say it explored first, then found, then went", any("exploring to find one" in t for t in texts)
      and any("confirmed the fridge" in t for t in texts) and any(t.startswith("going to the fridge") for t in texts), texts)
site_objs = mc.sites.objects("home")
check("the run's result: the object found (the site's stable id, kind, position) and the stand pose reached",
      r["result"]["object"]["kind"] == "fridge" and r["result"]["object"]["id"] == site_objs[[o["kind"] for o in site_objs].index("fridge")]["id"]
      and r["result"]["object"]["id"].startswith("obj-") and r["result"]["stand"]["frame"] == "site", r["result"])
check("the objects the run saw are in the site's map with stable ids, the fridge confirmed and unique",
      len(site_objs) >= 1 and all(o["id"].startswith("obj-") for o in site_objs)
      and next(o for o in site_objs if o["kind"] == "fridge")["confirmed"] and next(o for o in site_objs if o["kind"] == "fridge")["unique"])
check("the run created no area: the robot never does", mc.sites.areas("home") == [])
check("objects arrive as events", kinds(mc, "objects") and kinds(mc, "objects")[0]["site"] == "home")

fridge_id = r["result"]["object"]["id"]
run = start(mc, {"kind": "go_to_object", "params": {"kind": "fridge"}})
r2 = finish_run(mc, clock, run["id"], 200)
texts2 = [d["text"] for d in r2["decisions"]]
check("the next run is seeded with the site's map: no exploring, the same object id",
      r2["state"] == "reached" and not any("exploring" in t for t in texts2) and r2["result"]["object"]["id"] == fridge_id, (r2["state"], texts2))
mc.sites.label("home", fridge_id, "the cold box")
run = start(mc, {"kind": "go_to_object", "params": {"label": "THE cold box"}})
r3 = finish_run(mc, clock, run["id"], 200)
check("a label is the operator's name for it and wins: go_to_object by label", r3["state"] == "reached" and r3["result"]["object"]["label"] == "the cold box"
      and r3["result"]["object"]["id"] == fridge_id, r3["result"])
run = start(mc, {"kind": "go_to_object", "params": {"id": fridge_id}})
check("go_to_object by exact id", finish_run(mc, clock, run["id"], 200)["state"] == "reached")
run = start(mc, {"kind": "go_to_object", "params": {"label": "the unicorn"}, "budget": {"minutes": 1}})
r = finish_run(mc, clock, run["id"], 200)
check("not_found: nothing of that name in the map, the budget spent exploring: neither refused nor failed",
      r["state"] == "not_found" and "the unicorn" in r["reason"], (r["state"], r["reason"]))
run = start(mc, {"kind": "go_to_object", "params": {"kind": "bed"}, "budget": {"minutes": 5}})
r = finish_run(mc, clock, run["id"], 400)
check("not_found also when there is nothing left to explore", r["state"] == "not_found", (r["state"], r["reason"]))

# areas drawn by the operator, then the goals on them
study = mc.sites.create_area("home", "Study", "study", [[-3.2, 0.8], [-1.2, 0.8], [-1.2, 2.6], [-3.2, 2.6]])
kitchen = mc.sites.create_area("home", "Kitchen", "kitchen", [[2.0, 0.5], [3.9, 0.5], [3.9, 2.9], [2.0, 2.9]])
fake(mc).x, fake(mc).y = 0.0, 0.0
run = start(mc, {"kind": "go_to_area", "params": {"area": "study"}})
run_for(mc, clock, 1.0)
check("progress while it runs: the area it believes it is in (none yet, it is still at the dock)", mc.get_run(run["id"])["progress"]["area"] is None)
r = finish_run(mc, clock, run["id"], 200)
check("go_to_area: done when the robot is inside the outline (truth)", r["state"] == "reached"
      and mc.sites.area_at("home", fake(mc).x, fake(mc).y)["id"] == "study", (r["state"], fake(mc).x, fake(mc).y))
check("the final progress is the last tick's: it has the area and the pose", {"area", "pose", "elapsed_s"} <= set(r["progress"]), r["progress"])
r = start(mc, {"kind": "go_to_area", "params": {"area": "ballroom"}})
check("an area that is not in the site is refused with the reason", r["state"] == "refused" and "no area 'ballroom'" in r["reason"], r["reason"])
check("the fridge is now in the kitchen, by geometry", mc.sites.object("home", fridge_id)["area"] == "kitchen")
run = start(mc, {"kind": "go_to_object", "params": {"kind": "fridge", "area": "study"}, "budget": {"minutes": 1}})
r = finish_run(mc, clock, run["id"], 200)
check("area narrows the choice: no fridge in the study is not_found", r["state"] == "not_found", (r["state"], r["reason"]))

run = start(mc, {"kind": "explore", "params": {"area": "kitchen"}})
r = finish_run(mc, clock, run["id"], 200)
check("explore {area}: only the waypoints inside it; no frontier left is done, not a failure",
      r["state"] == "done" and r["result"]["ended_by"] == "no_frontier_left" and r["progress"]["waypoints_visited"] == 1, (r["state"], r["result"], r["progress"]))
run = start(mc, {"kind": "explore", "params": {"site": True}, "budget": {"minutes": 0.2}})
r = finish_run(mc, clock, run["id"], 200)
check("explore {site} that ends by its budget is done too, the coverage is the result",
      r["state"] == "done" and r["result"]["ended_by"] == "budget" and r["result"]["cells_explored"] > 0 and "objects_found" in r["result"], r["result"])
check("done counts as met for a reach goal", r["as_expected"] is True)

mc2, clock2 = boot()
mc2.sites.create("Home", "apartment")
mc2.assign_site("fake-1", "home")
run = start(mc2, {"kind": "inventory", "params": {"areas": []}})
r = finish_run(mc2, clock2, run["id"], 400)
inv = r["result"]
check("inventory: done; the objects of the whole site, no areas drawn yet, so 'none defined'",
      r["state"] == "done" and inv["areas"] == [] and len(inv["none_defined"]) == 4 and inv["ended_by"] == "no_frontier_left", (r["state"], inv))
site_ids = {o["id"] for o in mc2.sites.objects("home")}
check("inventory's objects carry the site's stable ids", {o["id"] for o in inv["none_defined"]} == site_ids and all(i.startswith("obj-") for i in site_ids))
check("every object of the fake site was found and confirmed", {o["kind"] for o in mc2.sites.inventory("home")["none_defined"]} == {"fridge", "sofa", "desk", "plant"})
mc2.sites.create_area("home", "Kitchen", "kitchen", [[2.0, 0.5], [3.9, 0.5], [3.9, 2.9], [2.0, 2.9]])
mc2.sites.create_area("home", "Lounge", "lounge", [[-4, -3], [0.5, -3], [0.5, 0], [-4, 0]])
run = start(mc2, {"kind": "inventory", "params": {"areas": ["kitchen", "lounge"]}})
r = finish_run(mc2, clock2, run["id"], 400)
by_area = {a["area"]: [o["kind"] for o in a["objects"]] for a in r["result"]["areas"]}
check("inventory by area: the objects in each of the operator's areas", by_area == {"kitchen": ["fridge"], "lounge": ["sofa"]}, by_area)
check("a second run found the same objects: still four, ids stable across runs", len(mc2.sites.objects("home")) == 4
      and {o["id"] for o in mc2.sites.objects("home")} == site_ids)

# --- what a robot can take, and what it must refuse (§3.3.2, §3.4.8) --------------------------------
blind = robot_file("blind", capabilities={**robot_file()["capabilities"], "recognisers": [],
                                         "localisation": {"frame": "run", "how": "dock"}, "guardrails": ["contact"]})
mc3, clock3 = boot(blind)
mc3.sites.create("Home", "apartment")
mc3.assign_site("blind", "home")
r = start(mc3, {"kind": "go_to_object", "params": {"kind": "fridge"}}, rid="blind")
check("no recogniser and not localised: refused with the RFC's reason", r["reason"] == "no recogniser and not localised in the site frame", r["reason"])
r = start(mc3, {"kind": "point", "params": {"x": 1, "y": 0}, "must_not": [{"name": "max_speed", "mps": 0.3}]}, rid="blind")
check("a guardrail the robot cannot enforce is refused, naming it", r["state"] == "refused" and "cannot enforce the guardrail max_speed" in r["reason"], r["reason"])
try:
    RobotConfig(robot_file(guardrails=[{"name": "max_speed", "mps": 0.3}], capabilities={"guardrails": ["contact"]}))
    check("a robot file whose own guardrail it cannot enforce is a config error", False)
except ConfigError as exc:
    check("a robot file whose own guardrail it cannot enforce is a config error", "not in capabilities.guardrails" in str(exc), str(exc))
check("several robots need robots that exist, and a team that exists (the groups themselves are in test_teams.py)",
      refusal(mc3.run_adhoc, {"goal": POINT, "robots": ["blind", "x"]}).status == 404
      and refusal(mc3.run_adhoc, {"goal": POINT, "team": "all"}).status == 404)
check("a bad goal is a 422 and creates no run", refusal(mc3.run_adhoc, {"goal": {"kind": "fetch"}, "robots": ["blind"]}).code == "unknown_kind"
      and mc3.list_runs(robot="blind") != [] and all(r["goal"]["kind"] != "fetch" for r in mc3.list_runs()))
check("the fake is not a real robot", refusal(start, mc3, POINT, rid="blind", target="real").status == 422)

# --- the goal library --------------------------------------------------------------------------------
mc, clock = boot()
g = mc.create_goal({"name": "to the door", "folder": "tests/course/", "kind": "point", "params": {"x": 1, "y": 1}})
mc.create_goal({"name": "far corner", "folder": "tests", "kind": "point", "params": {"x": 3, "y": 2}})
mc.create_goal({"name": "top", "kind": "point", "params": {"x": 0, "y": 1}})
check("goals live in folders; the folder is normalised", g["folder"] == "tests/course" and g["id"] == 1)
check("GET goals lists all", len(mc.list_goals()) == 3)
check("a folder lists its goals and its subfolders'", [x["name"] for x in mc.list_goals("tests")] == ["far corner", "to the door"]
      and [x["name"] for x in mc.list_goals("tests/course")] == ["to the door"])
check("a folder that does not exist lists nothing", mc.list_goals("nothing") == [])
check("a name is unique in its folder", refusal(mc.create_goal, {"name": "TO THE DOOR", "folder": "tests/course", "kind": "point", "params": {"x": 0, "y": 0}}).code == "name_taken")
check("a bad goal is refused and not stored", refusal(mc.create_goal, {"name": "x", "kind": "fetch"}).code == "unknown_kind" and len(mc.list_goals()) == 3)
run = mc.run_goal(g["id"], {"robots": ["fake-1"]})
check("a library goal's run keeps the link to it", run["goal_id"] == g["id"] and run["goal"]["name"] == "to the door")
check("a goal that is running cannot be changed or retired", refusal(mc.update_goal, g["id"], g).code == "goal_running"
      and refusal(mc.retire_goal, g["id"]).code == "goal_running")
r = finish_run(mc, clock, run["id"])
check("it ran", r["state"] == "reached")
changed = mc.update_goal(g["id"], {**g, "params": {"x": 2, "y": 1}})
check("a goal changes", changed["params"]["x"] == 2.0 and changed["id"] == g["id"])
check("and the old run still holds the goal as it was run", mc.get_run(run["id"])["goal"]["params"]["x"] == 1.0)
adhoc = start(mc, {"kind": "point", "params": {"x": -1.0, "y": 0.0}})
finish_run(mc, clock, adhoc["id"])
saved = mc.save_run(adhoc["id"], {"name": "behind", "folder": "tests/course"})
check("save the goal of an ad-hoc run into the library: the run is linked to it", saved["name"] == "behind" and saved["folder"] == "tests/course"
      and mc.get_run(adhoc["id"])["goal_id"] == saved["id"] and len(mc.list_goals()) == 4)
check("runs list by robot, goal and state", len(mc.list_runs(goal_id=g["id"])) == 1 and len(mc.list_runs(state="reached")) == 2
      and mc.list_runs()[0]["id"] == adhoc["id"])
mc.retire_goal(g["id"])
check("a retired goal is gone from the library and its runs stay", refusal(mc.get_goal, g["id"]).status == 404 and mc.get_run(run["id"])["state"] == "reached")
check("an unknown run is a 404", refusal(mc.get_run, 999).status == 404)

# --- the event stream: sequence numbers, replay, rates -----------------------------------------------
seq = mc.bus.seq
events, gap = mc.bus.since(0, 100000)
check("every event has a growing sequence number, a time and a kind", [e["seq"] for e in events] == sorted(e["seq"] for e in events)
      and len({e["seq"] for e in events}) == len(events) and all("t" in e and "kind" in e for e in events))
check("a client that dropped asks for what it missed", [e["seq"] for e in mc.bus.since(seq - 3)[0]] == [seq - 2, seq - 1, seq])
run_for(mc, clock, 1.0)
check("kinds: state, goal-run, decision, lock, stop-free so far", {"state", "goal-run", "decision", "lock"} <= {e["kind"] for e in mc.bus.since(0, 100000)[0]})
check("the navigator's decisions are relayed per goal run", any(e["kind"] == "decision" and e["goal_run"] == run["id"] for e in events))

fast = robot_file("fast", rates={"state_hz": 5.0, "map_hz": 1.0, "max_state_hz": 10.0})
slow = robot_file("slow", rates={"state_hz": 0.5, "map_hz": 1.0, "max_state_hz": 10.0})
mc4, clock4 = boot(fast, slow)
n0 = {rid: len([e for e in mc4.bus.since(0, 100000)[0] if e["kind"] == "state" and e["robot"] == rid]) for rid in ("fast", "slow")}
run_for(mc4, clock4, 10.0)
n = {rid: len([e for e in mc4.bus.since(0, 100000)[0] if e["kind"] == "state" and e["robot"] == rid]) - n0[rid] for rid in ("fast", "slow")}
check("the state rate is a setting per robot: 5 Hz and 0.5 Hz over 10 s", 48 <= n["fast"] <= 51 and 4 <= n["slow"] <= 6, n)
for bad in ({"state_hz": 20.0, "max_state_hz": 10.0}, {"state_hz": 0}, {"state_hz": "fast"}):
    try:
        RobotConfig(robot_file(rates=bad))
        check(f"a rate above the robot's own limit or not a number is refused: {bad}", False)
    except ConfigError:
        check(f"a rate above the robot's own limit or not a number is refused: {bad}", True)
check("the map is an event, once, when it changes (and only that often)", 1 <= len(kinds(mc4, "map")) <= 12)

# --- a robot that does not answer holds up nobody ---------------------------------------------------
real = time.monotonic
hung = robot_file("hung", adapter={"type": "fake", "call_timeout_s": 0.2}, online_after_s=0.6, rates={"state_hz": 10.0, "map_hz": 1.0, "max_state_hz": 10.0})
well = robot_file("well", rates={"state_hz": 10.0, "map_hz": 1.0, "max_state_hz": 10.0})
mc5 = MissionControl([RobotConfig(hung), RobotConfig(well)], clock=real, wall=time.time)
mc5.start()
time.sleep(0.5)
check("both online to begin with", all(r["online"] for r in mc5.list_robots()), mc5.list_robots())
release = threading.Event()
mc5.robots["hung"].adapter.robot.hang = release
t0 = real()
count0 = len([e for e in mc5.bus.since(0, 100000)[0] if e["kind"] == "state" and e["robot"] == "well"])
time.sleep(1.5)
count1 = len([e for e in mc5.bus.since(0, 100000)[0] if e["kind"] == "state" and e["robot"] == "well"])
check("the hung robot does not slow the other: it kept its 10 Hz", count1 - count0 >= 10, count1 - count0)
check("the hung robot is offline, by the age of its last answer, while its call is still stuck", mc5.get_robot("hung")["online"] is False)
t1 = real()
listed = mc5.list_robots()
check("listing robots does not wait for the hung one", real() - t1 < 1.0 and [r["online"] for r in listed] == [False, True], real() - t1)
t1 = real()
res = mc5.stop_all("page")
byid = {r["robot"]: r for r in res["robots"]}
check("STOP-all reaches the robot that answers and reports the one that does not, within its bound",
      byid["well"]["confirmed"] is True and byid["hung"]["confirmed"] is False and res["all_confirmed"] is False and real() - t1 < 4.0, (res, real() - t1))
release.set()
mc5.close()
check("the threads end on close", all(not t.is_alive() for t in mc5._threads))

# --- persistence: the library, the runs, the sites and the gate's log survive a restart -----------------
with tempfile.TemporaryDirectory() as tmp:
    mc, clock = boot(state_dir=tmp)
    mc.sites.create("Home", "apartment")
    mc.assign_site("fake-1", "home")
    g = mc.create_goal({"name": "fridge", "folder": "kitchen", "kind": "go_to_object", "params": {"kind": "fridge"}})
    run = mc.run_goal(g["id"], {"robots": ["fake-1"]})
    finish_run(mc, clock, run["id"], 200)
    mc.close()
    mc2 = make_mc(Clock(), state_dir=tmp)
    check("goals, runs with their decisions, sites and objects are still there after a restart",
          mc2.get_goal(g["id"])["name"] == "fridge" and mc2.get_run(run["id"])["state"] == "reached" and mc2.get_run(run["id"])["decisions"]
          and mc2.sites.get("home")["counts"]["objects"] >= 1)
    log = (Path(tmp) / "gate-fake-1.jsonl").read_text().splitlines()
    check("the gate's log is a file beside the state (RFC-0017 §3.6): lease acquired by the navigator", any('"acquired"' in l and "fake-navigator" in l for l in log), log[:3])
    mc2.close()

finish("test_core")
