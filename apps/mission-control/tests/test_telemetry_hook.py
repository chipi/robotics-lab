"""Mission Control's telemetry hook (mission_control.telemetry, docs/wip/TELEMETRY-RETENTION-DESIGN.md) against a local OTLP receiver: the
bus's events in, the right metrics, spans and logs out, each with robot_id, robot_kind and host_kind from the adapter-type table; a
failed goal's span has the error status; a dead receiver or a sink that raises does not slow or break emit; telemetry is off with
no installation file or no telemetry block; core wires the hook in. Only 127.0.0.1.
Run: cd apps/mission-control && uv run python tests/test_telemetry_hook.py"""

import io
import json
import os
import tempfile
import time
from contextlib import redirect_stderr
from pathlib import Path

for k in [k for k in os.environ if k.startswith(("OTEL_", "ROBOTICS_LAB"))]:
    del os.environ[k]

from common import Clock, check, finish, finish_run, installation_file, robot_file
from otlp_stub import OtlpStub

from mission_control import telemetry as H
from mission_control.core import MissionControl
from mission_control.events import EventBus
from mission_control.robots import RobotConfig
from runfile import telemetry as T
from runfile.installation import Telemetry

ADAPTERS = {"duck-a": "duck-sim", "real-1": "duck-real", "nxt-1": "nxt-web", "fk": "fake", "odd": "something-new"}


def cfg_for(stub, **off):
    return Telemetry("check", None if off.get("traces") is False else stub.url("traces"), None if off.get("metrics") is False else stub.url("metrics"),
                     None if off.get("logs") is False else stub.url("logs"), 5)


def labels(rid, kind, host):
    return {"robot_id": rid, "robot_kind": kind, "host_kind": host}


# 1. the table
check("the adapter table: duck-sim, duck-real, nxt-web, fake", H.robot_labels("duck-sim") == ("legged", "pollen-duck-sim")
      and H.robot_labels("duck-real") == ("legged", "microduck") and H.robot_labels("nxt-web") == ("tracked", "nxt-brick")
      and H.robot_labels("fake") == ("fake", "fake"))
check("an adapter not in the table, and none: unknown", H.robot_labels("something-new") == ("unknown", "unknown")
      and H.robot_labels(None) == ("unknown", "unknown"))

# 2. events in, signals out
stub = OtlpStub("ok")
sink = T.start(cfg_for(stub), "mission-control", version="0.1.0")
clock = Clock(5000.0)
bus = EventBus(clock)
hook = H.make(sink, ADAPTERS.get)
bus.listen(hook.listener)
bus.emit("robot-online", robot="duck-a", error=None)
bus.emit("robot-offline", robot="nxt-1", error="no answer")
bus.emit("lock", robot="duck-a", event="acquired", client="fake-navigator", lease_id=1)
bus.emit("lock", robot="nxt-1", event="acquired", client="page", lease_id=1)
bus.emit("lock", robot="nxt-1", event="lease_ended", client="page", why="stopped")
bus.emit("goal-run", robot="duck-a", goal_run=1, state="queued", client="page")
bus.emit("goal-run", robot="duck-a", goal_run=1, state="running", run_key="duck/room/r1")
clock.advance(2.0)
bus.emit("goal-run", robot="duck-a", goal_run=1, state="running", progress={"x": 1})
bus.emit("anomaly", robot="duck-a", goal_run=1, watch=None,
         anomaly={"anomaly": "rtf_low", "severity": "minor", "source": "navigator", "summary": "slow sim"})
clock.advance(10.5)
bus.emit("goal-run", robot="duck-a", goal_run=1, state="reached", reason=None, result={}, broken=None, as_expected=True)
bus.emit("goal-run", robot="nxt-1", goal_run=2, state="running", run_key="nxt/room/r2")
clock.advance(4.0)
bus.emit("goal-run", robot="nxt-1", goal_run=2, state="failed", reason="stuck at the door", result=None, broken=None, as_expected=False)
bus.emit("goal-run", robot="fk", goal_run=3, state="refused", reason="robot busy", client="page")
bus.emit("goal-run", robot="odd", goal_run=4, state="running", run_key=None)
bus.emit("goal-run", robot="odd", goal_run=4, state="timeout", reason="time up", result=None, broken=None, as_expected=False)
bus.emit("goal-run", robot="duck-a", goal_run=5, state="running", run_key=None)
bus.emit("goal-run", robot="duck-a", goal_run=5, state="cancelled", reason="operator", result=None, broken=None, as_expected=False)
bus.emit("goal-run", robot="nxt-1", goal_run=6, state="running", run_key=None)
bus.emit("goal-run", robot="nxt-1", goal_run=6, state="done", reason=None, result={}, broken=[{"must_not": "contact"}], as_expected=True)
bus.emit("anomaly", robot="real-1", goal_run=None, watch=None,
         anomaly={"anomaly": "someone_else_drives", "severity": "critical", "source": "gate", "summary": "drives"})
