"""The gate's socket proxy (RFC-0017 §3.2, §5 step 3) in front of a stand-in for robotd: ids routed per client over one upstream
connection, the subscribe stream relayed, the lease enforced on the wire (held, STOP latch, disconnect, expiry, takeover), the log.
No simulator: the stand-in speaks robotd's newline-framed JSON-RPC over a Unix socket.
Run: cd robots/duck && uv run python tests/test_gate_proxy.py"""

import json
import socket
import tempfile
import threading
import time
from pathlib import Path

from labrunner.gate import Proxy

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:200]}]" if detail else ""))
    if not cond:
        failures.append(name)


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class FakeRobotd:
    """Answers like robotd: echoes `tag`, records every request with the connection it came on, streams robot.state to a
    connection after it subscribes."""

    def __init__(self, path: Path):
        self.path = path
        self.calls: list = []
        self.conns: list = []
        self._lock = threading.Lock()
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(4)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        n = 0
        while True:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            n += 1
            self.conns.append(sock)
            threading.Thread(target=self._serve, args=(sock, n), daemon=True).start()

    def _serve(self, sock, n):
        send_lock = threading.Lock()

        def send(msg):
            with send_lock:
                sock.sendall((json.dumps(msg) + "\n").encode())

        rate = {"hz": 33.0, "streaming": False}      # robotd's rule: one stream per connection, at the last subscribe's rate

        def stream():
            seq = 0
            while True:
                seq += 1
                try:
                    send({"jsonrpc": "2.0", "method": "robot.state", "params": {"seq": seq}})
                except OSError:
                    return
                time.sleep(1.0 / rate["hz"])

        for line in sock.makefile("r"):
            req = json.loads(line)
            with self._lock:
                self.calls.append((n, req["method"], req.get("params")))
            m, p = req["method"], req.get("params") or {}
            if m == "robot.fail":
                send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -5, "message": "boom"}})
            elif m == "robot.subscribe" and "hz" in p and (isinstance(p["hz"], bool) or not isinstance(p["hz"], int)):
                # robotd's own refusal (read from it, 2026-11-22): hz is an integer, 5.0 is not
                send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32602,
                                                                   "message": f"invalid type: floating point `{p['hz']}`, expected u32"}})
            elif m == "robot.subscribe":
                rate["hz"] = float(p.get("hz") or 33.0)
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"policy": "fake", "hz": p.get("hz")}})
                if not rate["streaming"]:
                    rate["streaming"] = True
                    threading.Thread(target=stream, daemon=True).start()
            elif m in ("robot.move", "robot.stop", "robot.state", "robot.health"):
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True, "tag": p.get("tag")}})
            else:
                send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": "no such method"}})

    def methods(self):
        with self._lock:
            return [m for _, m, _ in self.calls]

    def close(self):
        for c in self.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.server.close()


class Client:
    def __init__(self, path: Path, hello: str | None = None):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(str(path))
        self.sock.settimeout(5)
        self.f = self.sock.makefile("r")
        self.notes: list = []
        self.replies: dict = {}
        self.alive = True
        threading.Thread(target=self._read, daemon=True).start()
        if hello:
            self.call("hello", {"client": hello})

    def _read(self):
        try:
            for line in self.f:
                msg = json.loads(line)
                if "id" in msg and msg["id"] is not None:
                    self.replies[msg["id"]] = msg
                else:
                    self.notes.append(msg)
        except (OSError, ValueError):
            pass
        self.alive = False

    def send(self, method, params=None, rid=1):
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            req["params"] = params
        self.sock.sendall((json.dumps(req) + "\n").encode())

    def call(self, method, params=None, rid=1):
        self.replies.pop(rid, None)
        self.send(method, params, rid)
        assert wait_for(lambda: rid in self.replies), f"no reply to {method}"
        return self.replies.pop(rid)

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


