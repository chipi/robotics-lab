"""Telemetry (runfile.telemetry, docs/wip/TELEMETRY-RETENTION-DESIGN.md): the block absent is a Sink that does nothing (no threads, no SDK
import); against a local OTLP receiver the metrics' names, units and label sets, the resource, the spans and their status, and the log
severities arrive as designed; the run goes on when the port is closed (1000 events, a bounded close), the receiver answers 500 or
never answers, a label value is bad, or the SDK does not import; a robot kind added to the table labels the same metrics; no token
in the module. Mission Control's hook is tested through core.
Run: cd apps/mission-control && uv run python tests/test_telemetry.py"""

import io
import logging
import os
import sys
import threading
import time
from contextlib import redirect_stderr
from pathlib import Path

for k in [k for k in os.environ if k.startswith("OTEL_")]:
    del os.environ[k]

from common import check, finish
from otlp_stub import OtlpStub

from runfile import telemetry as T
from runfile.installation import Telemetry

check("importing the module imports no SDK", not any(m.startswith("opentelemetry.sdk") for m in sys.modules))

DUCK = {"robot_id": "duck-a", "robot_kind": "legged", "host_kind": "pollen-duck-sim"}
NXT = {"robot_id": "nxt-1", "robot_kind": "tracked", "host_kind": "nxt-brick"}
TURTLE = {"robot_id": "tb3-1", "robot_kind": "wheeled", "host_kind": "turtlebot3-burger"}   # a new row in Mission Control's table, no rename
ROBOT = set(T.ROBOT_LABELS)
EXTRA = {"robotics_lab.goals": {"state": "succeeded"}, "robotics_lab.goal.duration": {"state": "failed"},
         "robotics_lab.anomalies": {"anomaly": "rtf_low", "severity": "minor", "source": "navigator"}}


def cfg_for(stub, metrics=True, traces=True, logs=True, env="check"):
    return Telemetry(env, stub.url("traces") if traces else None, stub.url("metrics") if metrics else None,
                     stub.url("logs") if logs else None, 5)


def emit_all(sink, robot):
    for n, (kind, unit, extra) in T.INSTRUMENTS.items():
        labels = {**robot, **EXTRA.get(n, {})}
        {"gauge": lambda: sink.gauge(n, 1, **labels), "counter": lambda: sink.count(n, 2, **labels),
         "histogram": lambda: sink.observe(n, 1.5, **labels)}[kind]()


# 1. the block absent
threads0 = threading.active_count()
null = T.start(None, "mission-control", version="9.9")
for call in (lambda: null.count("robotics_lab.stops", **DUCK), lambda: null.gauge("robotics_lab.robot.online", 1, **DUCK),
             lambda: null.observe("robotics_lab.goal.duration", 1.0, state="x", **DUCK), lambda: null.span_start("k", "goal.run"),
             lambda: null.span_event("k", "e"), lambda: null.span_end("k", error="x"), lambda: null.log("major", "x", kind="k"), null.close):
    call()
check("no block: a Sink that does nothing, every call works", type(null) is T.Sink and null.dropped == 0)
check("no block: no threads started, no SDK imported", threading.active_count() == threads0
      and not any(m.startswith("opentelemetry.sdk") for m in sys.modules), threading.enumerate())
check("no block: the logging handler is a null handler", isinstance(null.logging_handler(), logging.NullHandler))