bus.emit("stop", robot="duck-a", client="page", confirmed=True)
bus.emit("stop", robot="nxt-1", client="page", confirmed=False)
bus.emit("stop-all", client="page", robots=[{"robot": "duck-a", "confirmed": True}, {"robot": "nxt-1", "confirmed": False}])
bus.emit("error", robot="nxt-1", message="RuntimeError: boom")
bus.emit("goal-run", goal_run=9, state="running", share="any", robots=["duck-a"], client="page")   # a group: no robot, no signal
bus.emit("state", robot="duck-a", battery_pct=80)
bus.emit("decision", robot="duck-a", goal_run=1, text="turning")
t0 = time.monotonic()
sink.close()
check("close flushed within its bound", time.monotonic() - t0 < 5, time.monotonic() - t0)
metrics, spans, logs = stub.snapshot()


def point(name, **attrs):
    return [m for m in metrics if m["name"] == name and all(m["attrs"].get(k) == v for k, v in attrs.items())]


def value(name, **attrs):
    pts = point(name, **attrs)
    return pts[0]["value"] if len(pts) == 1 else None


check("every metric carries robot_id, robot_kind and host_kind, and only its own extra labels",
      all(set(m["attrs"]) == set(T.ROBOT_LABELS) | set(T.INSTRUMENTS[m["name"]][2]) for m in metrics), sorted({m["name"] for m in metrics}))
check("the resource: the service and the environment", metrics[0]["resource"].get("service.name") == "robotics-lab-mission-control"
      and metrics[0]["resource"].get("deployment.environment.name") == "check")
check("robot-online: the gauge is 1 for the duck (legged, pollen-duck-sim), 0 for the NXT (tracked, nxt-brick)",
      value("robotics_lab.robot.online", **labels("duck-a", "legged", "pollen-duck-sim")) == 1
      and value("robotics_lab.robot.online", **labels("nxt-1", "tracked", "nxt-brick")) == 0, point("robotics_lab.robot.online"))
check("lock: acquired is 1, lease_ended is 0", value("robotics_lab.robot.lock_held", robot_id="duck-a") == 1
      and value("robotics_lab.robot.lock_held", robot_id="nxt-1") == 0, point("robotics_lab.robot.lock_held"))
check("goals counted by their end state, a refusal included",
      value("robotics_lab.goals", robot_id="duck-a", state="reached") == 1 and value("robotics_lab.goals", robot_id="nxt-1", state="failed") == 1
      and value("robotics_lab.goals", robot_id="fk", state="refused") == 1 and value("robotics_lab.goals", robot_id="duck-a", state="cancelled") == 1,
      [(m["attrs"]["robot_id"], m["attrs"]["state"], m["value"]) for m in point("robotics_lab.goals")])
check("a robot on an adapter not in the table is labelled unknown", value("robotics_lab.goals", robot_id="odd", state="timeout") == 1
      and point("robotics_lab.goals", robot_id="odd")[0]["attrs"]["robot_kind"] == "unknown"
      and point("robotics_lab.goals", robot_id="odd")[0]["attrs"]["host_kind"] == "unknown")
check("goals.active is back to 0 once every goal ended", all(m["value"] == 0 for m in point("robotics_lab.goals.active")) and point("robotics_lab.goals.active"),
      [(m["attrs"]["robot_id"], m["value"]) for m in point("robotics_lab.goals.active")])
