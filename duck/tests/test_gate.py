"""The gate's rules (RFC-0017 §3): the lease bound to a connection, expiry, release on disconnect,
the latching STOP, takeover, the log. A fake clock, a fake robot and fake connections; no sockets.
Run: cd duck && uv run python tests/test_gate.py"""

import json
import tempfile
from pathlib import Path

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

    def __call__(self, method, params):
        if self.fail:
            raise RuntimeError("robot gone")
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
check("STOP from a connection with no lease is accepted", gate.handle(b, "robot.stop") == {"ok": True})
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
check("the error shape carries the gate's code", GateError("held", "x", holder="y").to_rpc()["data"] == {"gate": "held", "holder": "y"})

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

tmp = Path(tempfile.mkdtemp())
jl = JsonlLog(tmp / "gate" / "gate.jsonl", wall=lambda: 5.0)
gate = Gate(Robot(), clock=Clock(), log=jl)
gate.handle(gate.open("mission-control"), "gate.acquire")
lines = (tmp / "gate" / "gate.jsonl").read_text().splitlines()
check("the jsonl log writes one json line per event", len(lines) == 1 and json.loads(lines[0])["event"] == "acquired" and json.loads(lines[0])["at"] == 5.0, lines)

names = tmp / "takeover.txt"
names.write_text("# the operator's own\noperator-laptop\n\n  operator-phone  # the phone\n")
check("the takeover list: one name per line, comments and blanks skipped", load_names(names) == {"operator-laptop", "operator-phone"}, load_names(names))
check("a missing list is empty", load_names(tmp / "none.txt") == frozenset())

print()
print("FAIL: " + ", ".join(failures) if failures else "all passed")
raise SystemExit(1 if failures else 0)