# 2. names, units, labels, resource, spans, logs
stub = OtlpStub("ok")
sink = T.start(cfg_for(stub), "mission-control", version="0.1.0")
check("a block: the live Sink", type(sink) is not T.Sink)
emit_all(sink, DUCK)
emit_all(sink, NXT)
sink.count("robotics_lab.goals", 1, **DUCK, state="succeeded", run_key="duck/scene/1")
sink.span_start("g1", "goal.run", goal="g1", run_key="duck/scene/1", **DUCK)
sink.span_event("g1", "anomaly", anomaly="rtf_low", severity="minor")
sink.span_end("g1")
sink.span_start("g2", "goal.run", goal="g2", **NXT)
sink.span_end("g2", error="stuck", state="failed")
sink.span_event(None, "goal.refused", reason="busy", **DUCK)
sink.span_event(None, "anomaly", anomaly="rtf_low", **DUCK)
sink.log("minor", "slow", kind="anomaly", **DUCK)
sink.log("major", "wall", kind="anomaly", run_key="r1")
sink.log("critical", "tipped", kind="anomaly")
sink.log("info", "started", kind="robot-online")
handler = sink.logging_handler()
lg = logging.getLogger("mission_control")
lg.addHandler(handler)
lg.setLevel(logging.INFO)
lg.warning("a bridged warning")
lg.removeHandler(handler)
t0 = time.monotonic()
sink.close()
metrics, spans, logs = stub.snapshot()
check("close flushed within its bound", time.monotonic() - t0 < 5, time.monotonic() - t0)
by = {}
for m in metrics:
    by.setdefault(m["name"], []).append(m)
check("every instrument of the table arrived, no other", set(by) == set(T.INSTRUMENTS), sorted(by))
check("the units", all(m["unit"] == T.INSTRUMENTS[m["name"]][1] for m in metrics), {m["name"]: m["unit"] for m in metrics})
check("the kinds: gauge, sum, histogram", {n: by[n][0]["kind"] for n in by} == {n: {"gauge": "gauge", "counter": "sum", "histogram": "histogram"}[k]
                                                                                for n, (k, _, _) in T.INSTRUMENTS.items()})
check("the label sets: the robot's three plus the instrument's own, nothing else (run_key is no metric label)",
      all(set(m["attrs"]) == ROBOT | set(T.INSTRUMENTS[m["name"]][2]) for m in metrics),
      {n: sorted(by[n][0]["attrs"]) for n in by})
check("robot labels as given for both robots", {m["attrs"]["robot_id"] for m in metrics} == {"duck-a", "nxt-1"}
      and any(m["attrs"].get("robot_kind") == "tracked" and m["attrs"].get("host_kind") == "nxt-brick" for m in metrics))
goals = [m for m in by["robotics_lab.goals"] if m["attrs"]["robot_id"] == "duck-a"]
check("a counter adds up (2 and 1)", goals and goals[0]["value"] == 3, goals)
check("the histogram carries its count and sum", by["robotics_lab.goal.duration"][0]["count"] == 1
      and by["robotics_lab.goal.duration"][0]["value"] == 1.5, by["robotics_lab.goal.duration"][0])
res = metrics[0]["resource"]
check("resource: service.name, namespace, version, environment",
      res.get("service.name") == "robotics-lab-mission-control" and res.get("service.namespace") == "robotics-lab"
      and res.get("service.version") == "0.1.0" and res.get("deployment.environment.name") == "check", res)
check("the same resource on spans and logs", all(s["resource"].get("service.name") == "robotics-lab-mission-control"
                                                  and s["resource"].get("deployment.environment.name") == "check" for s in spans)
      and all(r["resource"].get("service.name") == "robotics-lab-mission-control" for r in logs))
sp = {s["name"] + ":" + str(s["attrs"].get("goal", s["attrs"].get("reason", ""))): s for s in spans}
ok_run, bad_run = sp.get("goal.run:g1"), sp.get("goal.run:g2")
check("goal.run ok: unset status, the run_key as a span attribute, the anomaly an event on it",
      ok_run and ok_run["status"] == 0 and ok_run["attrs"].get("run_key") == "duck/scene/1" and ok_run["events"] == ["anomaly"]
      and ok_run["event_attrs"][0].get("severity") == "minor", ok_run)
check("goal.run failed: the error status and its message", bad_run and bad_run["status"] == 2 and bad_run["status_message"] == "stuck"
      and bad_run["attrs"].get("state") == "failed", bad_run)
