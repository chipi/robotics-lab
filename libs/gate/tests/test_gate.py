"""The gate's rules (RFC-0017 §3): the lease bound to a connection, expiry, release on disconnect,
the latching STOP, takeover, the log. A fake clock, a fake robot and fake connections; no sockets.
Run: cd robots/duck && uv run python tests/test_gate.py"""

import json
import shutil
import atexit
import tempfile
from pathlib import Path

import robotgate
from robotgate import Gate, GateError, JsonlLog, load_names

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Robot:
    """Records every call that reaches the robot."""

    def __init__(self):
        self.calls = []
        self.fail = False
        self.fail_methods = {}              # method -> the exception that call raises (a robot that answers move but not stop)

    def __call__(self, method, params):
        if self.fail:
            raise RuntimeError("robot gone")
        if method in self.fail_methods:
            raise self.fail_methods[method]
        self.calls.append((method, params))
        return {"ok": True}

    def stopped(self):
        """The gate's stop: robot.stop, then a zero move, last in the list."""
        return self.calls[-2:] == [("robot.stop", {}), ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})]


def refusal(gate, cid, method, params=None):
    try:
        gate.handle(cid, method, params)
    except GateError as exc:
        return exc
    return None


def make(names=("operator-laptop",)):
    clock, robot, log = Clock(), Robot(), []
    gate = Gate(robot, clock=clock, wall=lambda: 1_000_000.0, lease_s=20.0, takeover_names=names, log=log.append)
    return gate, clock, robot, log


MOVE = {"vx": 0.1, "vy": 0.0, "vyaw": 0.0}

# --- acquire, one driver at a time -----------------------------------------------------------
gate, clock, robot, log = make()
inbox_a, inbox_b = [], []
a = gate.open("mission-control", lambda m, p: inbox_a.append((m, p)))
b = gate.open("script", lambda m, p: inbox_b.append((m, p)))
check("a free robot: acquire gives a lease", gate.handle(a, "gate.acquire")["lease_id"] == 1)
check("the holder's move passes through unchanged", gate.handle(a, "robot.move", MOVE) == {"ok": True} and robot.calls[-1] == ("robot.move", MOVE))
err = refusal(gate, b, "gate.acquire")
check("a held robot: acquire is refused with who and since", err and err.code == "held" and "mission-control since" in str(err), err and str(err))
check("the refusal's data names the holder", err and err.data["holder"] == "mission-control")
before = len(robot.calls)
err = refusal(gate, b, "robot.move", MOVE)
check("a peer's move is refused and never reaches the robot", err and err.code == "held" and len(robot.calls) == before)
check("a peer cannot release it", refusal(gate, b, "gate.release").code == "not_holder")
check("acquiring again as the holder keeps the lease", gate.handle(a, "gate.acquire")["lease_id"] == 1)
who = gate.handle(b, "gate.who")
check("gate.who is open to anyone", who["holder"] == "mission-control" and who["lease_id"] == 1 and who["since"] == 1_000_000.0, who)
err = refusal(gate, a, "gate.takeover")
check("takeover is refused to a name not on the list", err and err.code == "not_allowed")
check("a peer cannot eject the holder: still held", gate.who()["holder"] == "mission-control")

# --- reading and no lease --------------------------------------------------------------------
check("reading needs no lease", gate.handle(b, "robot.state") == {"ok": True} and gate.handle(b, "robot.subscribe", {"hz": 10}) == {"ok": True})
gate2, _, robot2, _ = make()
c = gate2.open("script")
err = refusal(gate2, c, "robot.move", MOVE)
check("no lease, no motion", err and err.code == "no_lease" and robot2.calls == [])
check("an unknown method needs the lease too", refusal(gate2, c, "robot.dance").code == "no_lease")
check("robot.do needs the lease", refusal(gate2, c, "robot.do", {"skill": "fire"}).code == "no_lease")
check("a closed connection is refused", refusal(gate2, 999, "robot.state").code == "unknown_connection")

# --- release ---------------------------------------------------------------------------------
robot.calls.clear()
gate.handle(a, "gate.release")
check("release stops the robot", robot.stopped(), robot.calls)
check("release frees it for the peer", gate.handle(b, "gate.acquire")["lease_id"] == 2)
err = refusal(gate, a, "robot.move", MOVE)
check("the old holder is refused after release", err and err.code == "lease_ended" and err.data["reason"] == "released", err and str(err))
gate.handle(b, "gate.release")