dur = point("robotics_lab.goal.duration", robot_id="duck-a", state="reached")
check("the duration histogram: 12.5 s from the first running to the end (progress events do not restart it)",
      len(dur) == 1 and dur[0]["count"] == 1 and abs(dur[0]["value"] - 12.5) < 1e-6, dur)
check("a goal that ended with no running seen has no duration", not point("robotics_lab.goal.duration", robot_id="fk"))
an = point("robotics_lab.anomalies")
check("anomalies counted by anomaly, severity and source (the duck's, and the gate's one with no goal)",
      value("robotics_lab.anomalies", robot_id="duck-a", anomaly="rtf_low", severity="minor", source="navigator") == 1
      and value("robotics_lab.anomalies", robot_id="real-1", anomaly="someone_else_drives", severity="critical", source="gate") == 1
      and point("robotics_lab.anomalies", robot_id="real-1")[0]["attrs"]["host_kind"] == "microduck", [m["attrs"] for m in an])
check("stops: one per stop event, stop-all is not counted again", value("robotics_lab.stops", robot_id="duck-a") == 1
      and value("robotics_lab.stops", robot_id="nxt-1") == 1, point("robotics_lab.stops"))
check("errors counted", value("robotics_lab.errors", robot_id="nxt-1") == 1)
check("a group goal (no robot) and state and decision events send no metric",
      not [m for m in metrics if m["attrs"].get("robot_id") in (None, "None")] and not any(m["attrs"]["robot_id"] == "unknown" for m in metrics))

runs = [s for s in spans if s["name"] == "goal.run"]
by = {s["attrs"].get("goal_run"): s for s in runs}
check("goal.run: one span per goal that ran, started by running (6 ran; the refused and queued ones are not goal.run)", sorted(by) == [1, 2, 4, 5, 6],
      sorted(by))
ok = by.get(1)
check("goal.run, reached: no error status, run_key and the robot labels as attributes, the anomaly an event on it",
      ok and ok["status"] == 0 and ok["attrs"].get("run_key") == "duck/room/r1" and ok["attrs"].get("robot_id") == "duck-a"
      and ok["attrs"].get("robot_kind") == "legged" and ok["events"] == ["anomaly"] and ok["event_attrs"][0].get("anomaly") == "rtf_low"
      and ok["attrs"].get("state") == "reached", ok)
bad = by.get(2)
check("goal.run, failed: the error status with the reason", bad and bad["status"] == 2 and bad["status_message"] == "stuck at the door"
      and bad["attrs"].get("state") == "failed", bad)
check("goal.run, timeout: the error status", by.get(4) and by[4]["status"] == 2, by.get(4))
check("goal.run, cancelled by the operator: not an error", by.get(5) and by[5]["status"] == 0 and by[5]["attrs"]["state"] == "cancelled", by.get(5))
check("goal.run, ended with a must-not broken: the error status", by.get(6) and by[6]["status"] == 2 and by[6]["attrs"]["state"] == "done", by.get(6))
ref = [s for s in spans if s["name"] == "goal.refused"]
check("goal.refused: a span of zero length with the reason and the labels", len(ref) == 1 and ref[0]["start"] == ref[0]["end"]
      and ref[0]["attrs"].get("reason") == "robot busy" and ref[0]["attrs"].get("robot_id") == "fk" and ref[0]["attrs"].get("robot_kind") == "fake", ref)
loose = [s for s in spans if s["name"] == "anomaly"]
check("an anomaly with no active goal: a span of zero length", len(loose) == 1 and loose[0]["start"] == loose[0]["end"]
      and loose[0]["attrs"].get("anomaly") == "someone_else_drives", loose)

sev = {(r["attrs"].get("event.kind"), r["attrs"].get("robot_id")): (r["severity"], r["body"]) for r in logs}
check("logs carry event.kind and the robot labels", all(r["attrs"].get("event.kind") for r in logs) and all(r["attrs"].get("robot_id") for r in logs
                                                                                                     if r["attrs"]["event.kind"] != "stop-all"), logs[:2])
an_logs = {r["attrs"]["robot_id"]: r for r in logs if r["attrs"]["event.kind"] == "anomaly"}
check("anomaly logs: minor is WARN, critical is FATAL, the summary is the body", an_logs["duck-a"]["severity"] == "WARN"
      and an_logs["real-1"]["severity"] == "FATAL" and an_logs["duck-a"]["body"] == "slow sim" and an_logs["duck-a"]["attrs"].get("run_key") is None, an_logs)
