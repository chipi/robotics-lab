"""Mission Control's telemetry hook (phase 5 steps 6 and 7, docs/wip/TELEMETRY-RETENTION-DESIGN.md): a listener on the EventBus that
maps robot-online, robot-offline, lock, goal-run, anomaly, stop, stop-all and error to the telemetry Sink (runfile.telemetry): the
metrics, the `goal.run` and `goal.refused` spans, a log record per event. It is the one place that knows what a robot is called in the
labels (RFC-0025: robot_id, robot_kind, host_kind).

The bus calls a listener on the emitting thread, and a listener that raises breaks that emit. This one only hands points to the Sink,
whose methods queue and swallow their errors, and it catches the rest: it never blocks and never raises.

A goal's span runs from its first `running` event to its end. The error status is for the ends that went wrong: failed, stalled, timeout,
not_found, stopped_by_guardrail, interrupted, or any end with a must-not broken. `done`/`reached`, `cancelled` (the operator's call)
and `refused` are not errors. A stop is counted from the robot's `stop` event; `stop-all` is one log record, because core emits a `stop`
for each robot it stops."""

import sys
import threading

from runfile import installation, telemetry as T

from . import goals

# adapter type -> (robot_kind, host_kind). robot_kind: what the robot is (RFC-0025); host_kind: what it runs on. duck-sim is the duck on
# its simulator host, duck-real the Microduck on its own board. A TurtleBot adds a row here, with no rename.
ROBOT_TABLE = {
    "duck-sim": ("legged", "pollen-duck-sim"),
    "duck-real": ("legged", "microduck"),
    "nxt-web": ("tracked", "nxt-brick"),
    "fake": ("fake", "fake"),
}
UNKNOWN = ("unknown", "unknown")
ERROR_ENDS = frozenset(goals.TERMINAL) - set(goals.SUCCESS) - {"refused", "cancelled"}
OPEN_GOALS = 1000
# The gate's log entries (libs/gate robotgate.Gate._log, libs/runner labrunner.gate.Proxy.log) by what they say about the lease.
# Anything not named here leaves the gauge alone: an event the gate adds later is not guessed to be a release.
LEASE_BEGINS = frozenset({"acquired"})
LEASE_ENDS = frozenset({"released", "expired", "taken_over", "lease_ended"})        # lease_ended: STOP by a client, someone else drives
LEASE_KEEPS = {"refused", "not_watched", "stop", "stop_failed"}       # gate log entries that say nothing about who holds the lease


def robot_labels(adapter_type) -> tuple:
    return ROBOT_TABLE.get(adapter_type, UNKNOWN)


def _text(v, default="unknown") -> str:
    return str(v) if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v) else default