refused = sp.get("goal.refused:busy")
check("goal.refused: a span of zero length", refused and refused["start"] == refused["end"] and refused["attrs"]["robot_id"] == "duck-a", refused)
loose = [s for s in spans if s["name"] == "anomaly"]
check("an anomaly with no active run: a span of zero length", len(loose) == 1 and loose[0]["start"] == loose[0]["end"], loose)
sev = {r["body"]: (r["severity"], r["severity_number"]) for r in logs}
check("log severities: minor WARN, major ERROR, critical FATAL, info INFO",
      sev.get("slow") == ("WARN", 13) and sev.get("wall") == ("ERROR", 17) and sev.get("tipped") == ("FATAL", 21)
      and sev.get("started") == ("INFO", 9), sev)
byb = {r["body"]: r for r in logs}
check("a log carries event.kind and its attributes (run_key allowed on a log)", byb["slow"]["attrs"].get("event.kind") == "anomaly"
      and byb["wall"]["attrs"].get("run_key") == "r1" and byb["slow"]["attrs"].get("robot_id") == "duck-a", byb["slow"])
check("the mission_control logger's bridge: its warning arrives as WARN", sev.get("a bridged warning", ("",))[0] == "WARN", sev)
check("no Authorization header, no header carrying a credential", stub.requests and not any(
    k in ("authorization", "proxy-authorization") or "token" in k or "key" in k for h in stub.headers for k in h), stub.headers[:1])
check("the paths are used as given", {r for r in stub.requests} == {"/v1/traces", "/v1/metrics", "/v1/logs"}, set(stub.requests))
stub.stop()
sink.count("robotics_lab.stops", **DUCK)
sink.log("info", "after close")
sink.span_start("z", "late")

# 2b. only one signal
stub = OtlpStub("ok")
only = T.start(cfg_for(stub, traces=False, logs=False), "mission-control")
only.span_start("k", "goal.run")
only.span_end("k")
only.log("info", "x")
only.count("robotics_lab.stops", **DUCK)
only.close()
metrics, spans, logs = stub.snapshot()
check("only the metrics URL given: metrics sent, no spans or logs, and the other calls do not raise",
      metrics and not spans and not logs and set(stub.requests) == {"/v1/metrics"} and isinstance(only.logging_handler(), logging.NullHandler),
      stub.requests)
stub.stop()

# 3. a TurtleBot row labels the same metrics
stub = OtlpStub("ok")
tb = T.start(cfg_for(stub, traces=False, logs=False), "mission-control")
emit_all(tb, TURTLE)
tb.close()
metrics, _, _ = stub.snapshot()
check("a TurtleBot (a new robot_kind and host_kind) labels the same instruments with the same label keys",
      {m["name"] for m in metrics} == set(T.INSTRUMENTS) and all(set(m["attrs"]) == ROBOT | set(T.INSTRUMENTS[m["name"]][2]) for m in metrics)
      and {m["attrs"]["robot_kind"] for m in metrics} == {"wheeled"}, sorted({m["attrs"]["robot_kind"] for m in metrics}))
stub.stop()


def storm(sink, n=1000):
    t = time.monotonic()
    for i in range(n):
        sink.count("robotics_lab.stops", **DUCK)
        sink.span_start(i, "goal.run", goal=str(i), **DUCK)
        sink.span_end(i, error="x" if i % 2 else None)
        sink.log("minor", f"event {i}", kind="anomaly", **DUCK)
    return time.monotonic() - t


# 4. must-fail: a closed port
stub = OtlpStub("refuse")
s = T.start(cfg_for(stub), "mission-control")
took = storm(s)
t0 = time.monotonic()
s.close()
closed = time.monotonic() - t0
check("a closed port: 1000 events of each kind never block the caller", took < 5, took)
check("a closed port: close returns under 5 s", closed < 5, closed)

# 5. must-fail: 500
stub = OtlpStub("500")
s = T.start(cfg_for(stub), "mission-control")
took = storm(s, 200)
t0 = time.monotonic()
s.close()
closed = time.monotonic() - t0
check("a 500: the run goes on and close is bounded", took < 5 and closed < 5, (took, closed))
check("a 500: the receiver was tried", len(stub.requests) > 0, stub.requests)
stub.stop()