# --- expiry ----------------------------------------------------------------------------------
gate, clock, robot, log = make()
inbox_a, inbox_b = [], []
a = gate.open("mission-control", lambda m, p: inbox_a.append((m, p)))
b = gate.open("script")
gate.handle(a, "gate.acquire")
clock.t += 15
gate.handle(a, "robot.move", MOVE)
clock.t += 15
gate.tick()
check("a move renews the lease", gate.who()["holder"] == "mission-control", gate.who())
gate.handle(a, "gate.keepalive")
clock.t += 19
check("a keepalive renews the lease", gate.who()["holder"] == "mission-control")
check("a read does not renew the lease", gate.handle(a, "robot.state") == {"ok": True})
clock.t += 2
robot.calls.clear()
check("silence past the lease: the gate frees it on its own clock", gate.who()["holder"] is None)
check("expiry stops the robot", robot.stopped(), robot.calls)
check("the frozen holder is told", inbox_a and inbox_a[-1][0] == "lease_lost" and "expired" in inbox_a[-1][1]["reason"], inbox_a)
robot.calls.clear()
err = refusal(gate, a, "robot.move", MOVE)
check("the frozen client wakes up and is refused", err and err.code == "lease_ended" and "expired" in err.data["reason"] and robot.calls == [], err and str(err))
check("a peer gets the robot now", gate.handle(b, "gate.acquire")["lease_id"] == 2)
err = refusal(gate, a, "robot.move", MOVE)
check("the woken client is refused because someone holds it", err and err.code == "lease_ended")
gate.handle(b, "gate.release")
check("it can acquire again when the robot is free", gate.handle(a, "gate.acquire")["lease_id"] == 3)
check("and then drives", gate.handle(a, "robot.move", MOVE) == {"ok": True})

# expiry is noticed by a call, with no timer
gate, clock, robot, log = make()
a = gate.open("mission-control")
b = gate.open("script")
gate.handle(a, "gate.acquire")
clock.t += 21
check("a peer's acquire after the lease ran out succeeds without a tick", gate.handle(b, "gate.acquire")["lease_id"] == 2)

# --- disconnect ------------------------------------------------------------------------------
gate, clock, robot, log = make()
a = gate.open("mission-control")
b = gate.open("script")
gate.handle(a, "gate.acquire")
robot.calls.clear()
gate.close(a)
check("a closed connection frees the robot at once (no waiting for expiry)", gate.who()["holder"] is None and clock.t == 100.0)
check("and stops it", robot.stopped(), robot.calls)
check("the peer can acquire right away", gate.handle(b, "gate.acquire")["lease_id"] == 2)
robot.calls.clear()
gate.close(b)
gate.close(b)
check("closing twice is harmless", robot.stopped())
gate.close(gate.open("idle"))
check("closing a connection that holds nothing does not stop the robot", len(robot.calls) == 2)

# --- STOP latches ----------------------------------------------------------------------------
gate, clock, robot, log = make()
inbox_a = []
a = gate.open("navigator", lambda m, p: inbox_a.append((m, p)))
b = gate.open("bystander")
gate.handle(a, "gate.acquire")
gate.handle(a, "robot.move", MOVE)
robot.calls.clear()
check("STOP from a connection with no lease is accepted, and the robot answered", gate.handle(b, "robot.stop") == {"ok": True, "confirmed": True, "errors": []})
check("STOP stops the robot", robot.stopped(), robot.calls)
check("STOP ends the holder's lease", gate.who()["holder"] is None)
check("the holder is told, with the name that stopped it", inbox_a[-1] == ("lease_lost", {"lease_id": 1, "reason": "stopped_by bystander"}), inbox_a)
robot.calls.clear()
err = refusal(gate, a, "robot.move", MOVE)
check("the 10 Hz resend is refused with the reason, it does not restart the robot", err and err.code == "lease_ended" and err.data["reason"] == "stopped_by bystander" and robot.calls == [], err and str(err))
err = refusal(gate, a, "robot.move", MOVE)
check("and again on the next tick: the latch holds", err and err.code == "lease_ended")
check("a keepalive does not clear the latch", refusal(gate, a, "gate.keepalive").code == "lease_ended")
check("acquiring clears it", gate.handle(a, "gate.acquire")["lease_id"] == 2 and gate.handle(a, "robot.move", MOVE) == {"ok": True})
robot.calls.clear()
gate.handle(a, "robot.stop")
check("the holder's own STOP latches too", refusal(gate, a, "robot.move", MOVE).data["reason"] == "stopped_by navigator" and robot.stopped())
robot.calls.clear()
gate.handle(b, "robot.stop")
check("STOP with nobody holding still stops the robot", robot.stopped(), robot.calls)