MOVE = {"vx": 0.1, "vy": 0.0, "vyaw": 0.0}
ZERO = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    robotd = FakeRobotd(tmp / "robotd.sock")
    names = tmp / "takeover.txt"
    names.write_text("# the operator's own\noperator\n")
    logfile = tmp / "gate.jsonl"
    proxy = Proxy(tmp / "gate.sock", tmp / "robotd.sock", takeover_names={"operator"}, log=logfile, lease_s=1.5)
    proxy.start()
    check("the proxy listens on its own socket, mode 660", (tmp / "gate.sock").exists() and oct((tmp / "gate.sock").stat().st_mode & 0o777) == "0o660")

    a = Client(tmp / "gate.sock", hello="navigator")
    b = Client(tmp / "gate.sock", hello="script")
    anon = Client(tmp / "gate.sock")
    check("hello is answered by the gate and not sent upstream", robotd.methods() == [] and a.call("hello", {"client": "again"})["result"]["client"] == "navigator")

    # ids per client
    a.send("robot.state", {"tag": "from-a"}, rid=1)
    b.send("robot.state", {"tag": "from-b"}, rid=1)
    check("two clients that both use id 1 each get their own reply", wait_for(lambda: 1 in a.replies and 1 in b.replies)
          and a.replies[1]["result"]["tag"] == "from-a" and b.replies[1]["result"]["tag"] == "from-b", (a.replies, b.replies))
    check("they went upstream on one connection", len({n for n, m, _ in robotd.calls if m == "robot.state"}) == 1 and len(robotd.conns) == 1)

    # the lease on the wire
    r = a.call("robot.move", MOVE)
    check("no lease, no motion: refused with the gate's code, nothing upstream", r["error"]["data"]["gate"] == "no_lease" and "robot.move" not in robotd.methods(), r)
    check("gate.acquire", a.call("gate.acquire")["result"]["lease_id"] == 1)
    check("the holder's move passes through with its params", a.call("robot.move", MOVE)["result"]["ok"] and (1, "robot.move", MOVE) in robotd.calls)
    r = b.call("gate.acquire")
    check("a second client is refused with who holds it and since", r["error"]["data"]["gate"] == "held" and r["error"]["data"]["holder"] == "navigator"
          and "navigator since" in r["error"]["message"], r)
    n_moves = robotd.methods().count("robot.move")
    r = b.call("robot.move", MOVE)
    check("its move never reaches the robot", r["error"]["data"]["gate"] == "held" and robotd.methods().count("robot.move") == n_moves)
    check("an anonymous client is named by the proxy and is refused too", anon.call("robot.move", MOVE)["error"]["data"]["gate"] == "held")
    check("reading is open to every client", b.call("robot.state", {"tag": "x"})["result"]["tag"] == "x" and b.call("gate.who")["result"]["holder"] == "navigator")
    check("an upstream error is relayed as robotd sent it", a.call("robot.fail")["error"] == {"code": -5, "message": "boom"})
    check("an unknown method is robotd's error, not the proxy's", a.call("robot.dance")["error"]["code"] == -32601)
    a.sock.sendall(b"{not json\n")
    check("a bad line is an error reply, and the connection stays", wait_for(lambda: any(n.get("error", {}).get("code") == -32700 for n in a.notes))
          and a.call("gate.who")["result"]["holder"] == "navigator")

    # the subscribe stream
    sa = a.call("robot.subscribe", {"hz": 20})
    sb = b.call("robot.subscribe", {"hz": 10})
    check("robot.subscribe is answered by robotd and relayed", sa["result"]["policy"] == "fake" and sb["result"]["hz"] == 10)
    check("both subscribers get the stream", wait_for(lambda: sum(1 for n in a.notes if n.get("method") == "robot.state") >= 3
                                                      and sum(1 for n in b.notes if n.get("method") == "robot.state") >= 3))
    check("a client that did not subscribe gets none", not any(n.get("method") == "robot.state" for n in anon.notes))
    check("robotd was asked to subscribe once per request, over its one connection", {n for n, m, _ in robotd.calls if m == "robot.subscribe"} == {1})

    def states(c):
        return sum(1 for n in c.notes if n.get("method") == "robot.state")

    def rates(*clients, secs=2.0):
        n0, t0 = [states(c) for c in clients], time.monotonic()
        while time.monotonic() - t0 < secs:
            a.call("gate.keepalive")        # the holder's lease (1.5 s here) outlives the measurement
            time.sleep(0.4)
        dt = time.monotonic() - t0
        return [round((states(c) - n) / dt, 1) for c, n in zip(clients, n0)]

    def upstream_hz():
        return [p.get("hz") for _, m, p in robotd.calls if m == "robot.subscribe"][-1]

    ra, rb = rates(a, b)
    check("must fail: a later, slower subscriber does not slow an earlier one; each gets its own rate (20 and 10 Hz)",
          15 <= ra <= 23 and 7 <= rb <= 12, (ra, rb))
    check("robotd streams at the fastest subscriber's rate", upstream_hz() == 20, upstream_hz())
    b.close()
    seen = states(a)
    check("when a subscriber leaves the other's stream goes on", wait_for(lambda: states(a) > seen + 2))
    e = Client(tmp / "gate.sock", hello="fast-viewer")
    e.call("robot.subscribe", {"hz": 30})
    check("a faster subscriber raises robotd's rate", upstream_hz() == 30, upstream_hz())
    ra, re_ = rates(a, e)
    check("... and the earlier one still gets its own 20 Hz, not more", 15 <= ra <= 23 and 24 <= re_ <= 34, (ra, re_))
    e.close()
    check("when the fastest leaves, robotd goes back to the fastest left (20 Hz)", wait_for(lambda: upstream_hz() == 20), upstream_hz())
    f = Client(tmp / "gate.sock", hello="float-rate")
    asked = sum(1 for _, m, _ in robotd.calls if m == "robot.subscribe")
    for bad in (5.0, 2.5, 0, -1, True, "5"):
        r = f.call("robot.subscribe", {"hz": bad})
        check(f"must fail: hz {bad!r} is refused by the gate in its own words (the operator's decision h), robotd not asked",
              (r.get("error") or {}).get("data", {}).get("gate") == "bad_rate" and "whole number" in r["error"]["message"]
              and sum(1 for _, m, _ in robotd.calls if m == "robot.subscribe") == asked, r)
    check("... and the refused client gets no stream", not any(n.get("method") == "robot.state" for n in f.notes))
    f.close()

    # STOP latches, and the holder is told
    c = Client(tmp / "gate.sock", hello="bystander")
    n_before = len(robotd.calls)
    c.call("robot.stop")
    check("STOP from anyone: robot.stop, then an explicit zero move, upstream",
          [(m, p) for _, m, p in robotd.calls[n_before:]][-2:] == [("robot.stop", {}), ("robot.move", ZERO)], robotd.calls[n_before:])
    check("the holder is told at once: gate.lease_lost", wait_for(lambda: any(n.get("method") == "gate.lease_lost" and n["params"]["reason"] == "stopped_by bystander" for n in a.notes)))
    r = a.call("robot.move", MOVE)
    check("and its next move is refused, with the reason", r["error"]["data"]["gate"] == "lease_ended" and r["error"]["data"]["reason"] == "stopped_by bystander", r)
    check("the robot is free", c.call("gate.who")["result"]["holder"] is None)

    # disconnect frees at once
    check("acquire again clears the latch", a.call("gate.acquire")["result"]["lease_id"] == 2)
    n_before = len(robotd.calls)
    a.close()
    check("a dropped connection stops the robot and frees it", wait_for(lambda: c.call("gate.who")["result"]["holder"] is None)
          and [(m, p) for _, m, p in robotd.calls[n_before:]][-2:] == [("robot.stop", {}), ("robot.move", ZERO)])

    # expiry of a frozen client: the socket stays open, it says nothing
    d = Client(tmp / "gate.sock", hello="frozen")
    d.call("gate.acquire")
    check("a frozen client holds it...", c.call("gate.who")["result"]["holder"] == "frozen")
    check("...until the lease runs out on the gate's own clock", wait_for(lambda: c.call("gate.who")["result"]["holder"] is None, timeout=4.0))
    r = d.call("robot.move", MOVE)
    check("the client that wakes up is refused: its lease expired", r["error"]["data"]["gate"] == "lease_ended" and r["error"]["data"]["reason"] == "expired", r)
    check("it was told when it happened", any(n.get("method") == "gate.lease_lost" and n["params"]["reason"] == "expired" for n in d.notes))

    # takeover by name
    e = Client(tmp / "gate.sock", hello="navigator-2")
    e.call("gate.acquire")
    o = Client(tmp / "gate.sock", hello="operator")
    r = c.call("gate.takeover")
    check("takeover is refused to a name not on the list", r["error"]["data"]["gate"] == "not_allowed")
    r = o.call("gate.takeover")
    check("an owner takes the robot", r["result"]["lease_id"] >= 4 and o.call("gate.who")["result"]["holder"] == "operator")
    check("the old holder is told: taken_over_by operator", wait_for(lambda: any(n.get("method") == "gate.lease_lost" and n["params"]["reason"] == "taken_over_by operator" for n in e.notes)))
    check("the operator drives", o.call("robot.move", MOVE)["result"]["ok"])

    # the log
    lines = [json.loads(l) for l in logfile.read_text().splitlines()]
    events = {x["event"] for x in lines}
    check("the log has connected, acquired, refused, stop, disconnected, expired, taken_over", {"connected", "acquired", "refused", "stop", "disconnected", "expired", "taken_over"} <= events, sorted(events))
    check("a STOP is logged with the connection's name", any(x["event"] == "stop" and x["client"] == "bystander" for x in lines))

    # two gates cannot share a socket; a stale file is taken
    try:
        Proxy(tmp / "gate.sock", tmp / "robotd.sock").start()
        check("a second gate on a live socket is refused", False)
    except RuntimeError as exc:
        check("a second gate on a live socket is refused", "in use" in str(exc))

    # upstream gone
    robotd.close()
    check("with robotd gone the clients are told, and the gate does not die", wait_for(lambda: o.call("robot.state")["error"]["data"]["gate"] == "upstream"))

    for cl in (c, d, e, o, anon):
        cl.close()
    proxy.stop()
    check("stopping the gate removes its socket", not (tmp / "gate.sock").exists())

    # a stale socket file left by a dead gate is replaced
    (tmp / "stale.sock").write_text("")
    robotd2 = FakeRobotd(tmp / "robotd2.sock")
    p2 = Proxy(tmp / "stale.sock", tmp / "robotd2.sock")
    p2.start()
    check("a stale socket file is taken over", Client(tmp / "stale.sock").call("robot.state", {"tag": "t"})["result"]["tag"] == "t")
    p2.stop()
    robotd2.close()

print()
print("GATE PROXY", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