# 6. must-fail: a receiver that never answers
stub = OtlpStub("hang")
s = T.start(cfg_for(stub), "mission-control")
took = storm(s, 200)
s.count("robotics_lab.stops", **DUCK)
t0 = time.monotonic()
s.close(timeout=2.0)
closed = time.monotonic() - t0
check("a hang: the caller is not blocked", took < 5, took)
check("a hang: close returns within its own timeout (2 s) and a little", closed < 3.0, closed)
check("a hang: the receiver was reached", len(stub.requests) > 0, stub.requests)
s2 = T.start(cfg_for(stub), "mission-control")
s2.count("robotics_lab.stops", **DUCK)
t0 = time.monotonic()
s2.close()
check("a hang: the default close is under 5 s", time.monotonic() - t0 < 5, time.monotonic() - t0)
stub.stop()

# 7. must-fail: bad label values and bad calls
stub = OtlpStub("ok")
s = T.start(cfg_for(stub), "mission-control")
bad = [lambda: s.count("robotics_lab.stops", **{**DUCK, "robot_id": None}), lambda: s.count("robotics_lab.stops", **{**DUCK, "robot_id": {"a": 1}}),
       lambda: s.count("robotics_lab.stops", **{**DUCK, "robot_id": ""}), lambda: s.count("robotics_lab.stops", **{**DUCK, "robot_id": "x" * 500}),
       lambda: s.count("robotics_lab.stops", **{k: v for k, v in DUCK.items() if k != "host_kind"}),
       lambda: s.count("robotics_lab.goals", **DUCK), lambda: s.count("robotics_lab.stops", float("nan"), **DUCK),
       lambda: s.count("robotics_lab.stops", "many", **DUCK), lambda: s.count("robotics_lab.no_such", **DUCK),
       lambda: s.gauge("robotics_lab.stops", 1, **DUCK), lambda: s.log("loud", "x"), lambda: s.span_end("never-started", error="x")]
raised = []
for i, f in enumerate(bad):
    try:
        f()
    except BaseException as e:
        raised.append((i, e))
s.count("robotics_lab.stops", 1, **{**DUCK, "robot_id": "good"})
s.close()
metrics, _, logs = stub.snapshot()
check("bad label values and bad calls: nothing raises", not raised, raised)
check("bad label values and bad calls: each counted as dropped (the never-started span end is not a drop)", s.dropped == len(bad) - 1, s.dropped)
check("bad label values: no point of them sent, the good one after them is", [m["attrs"]["robot_id"] for m in metrics] == ["good"]
      and not logs, [(m["name"], m["attrs"]) for m in metrics])
stub.stop()

# 8. must-fail: the SDK does not import
real = {k: sys.modules[k] for k in ("opentelemetry.sdk.trace",) if k in sys.modules}
sys.modules["opentelemetry.sdk.trace"] = None
err = io.StringIO()
try:
    with redirect_stderr(err):
        s = T.start(Telemetry("dev", "http://127.0.0.1:1/v1/traces", None, None, 15), "mission-control")
finally:
    sys.modules.pop("opentelemetry.sdk.trace", None)
    sys.modules.update(real)
s.count("robotics_lab.stops", **DUCK)
s.log("critical", "x")
s.close()
check("the SDK does not import: the Sink that does nothing, one line said", type(s) is T.Sink and err.getvalue().count("\n") == 1
      and err.getvalue().startswith("telemetry: off"), err.getvalue())

# 9. the limits and the module's text
src = Path(T.__file__).read_text().lower()
check("exporters time out at 3 s, queues are bounded", T.EXPORT_TIMEOUT_S == 3.0 and 0 < T.QUEUE <= 2048 and T.OPEN_SPANS <= 10000)
check("no token, credential or Authorization header in the module", not any(w in src for w in ("authorization", "bearer", "token", "password",
                                                                                                 "secret", "api_key", "basic ")))
finish("TELEMETRY")