check("robot-online is INFO, robot-offline is WARN with the error", sev.get(("robot-online", "duck-a"), ("",))[0] == "INFO"
      and sev.get(("robot-offline", "nxt-1"), ("",))[0] == "WARN" and "no answer" in sev[("robot-offline", "nxt-1")][1], sev)
check("an error event is an ERROR log with its message", sev.get(("error", "nxt-1")) == ("ERROR", "RuntimeError: boom"), sev.get(("error", "nxt-1")))
check("stop-all is one log, a stop is one", sum(1 for r in logs if r["attrs"]["event.kind"] == "stop-all") == 1
      and sum(1 for r in logs if r["attrs"]["event.kind"] == "stop") == 2, [r["attrs"]["event.kind"] for r in logs])
check("a refused goal, a failed goal and a finished goal are logged by their end", {r["attrs"].get("goal_run") for r in logs
                                                                                 if r["attrs"]["event.kind"] == "goal-run"} >= {1, 2, 3},
      [r["attrs"] for r in logs if r["attrs"]["event.kind"] == "goal-run"])
check("no log for state, decision or the group goal", not any(r["attrs"]["event.kind"] in ("state", "decision") for r in logs)
      and not any(r["attrs"].get("goal_run") == 9 for r in logs))
stub.stop()

# 3. the listener never raises, whatever arrives or whatever the sink does
stub = OtlpStub("ok")
sink = T.start(cfg_for(stub), "mission-control")
bus = EventBus(clock)
bus.listen(H.make(sink, ADAPTERS.get).listener)
raised = []
for kind, robot, data in [("goal-run", "duck-a", {"state": None}), ("goal-run", "duck-a", {"goal_run": {"a": 1}, "state": "running"}),
                          ("anomaly", "duck-a", {"anomaly": "not a dict"}), ("anomaly", "duck-a", {"anomaly": {"severity": 7, "anomaly": None}}),
                          ("anomaly", None, {"anomaly": {"anomaly": "x"}}), ("lock", "duck-a", {}), ("lock", "duck-a", {"event": None, "holder": object()}),
                          ("error", None, {}), ("stop", None, {}), ("stop-all", None, {"robots": "no"}), ("robot-online", "x" * 500, {}),
                          ("goal-run", "duck-a", {"state": "failed", "goal_run": 77}), (None, None, {}), ("nothing-known", "duck-a", {})]:
    try:
        bus.emit(kind, robot=robot, **data)
    except BaseException as e:
        raised.append((kind, e))
check("odd events never raise out of emit", not raised, raised)
sink.close()
stub.stop()


class Angry(T.Sink):
    def __getattribute__(self, name):
        if name in ("count", "gauge", "observe", "span_start", "span_end", "span_event", "log"):
            raise RuntimeError(name)
        return super().__getattribute__(name)


bus = EventBus(clock)
bus.listen(H.make(Angry(), ADAPTERS.get).listener)
seen = []
bus.listen(seen.append)       # a listener after ours still runs
try:
    for kind in ("robot-online", "goal-run", "anomaly", "stop", "error"):
        bus.emit(kind, robot="duck-a", state="running", anomaly={"anomaly": "x"})
    ok_ = True
except BaseException as e:
    ok_ = False
check("a sink that raises does not break emit, and the listeners after ours still run", ok_ and len(seen) == 5, seen)

# 4. a dead endpoint does not slow emit
stub = OtlpStub("refuse")
sink = T.start(cfg_for(stub), "mission-control")
bus = EventBus(clock)
bus.listen(H.make(sink, ADAPTERS.get).listener)
t0 = time.monotonic()
for i in range(250):
    bus.emit("goal-run", robot="duck-a", goal_run=i, state="running", run_key=f"duck/r/{i}")
    bus.emit("anomaly", robot="duck-a", goal_run=i, watch=None, anomaly={"anomaly": "rtf_low", "severity": "minor", "source": "navigator"})
    bus.emit("goal-run", robot="duck-a", goal_run=i, state="failed" if i % 2 else "reached", reason="x", result=None, broken=None)
    bus.emit("stop", robot="duck-a", client="page", confirmed=True)