# the gate's stop is robust: a dead robot cannot keep a lease alive
gate, clock, robot, log = make()
a = gate.open("navigator")
gate.handle(a, "gate.acquire")
robot.fail = True
gate.close(a)
check("a robot that fails the stop still ends the lease", gate.who()["holder"] is None)
check("and the failure is logged", any(e["event"] == "stop_failed" for e in log), log)

# STOP says whether the robot answered robot.stop: accepted is not confirmed
for why, exc in (("raises", RuntimeError("robotd gone")), ("times out", TimeoutError("no answer from robotd"))):
    gate, clock, robot, log = make()
    a, b = gate.open("navigator"), gate.open("bystander")
    gate.handle(a, "gate.acquire")
    robot.fail_methods["robot.stop"] = exc
    robot.calls.clear()
    reply = gate.handle(b, "robot.stop")
    check(f"STOP with a holder, robot.stop {why}: accepted, not confirmed, the error said",
          reply["ok"] is True and reply["confirmed"] is False and len(reply["errors"]) == 1 and "robot.stop" in reply["errors"][0], reply)
    check(f"... the lease still ended and the zero move was still sent ({why})",
          gate.who()["holder"] is None and robot.calls == [("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})], robot.calls)
    reply = gate.handle(b, "robot.stop")
    check(f"STOP with no holder, robot.stop {why}: accepted, not confirmed, the error said",
          reply["ok"] is True and reply["confirmed"] is False and "robot.stop" in reply["errors"][0], reply)
    robot.fail_methods.clear()
    check("a robot that answers again is confirmed again", gate.handle(b, "robot.stop")["confirmed"] is True)
gate, clock, robot, log = make()
a, b = gate.open("navigator"), gate.open("bystander")
gate.handle(a, "gate.acquire")
check("STOP with a holder and a working robot: confirmed", gate.handle(b, "robot.stop") == {"ok": True, "confirmed": True, "errors": []})
gate.handle(a, "gate.acquire")
robot.fail = True
reply = gate.handle(a, "robot.stop")
check("STOP with the whole robot gone: accepted, not confirmed, both errors", reply["ok"] is True and reply["confirmed"] is False and len(reply["errors"]) == 2, reply)

# --- takeover --------------------------------------------------------------------------------
gate, clock, robot, log = make(names=("operator-laptop", "operator-phone"))
inbox_a = []
a = gate.open("friend-laptop", lambda m, p: inbox_a.append((m, p)))
o = gate.open("operator-laptop")
gate.handle(a, "gate.acquire")
gate.handle(a, "robot.move", MOVE)
robot.calls.clear()
lease = gate.handle(o, "gate.takeover")
check("an owner takes a lent robot back", lease["lease_id"] == 2 and gate.who()["holder"] == "operator-laptop", lease)
check("the robot is stopped before the new holder's first command", robot.stopped() and not any(c[0] == "robot.move" and c[1] == MOVE for c in robot.calls), robot.calls)
check("the old holder is told at once", inbox_a[-1] == ("lease_lost", {"lease_id": 1, "reason": "taken_over_by operator-laptop"}), inbox_a)
err = refusal(gate, a, "robot.move", MOVE)
check("the old holder is refused with the reason", err and err.data["reason"] == "taken_over_by operator-laptop")
check("the old holder cannot take it back: it is on no list", refusal(gate, a, "gate.takeover").code == "not_allowed")
check("takeover by the holder is a renewal, not a new lease", gate.handle(o, "gate.takeover")["lease_id"] == 2)
phone = gate.open("operator-phone")
check("a second owner may take it from the first (the owner's own devices)", gate.handle(phone, "gate.takeover")["lease_id"] == 3)
free, _, _, _ = make()
f = free.open("operator-laptop")
check("takeover of a free robot is an acquire", free.handle(f, "gate.takeover")["lease_id"] == 1)
nobody, _, _, _ = make(names=())
n = nobody.open("operator-laptop")
check("an empty takeover list allows nobody", refusal(nobody, n, "gate.takeover").code == "not_allowed")

# --- lease ids and unknown gate methods -----------------------------------------------------
gate, clock, robot, log = make()
a = gate.open("x")
ids = []
for _ in range(3):
    ids.append(gate.handle(a, "gate.acquire")["lease_id"])
    gate.handle(a, "gate.release")
check("the lease id grows with every lease", ids == [1, 2, 3], ids)
check("an unknown gate method is refused", refusal(gate, a, "gate.nope").code == "unknown_method")
check("the error shape carries the gate's code", GateError("held", "x", holder="y").to_rpc()["data"] == {"gate": "held", "protocol": 1, "holder": "y"})

# --- the log ---------------------------------------------------------------------------------
gate, clock, robot, log = make()
a = gate.open("mission-control")
b = gate.open("script")
o = gate.open("operator-laptop")
gate.handle(a, "gate.acquire")
refusal(gate, b, "gate.acquire")
gate.handle(b, "robot.stop")
gate.handle(a, "gate.acquire")
gate.handle(o, "gate.takeover")
gate.close(o)
events = [e["event"] for e in log]
check("the log records acquired, refused, stop, lease ended, taken over, disconnected",
      events[:2] == ["acquired", "refused"] and "stop" in events and "taken_over" in events and "disconnected" in events, events)
stop = next(e for e in log if e["event"] == "stop")
check("a STOP is logged with the connection's name", stop["client"] == "script", stop)
taken = next(e for e in log if e["event"] == "taken_over")
check("a takeover is logged: who, from whom", taken["by"] == "operator-laptop" and taken["client"] == "mission-control", taken)

# --- the protocol's version (RFC-0018 §5.3): `protocol` in gate.who and in every gate reply, and how a client reads it ----------
gate, clock, robot, log = make()
a, b = gate.open("mission-control"), gate.open("operator-laptop")
replies = {"gate.who (free)": gate.handle(a, "gate.who"), "gate.acquire": gate.handle(a, "gate.acquire"),
           "gate.who (held)": gate.handle(b, "gate.who"), "gate.keepalive": gate.handle(a, "gate.keepalive"),
           "gate.takeover": gate.handle(b, "gate.takeover"), "gate.release": gate.handle(b, "gate.release")}
check("must fail: the gate has a protocol number, 1", getattr(robotgate, "PROTOCOL", None) == 1)
check("must fail: every gate.* reply carries protocol: 1", all(r.get("protocol") == 1 for r in replies.values()),
      {k: r.get("protocol") for k, r in replies.items()})
check("must fail: Gate.who() carries it too (Mission Control reads it in process)", gate.who().get("protocol") == 1)
err = refusal(gate, a, "gate.keepalive")
check("must fail: a refusal carries it in its data", err is not None and err.to_rpc()["data"].get("protocol") == 1, err and err.to_rpc())
check("a robot's own reply is the robot's, passed on as it is", gate.handle(a, "robot.state") == {"ok": True})


def reading(reply):
    try:
        return robotgate.check_protocol(reply)
    except Exception as exc:       # noqa: BLE001 - the check's answer
        return exc


check_protocol = getattr(robotgate, "check_protocol", None)
if check_protocol is None:
    check("must fail: a client reads a gate's protocol (robotgate.check_protocol)", False)
else:
    import contextlib
    import io
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got = [reading({"protocol": 1}), reading({"holder": None}), reading({"holder": None}), reading({"protocol": 0})]
    check("a reply of this protocol is read as it says, a missing number as 0", got == [1, 0, 0, 0], got)
    check("a missing number is accepted with one warning only, naming the protocol", err.getvalue().count("protocol") >= 1
          and err.getvalue().count("\n") == 1, err.getvalue())
    newer = reading({"protocol": 2})
    check("must fail: a newer protocol is refused, both numbers said", isinstance(newer, robotgate.ProtocolError)
          and "2" in str(newer) and "1" in str(newer), newer)
    check("a protocol that is no number is refused", isinstance(reading({"protocol": "one"}), robotgate.ProtocolError))

tmp = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, tmp, True)
jl = JsonlLog(tmp / "gate" / "gate.jsonl", wall=lambda: 5.0)
gate = Gate(Robot(), clock=Clock(), log=jl)
gate.handle(gate.open("mission-control"), "gate.acquire")
lines = (tmp / "gate" / "gate.jsonl").read_text().splitlines()
check("the jsonl log writes one json line per event", len(lines) == 1 and json.loads(lines[0])["event"] == "acquired" and json.loads(lines[0])["at"] == 5.0, lines)

names = tmp / "takeover.txt"
names.write_text("# the operator's own\noperator-laptop\n\n  operator-phone  # the phone\n")
check("the takeover list: one name per line, comments and blanks skipped", load_names(names) == {"operator-laptop", "operator-phone"}, load_names(names))
check("a missing list is empty", load_names(tmp / "none.txt") == frozenset())

# --- the other-doors watch (RFC-0017 §3.8, RFC-0002 §3.6): a fake state source feeds observe_state -----------------------------
def watched(**kw):
    robot, clock, log = Robot(), Clock(), []
    g = Gate(robot, clock=clock, log=log.append, **kw)
    got = []
    cid = g.open("mission-control", lambda m, p: got.append((m, p)))
    g.open("viewer", lambda m, p: got.append(("viewer:" + m, p)))
    return g, robot, clock, log, got, cid


def feed(g, state):
    try:
        g.observe_state(state)
        return None
    except Exception as exc:
        return exc


def drive_state(source="gate-proxy", **move):
    return {"autonomous": False, "move": {"source": source, "applied": {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}, **move}}


def raised(log):
    return [e for e in log if e["event"] == "someone_else_drives"]


OURS = dict(own_sources={"gate-proxy"})
MOVING = {"vx": 0.3, "vy": 0.0, "vyaw": 0.0}

g, robot, clock, log, got, cid = watched(**OURS)
g.handle(cid, "gate.acquire")
n = len(robot.calls)
err = feed(g, drive_state(applied={"vx": 0.2, "vy": 0.0, "vyaw": 0.0}))
check("the holder driving (our source, motion, lease held) raises nothing",
      err is None and g.who()["holder"] == "mission-control" and not raised(log) and len(robot.calls) == n, (err, log))

g, robot, clock, log, got, cid = watched(**OURS)
g.handle(cid, "gate.acquire")
err = feed(g, {"autonomous": True, "move": {"source": "gate-proxy"}})
check("autonomous set: someone_else_drives is logged with the sign, the robot is stopped, the lease ended",
      err is None and len(raised(log)) == 1 and raised(log)[0]["signal"] == "autonomous" and robot.stopped()
      and g.who()["holder"] is None, (err, log))
check("the holder gets lease_lost naming someone_else_drives; every connection gets the someone_else_drives event",
      ("lease_lost", {"lease_id": 1, "reason": "someone_else_drives"}) in got
      and any(m == "someone_else_drives" for m, p in got) and any(m == "viewer:someone_else_drives" for m, p in got), got)
n = len(robot.calls)
feed(g, {"autonomous": True})
check("the same episode raises once, not at every frame", len(raised(log)) == 1 and len(robot.calls) == n, log)
feed(g, {"autonomous": False})
feed(g, {"autonomous": True})
check("a clean frame re-arms: the next episode raises again", len(raised(log)) == 2, log)
r = refusal(g, cid, "robot.move", {"vx": 0.1})
check("the ended holder is told why when it calls", getattr(r, "data", {}).get("reason") == "someone_else_drives", r)

g, robot, clock, log, got, cid = watched(**OURS)
g.handle(cid, "gate.acquire")
feed(g, drive_state(source="pollen-app"))
check("a move.source that is not ours raises, stops, ends the lease",
      len(raised(log)) == 1 and raised(log)[0].get("signal") == "move.source" and raised(log)[0].get("source") == "pollen-app"
      and robot.stopped() and g.who()["holder"] is None, log)

g, robot, clock, log, got, cid = watched(**OURS)
feed(g, drive_state(applied=MOVING))
check("motion while no lease is held raises and stops the robot",
      len(raised(log)) == 1 and raised(log)[0].get("signal") == "motion_without_lease" and robot.stopped(), log)

g, robot, clock, log, got, cid = watched(**OURS)
g.handle(cid, "gate.acquire")
g.handle(cid, "gate.release")
feed(g, drive_state(applied=MOVING))
check("the robot still coasting just after the gate's own stop is not someone else", not raised(log), log)
clock.t += 5
feed(g, drive_state(applied=MOVING))
check("the same motion seconds after the stop is", len(raised(log)) == 1, log)

g, robot, clock, log, got, cid = watched(**OURS)
g.handle(cid, "gate.acquire")
n = len(robot.calls)
errs = [feed(g, {}), feed(g, {"pose": [0, 0, 0]}), feed(g, {}), feed(g, "not a state")]
nw = [e for e in log if e["event"] == "not_watched"]
check("fields robotd does not fill raise nothing and are reported once as not watched",
      errs == [None] * 4 and len(nw) == 1 and set(nw[0]["fields"]) == {"autonomous", "move.source", "move.applied"}
      and g.who()["holder"] == "mission-control" and len(robot.calls) == n and not raised(log), (errs, log))

g, robot, clock, log, got, cid = watched()
g.handle(cid, "gate.acquire")
feed(g, drive_state(source="anyone"))
check("without a named own source, move.source is not judged and is reported as not watched",
      g.who()["holder"] == "mission-control" and any(e["event"] == "not_watched" and "move.source" in e["fields"] for e in log), log)

# --- Pollen's wire shapes (duck-ipc-proto at 094d4bb4): `move.applied` is [vx, vy, vyaw]; `autonomous` is left out when false; the
# open methods are reads -------------------------------------------------------------------------------------------------------
def pollen_state(applied=(0.0, 0.0, 0.0), source=None, **top):
    move = {"applied": list(applied)}
    if source is not None:
        move["source"] = source
    return {"move": move, **top}


g, robot, clock, log, got, cid = watched(**OURS)
feed(g, pollen_state(applied=[0.3, 0.0, 0.0], source="gate-proxy"))
check("an applied array with motion and no lease raises motion_without_lease",
      len(raised(log)) == 1 and raised(log)[0].get("signal") == "motion_without_lease" and robot.stopped(), log)

g, robot, clock, log, got, cid = watched(**OURS)
feed(g, pollen_state(applied=[0.0, 0.0, 0.0005], source="gate-proxy"))
check("an applied array at rest raises nothing and is watched (not in not_watched)",
      not raised(log) and not any("move.applied" in e.get("fields", ()) for e in log if e["event"] == "not_watched"), log)

g, robot, clock, log, got, cid = watched(**OURS)
g.handle(cid, "gate.acquire")
feed(g, pollen_state(applied=(0.0, 0.0, 0.4), source="gate-proxy"))
check("an applied array while the holder drives raises nothing", not raised(log) and g.who()["holder"] == "mission-control", log)

g, robot, clock, log, got, cid = watched(omits_false_autonomous=True, **OURS)
g.handle(cid, "gate.acquire")
feed(g, pollen_state(source="gate-proxy"))
check("with omits_false_autonomous, an absent autonomous is false: watched, raises nothing",
      not raised(log) and not any("autonomous" in e.get("fields", ()) for e in log if e["event"] == "not_watched"), log)
feed(g, pollen_state(source="gate-proxy", autonomous=True))
check("... and autonomous true raises",
      len(raised(log)) == 1 and raised(log)[0]["signal"] == "autonomous" and robot.stopped() and g.who()["holder"] is None, log)

g, robot, clock, log, got, cid = watched(**OURS)
feed(g, pollen_state(source="gate-proxy"))
check("without the option an absent autonomous is not watched, as before",
      any(e["event"] == "not_watched" and "autonomous" in e["fields"] for e in log), log)

g, robot, clock, log, got, cid = watched(**OURS)
g.handle(cid, "gate.acquire")
feed(g, pollen_state(source="gate-proxy"))
check("a move.source equal to an own source raises nothing", not raised(log), log)
feed(g, pollen_state(source="pollen-pad"))
check("another move.source raises", len(raised(log)) == 1 and raised(log)[0].get("source") == "pollen-pad", log)

g, robot, clock, log, got, cid = watched(**OURS)
check("the read-only Pollen methods pass without a lease",
      all(refusal(g, cid, m) is None for m in ("robot.modelApi", "robot.policies", "robot.skills", "robot.vetbook", "pad.status")),
      [refusal(g, cid, m) for m in ("robot.modelApi", "pad.status")])

print()
print("FAIL: " + ", ".join(failures) if failures else "all passed")
raise SystemExit(1 if failures else 0)
