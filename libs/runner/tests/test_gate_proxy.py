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

import contextlib
import io

from labrunner.gate import Proxy
from labrunner.rpc import Rpc
from robotgate import ProtocolError

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
        self.extra: dict = {}               # merged into every streamed state
        self.hellos: list = []              # the params of every hello, kept out of `calls`: the gate's own, not a client's
        self.hello_api = 61                 # robotd's api_version in the hello reply; None: a v59 robotd, which refuses a named hello
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
                    send({"jsonrpc": "2.0", "method": "robot.state", "params": {"seq": seq, **self.extra}})
                except OSError:
                    return
                time.sleep(1.0 / rate["hz"])

        for line in sock.makefile("r"):
            req = json.loads(line)
            if req["method"] == "hello":
                with self._lock:
                    self.hellos.append(req.get("params"))
                if self.hello_api is None:
                    send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32602, "message": "unknown field `client`"}})
                else:
                    send({"jsonrpc": "2.0", "id": req["id"], "result": {"api_version": self.hello_api, "daemon_version": "0.61.0"}})
                continue
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
    check("must fail: hello, gate.who and gate.acquire's refusal say the gate protocol, 1 (RFC-0018 §5.3)",
          a.call("hello", {"client": "x"})["result"].get("protocol") == 1 and b.call("gate.who")["result"].get("protocol") == 1
          and r["error"]["data"].get("protocol") == 1, (a.replies, r))
    check("a robot's own reply carries none: robotd's, as it sent it", "protocol" not in b.call("robot.state", {"tag": "x"})["result"])
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

    # a client's first message reads the protocol: this one's gate, a gate with no number, a gate from the future
    def fake_gate(path, hello_result):
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(str(path))
        srv.listen(2)

        def serve():
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                for line in conn.makefile("r"):
                    conn.sendall((json.dumps({"jsonrpc": "2.0", "id": json.loads(line)["id"], "result": hello_result}) + "\n").encode())
        threading.Thread(target=serve, daemon=True).start()
        return srv

    def connect(path):
        try:
            Rpc(path, client="runner").close()
            return None
        except ProtocolError as exc:
            return exc

    check("a client of a gate that speaks this protocol connects", connect(tmp / "gate.sock") is None)
    old_gate = fake_gate(tmp / "old.sock", {"gate": True, "client": "runner"})
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        first, second = connect(tmp / "old.sock"), connect(tmp / "old.sock")
    check("must fail: a gate that names no protocol is read as 0 and accepted, with one warning for the process",
          first is None and second is None and err.getvalue().count("gate protocol") == 1, err.getvalue())
    new_gate = fake_gate(tmp / "new.sock", {"gate": True, "client": "runner", "protocol": 2})
    refused = connect(tmp / "new.sock")
    check("must fail: a gate that speaks a newer protocol is refused, both numbers said", refused is not None and "2" in str(refused)
          and "1" in str(refused), refused)
    old_gate.close()
    new_gate.close()
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

    # the other doors (RFC-0017 §3.8): a state frame that shows autonomous reaches the gate through the proxy
    robotd3 = FakeRobotd(tmp / "robotd3.sock")
    p3log = tmp / "gate3.jsonl"
    p3 = Proxy(tmp / "gate3.sock", tmp / "robotd3.sock", log=p3log, own_sources={"gate-proxy"})
    p3.start()
    drv, watcher = Client(tmp / "gate3.sock", hello="navigator"), Client(tmp / "gate3.sock", hello="viewer")
    drv.call("gate.acquire")
    drv.call("robot.move", MOVE)
    watcher.call("robot.subscribe", {"hz": 20})
    time.sleep(0.5)
    p3_events = lambda: [json.loads(x)["event"] for x in p3log.read_text().splitlines()] if p3log.exists() else []
    check("normal frames (nothing filled) leave the holder driving, and the watch says once it does not watch",
          drv.call("gate.who")["result"]["holder"] == "navigator" and p3_events().count("not_watched") == 1
          and "someone_else_drives" not in p3_events(), p3_events())
    robotd3.extra = {"autonomous": True}
    check("a state frame with autonomous true ends the lease and is logged",
          wait_for(lambda: drv.call("gate.who")["result"]["holder"] is None) and "someone_else_drives" in p3_events(), p3_events())
    check("... the robot was stopped upstream, then a zero move", ("robot.stop" in robotd3.methods())
          and [c for c in robotd3.calls if c[1] == "robot.move"][-1][2] == ZERO, robotd3.calls[-4:])
    check("... the holder got lease_lost and every client the someone_else_drives event",
          wait_for(lambda: any(n.get("method") == "gate.lease_lost" and n["params"]["reason"] == "someone_else_drives" for n in drv.notes))
          and wait_for(lambda: any(n.get("method") == "gate.someone_else_drives" for n in watcher.notes)), drv.notes[-3:])
    p3.stop()
    check("a stopped gate's threads have ended, so nothing writes its log afterwards",
          not [t.name for t in p3.threads() if t.is_alive()], [t.name for t in p3.threads() if t.is_alive()])
    robotd3.close()

    # the gate names itself to robotd (protocol v60): move.source then says who moved the robot, and an absent autonomous means false
    def events_of(path):
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    robotd4 = FakeRobotd(tmp / "robotd4.sock")
    p4log = tmp / "gate4.jsonl"
    p4 = Proxy(tmp / "gate4.sock", tmp / "robotd4.sock", log=p4log, own_sources={"extra-name"})
    check("the proxy says hello {client} upstream right after connecting, under its default name",
          robotd4.hellos == [{"client": "robotics-lab-gate"}] and robotd4.methods() == [], robotd4.hellos)
    check("... the name joins own_sources next to --own-source, and a v61 robotd turns on omits_false_autonomous",
          p4.gate.own_sources == {"robotics-lab-gate", "extra-name"} and p4.gate.omits_false_autonomous is True, p4.gate.own_sources)
    hello4 = [e for e in events_of(p4log) if e["event"] == "upstream_hello"]
    check("... one gate-log entry says what the hello returned", len(hello4) == 1 and hello4[0]["api_version"] == 61
          and hello4[0]["daemon_version"] == "0.61.0" and hello4[0]["client"] == "robotics-lab-gate", hello4)
    p4.start()
    robotd4.extra = {"move": {"applied": [0.0, 0.0, 0.0], "source": "robotics-lab-gate"}}
    watcher4 = Client(tmp / "gate4.sock", hello="viewer")
    watcher4.call("robot.subscribe", {"hz": 20})
    time.sleep(0.5)
    check("a Pollen-shaped frame (no autonomous, applied an array, our source) is watched and raises nothing",
          "someone_else_drives" not in [e["event"] for e in events_of(p4log)]
          and not any("autonomous" in e.get("fields", ()) or "move.applied" in e.get("fields", ()) for e in events_of(p4log) if e["event"] == "not_watched"),
          events_of(p4log))
    robotd4.extra = {"move": {"applied": [0.3, 0.0, 0.0], "source": "robotics-lab-gate"}}
    check("... and an applied array with motion and no lease is someone else",
          wait_for(lambda: any(e["event"] == "someone_else_drives" and e["signal"] == "motion_without_lease" for e in events_of(p4log))),
          events_of(p4log))
    watcher4.close()
    p4.stop()
    robotd4.close()

    robotd5 = FakeRobotd(tmp / "robotd5.sock")
    p5 = Proxy(tmp / "gate5.sock", tmp / "robotd5.sock", client_name="lab-gate-2")
    check("a --client-name changes the name sent and trusted", robotd5.hellos == [{"client": "lab-gate-2"}] and p5.gate.own_sources == {"lab-gate-2"}, robotd5.hellos)
    p5.stop()
    robotd5.close()

    robotd6 = FakeRobotd(tmp / "robotd6.sock")
    robotd6.hello_api = 59
    p6 = Proxy(tmp / "gate6.sock", tmp / "robotd6.sock")
    check("a robotd that answers with api_version below 60 leaves omits_false_autonomous off", p6.gate.omits_false_autonomous is False)
    p6.stop()
    robotd6.close()

    robotd7 = FakeRobotd(tmp / "robotd7.sock")
    robotd7.hello_api = None
    p7log = tmp / "gate7.jsonl"
    p7 = Proxy(tmp / "gate7.sock", tmp / "robotd7.sock", log=p7log, own_sources={"extra-name"})
    refused7 = [e for e in events_of(p7log) if e["event"] == "upstream_hello_refused"]
    check("a robotd that refuses the named hello (v59: INVALID_PARAMS) is logged once and the proxy goes on without the name",
          len(refused7) == 1 and refused7[0]["client"] == "robotics-lab-gate" and "unknown field" in refused7[0]["error"]
          and p7.gate.own_sources == {"extra-name"} and p7.gate.omits_false_autonomous is False and p7.upstream.alive, events_of(p7log))
    p7.start()
    check("... and still relays", Client(tmp / "gate7.sock").call("robot.state", {"tag": "v59"})["result"]["tag"] == "v59")
    p7.stop()
    robotd7.close()

print()
print("GATE PROXY", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