took = time.monotonic() - t0
t0 = time.monotonic()
sink.close()
closed = time.monotonic() - t0
check("a dead endpoint: 1000 emits take under 3 s", took < 3.0, took)
check("a dead endpoint: close is bounded", closed < 5.0, closed)
bare = EventBus(clock)
t0 = time.monotonic()
for i in range(1000):
    bare.emit("stop", robot="duck-a", client="page", confirmed=True)
base = time.monotonic() - t0
check("a dead endpoint: the hook costs under 2 ms an emit over a bus with no hook", (took - base) / 1000 < 0.002, (took, base))

# 5. telemetry is off with no file or no block
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    err = io.StringIO()
    with redirect_stderr(err):
        none_ = H.sink_from_installation(tmp / "missing.json")
        noblock = H.sink_from_installation(installation_file(tmp / "plain.json"))
    check("no installation file: the Sink that does nothing, nothing said", type(none_) is T.Sink and err.getvalue() == "", err.getvalue())
    check("an installation with no telemetry block: the Sink that does nothing", type(noblock) is T.Sink)
    stub = OtlpStub("ok")
    block = {"environment": "check", "metrics": stub.url("metrics"), "logs": stub.url("logs"), "traces": stub.url("traces")}
    live = H.sink_from_installation(installation_file(tmp / "on.json", telemetry=block))
    check("an installation with the block: a live Sink", type(live) is not T.Sink)
    live.count("robotics_lab.stops", **labels("a", "b", "c"))
    live.close()
    check("... that reached the receiver", {m["name"] for m in stub.snapshot()[0]} == {"robotics_lab.stops"}, stub.snapshot()[0])
    stub.stop()
    (tmp / "bad.json").write_text(json.dumps({"installation": 1, "telemetry": {}}))
    err = io.StringIO()
    with redirect_stderr(err):
        bad_ = H.sink_from_installation(tmp / "bad.json")
    check("a bad telemetry block: the Sink that does nothing, one line said, Mission Control still starts", type(bad_) is T.Sink
          and err.getvalue().count("\n") == 1 and "telemetry" in err.getvalue(), err.getvalue())
    os.environ["ROBOTICS_LAB_INSTALLATION"] = str(tmp / "missing.json")
    try:
        env_ = H.sink_from_installation()
    finally:
        del os.environ["ROBOTICS_LAB_INSTALLATION"]
    check("the default path is $ROBOTICS_LAB_INSTALLATION (a missing file there: off)", type(env_) is T.Sink)

# 6. core wires the hook beside the alarms listener
stub = OtlpStub("ok")
sink = T.start(cfg_for(stub), "mission-control")
clock = Clock()
mc = MissionControl([RobotConfig(robot_file())], clock=clock, wall=clock, telemetry=sink)
for _ in range(3):
    clock.advance(0.2)
    mc.tick()
run = mc.run_adhoc({"goal": {"kind": "point", "params": {"x": 2.0, "y": 0.0}}, "robots": ["fake-1"]})
end = finish_run(mc, clock, run["id"])
mc.stop("fake-1", "page")
mc.close()
sink.close()
metrics, spans, logs = stub.snapshot()
check("core: a goal on the fake robot is a goal.run span labelled fake/fake", any(
    s["name"] == "goal.run" and s["attrs"].get("robot_id") == "fake-1" and s["attrs"].get("robot_kind") == "fake"
    and s["attrs"].get("host_kind") == "fake" for s in spans), [(s["name"], s["attrs"]) for s in spans])
check("core: the goal, the stop and the robot's presence are metrics",
      {"robotics_lab.goals", "robotics_lab.stops", "robotics_lab.robot.online"} <= {m["name"] for m in metrics}, sorted({m["name"] for m in metrics}))
check("core: the alarms listener still works beside it", mc.alarms is not None and end["state"] in ("reached", "done"), end["state"])
stub.stop()
mc2 = MissionControl([RobotConfig(robot_file())], clock=Clock(), wall=Clock())
check("core: with no sink given, nothing is added to the bus's listeners but the alarms'", len(mc2.bus._listeners) == 1, len(mc2.bus._listeners))
mc2.close()

finish("TELEMETRY-HOOK")