class Hook:
    def __init__(self, sink, adapter_of):
        """`adapter_of(robot_id)` is the robot's adapter type (None or an exception: unknown)."""
        self.sink, self._adapter_of = sink, adapter_of
        self._labels: dict = {}
        self._open: dict = {}               # goal-run key -> (robot id, start time)
        self._lock = threading.Lock()

    def listener(self, event: dict) -> None:
        """What the EventBus calls."""
        try:
            data = dict(event)
            self.on_event(data.pop("kind", None), data.pop("robot", None), **data)
        except Exception:
            pass

    def on_event(self, kind, robot=None, **data) -> None:
        try:
            handler = getattr(self, "_on_" + str(kind).replace("-", "_"), None)
            if handler is not None and (robot is not None or kind in ("stop-all", "goal-run")):
                handler(robot, data)
        except Exception:
            pass

    def _robot(self, rid) -> dict:
        lab = self._labels.get(rid)
        if lab is None:
            try:
                kind, host = robot_labels(self._adapter_of(rid))
            except Exception:
                kind, host = UNKNOWN
            lab = {"robot_id": _text(rid), "robot_kind": kind, "host_kind": host}
            if len(self._labels) < 256:
                self._labels[rid] = lab
        return lab

    # --- presence and the lock -------------------------------------------------------------------------

    def _on_robot_online(self, robot, d) -> None:
        lab = self._robot(robot)
        self.sink.gauge("robotics_lab.robot.online", 1, **lab)
        self.sink.log("info", f"{robot} is online", kind="robot-online", **lab)

    def _on_robot_offline(self, robot, d) -> None:
        lab = self._robot(robot)
        self.sink.gauge("robotics_lab.robot.online", 0, **lab)
        self.sink.log("warn", f"{robot} is offline" + (f": {d['error']}" if d.get("error") else ""), kind="robot-offline", **lab)

    def _on_lock(self, robot, d) -> None:
        event = d.get("event")
        held = None
        if event == "holder":               # a remote gate's poll (duck-gate, nxt-web): nobody, also when the gate does not answer
            held = bool(d.get("holder"))
        elif event in LEASE_BEGINS:
            held = True
        elif event in LEASE_ENDS:
            held = False
        elif event == "disconnected" and "lease_id" in d:       # the gate's, for a holder that dropped; the proxy's own has no lease_id
            held = False
        elif event in LEASE_KEEPS or not event:
            return
        lab = self._robot(robot)
        if held is not None:
            self.sink.gauge("robotics_lab.robot.lock_held", int(held), **lab)
        self.sink.log("info", f"{robot} lock {event}" + (f" ({d['client']})" if d.get("client") else ""), kind="lock", event=event, **lab)

    # --- goals ----------------------------------------------------------------------------------------

    @staticmethod
    def _key(goal_run) -> str:
        return f"goal-run:{goal_run}"

    def _active(self, robot) -> int:
        return sum(1 for r, _ in self._open.values() if r == robot)

    def _on_goal_run(self, robot, d) -> None:
        if robot is None:
            return                      # a group goal over several robots: its children carry the signal
        state, run, key = d.get("state"), d.get("goal_run"), self._key(d.get("goal_run"))
        lab = self._robot(robot)
        if state == "running":
            with self._lock:
                fresh = key not in self._open
                if fresh:
                    if len(self._open) >= OPEN_GOALS:
                        self._open.pop(next(iter(self._open)))
                    self._open[key] = (robot, d.get("t"))
                n = self._active(robot)
            if fresh:
                self.sink.span_start(key, "goal.run", goal_run=run, run_key=d.get("run_key"), client=d.get("client"), **lab)
                self.sink.gauge("robotics_lab.goals.active", n, **lab)
                self.sink.log("info", f"goal run {run} running on {robot}", kind="goal-run", goal_run=run, state="running",
                              run_key=d.get("run_key"), **lab)
            return
        if state not in goals.TERMINAL:
            return                      # queued
        with self._lock:
            started = self._open.pop(key, None)
            n = self._active(robot)
        broken = bool(d.get("broken"))
        error = state in ERROR_ENDS or broken
        reason = d.get("reason")
        why = (str(reason) if reason else state) if state in ERROR_ENDS else ("a must-not was broken" if broken else None)
        if started is not None:
            self.sink.span_end(key, error=why if error else None, state=state, reason=reason)
            if started[1] is not None and d.get("t") is not None:
                self.sink.observe("robotics_lab.goal.duration", max(0.0, float(d["t"]) - float(started[1])), state=state, **lab)
            self.sink.gauge("robotics_lab.goals.active", n, **lab)
        elif state == "refused":
            self.sink.span_event(None, "goal.refused", goal_run=run, reason=reason, client=d.get("client"), **lab)
        self.sink.count("robotics_lab.goals", 1, state=state, **lab)
        self.sink.log("warn" if error else "info", f"goal run {run} {state} on {robot}" + (f": {reason}" if reason else ""), kind="goal-run",
                      goal_run=run, state=state, reason=reason, **lab)

    def _on_anomaly(self, robot, d) -> None:
        a = d.get("anomaly")
        a = a if isinstance(a, dict) else {}
        name, source = _text(a.get("anomaly")), _text(a.get("source"))
        severity = str(a.get("severity")).lower() if str(a.get("severity")).lower() in T.SEVERITIES else "info"
        lab = self._robot(robot)
        self.sink.count("robotics_lab.anomalies", 1, anomaly=name, severity=severity, source=source, **lab)
        run = d.get("goal_run")
        key = self._key(run) if run is not None else None
        self.sink.span_event(key, "anomaly", anomaly=name, severity=severity, source=source, summary=a.get("summary"), goal_run=run, **lab)
        self.sink.log(severity, a.get("summary") or name, kind="anomaly", anomaly=name, source=source, goal_run=run, **lab)

    # --- stops and errors ------------------------------------------------------------------------------

    def _on_stop(self, robot, d) -> None:
        lab = self._robot(robot)
        self.sink.count("robotics_lab.stops", 1, **lab)
        self.sink.log("info" if d.get("confirmed") else "warn", f"stop {robot}: " + ("confirmed" if d.get("confirmed") else "not confirmed"),
                      kind="stop", client=d.get("client"), confirmed=d.get("confirmed"), **lab)

    def _on_stop_all(self, robot, d) -> None:
        robots = d.get("robots") if isinstance(d.get("robots"), list) else []
        failed = [r.get("robot") for r in robots if isinstance(r, dict) and not r.get("confirmed")]
        self.sink.log("warn" if failed else "info", f"stop all: {len(robots)} robot(s)" + (f", not confirmed: {', '.join(map(str, failed))}" if failed else ""),
                      kind="stop-all", client=d.get("client"))

    def _on_error(self, robot, d) -> None:
        lab = self._robot(robot)
        self.sink.count("robotics_lab.errors", 1, **lab)
        self.sink.log("error", d.get("message") or "error", kind="error", **lab)


def make(sink, adapter_of) -> Hook:
    return Hook(sink, adapter_of)


def sink_from_installation(path=None, version: str = ""):
    """The telemetry Sink this machine's installation file asks for: the one that does nothing with no file or no `telemetry` block (and
    when the file is bad: one line, Mission Control still starts)."""
    try:
        inst = installation.load(path, required=False)
    except installation.InstallationError as exc:
        print(f"telemetry: off ({exc})", file=sys.stderr)
        return T.Sink()
    if inst is None or inst.telemetry is None:
        return T.Sink()
    return T.start(inst.telemetry, "mission-control", version=version)
