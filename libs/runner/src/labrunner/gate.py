"""The gate in front of a robot's socket (RFC-0017 §3.2, §5 step 3): a Unix-socket proxy that puts `robotgate.Gate`
between our clients (the navigator, Mission Control, a script) and the robot's one connection (RFC-0003 JSON-RPC on a
unix socket: robotd for the duck).

    lab-gate                      # listen on the host file's gate socket, upstream its robot socket (RFC-0021)
    lab-gate --listen /tmp/gate.sock --upstream /run/robotd.sock

One Gate, one upstream connection. The clients speak robotd's JSON-RPC (newline-framed, RFC-0003) and the gate's own
methods (gate.acquire, gate.release, gate.who, gate.keepalive, gate.takeover). The proxy gives each request its own id
upstream and routes the reply back under the client's id, so two clients that both use id 1 do not meet. A client's first
message may be `hello {client}`: the name it is known by in the lease and the log (answered here, not sent upstream);
without one it is `anonymous-N`. `robot.subscribe` is relayed: robotd streams `robot.state` to the one upstream
connection and the proxy copies each notification to every client that subscribed, dropping the oldest when a client is
slow (robotd's own rule: a gap, never backpressure). robotd streams one connection at its last subscribe's rate, so the
proxy subscribes upstream at the fastest rate any subscriber asked for (again when the fastest leaves) and gives each
subscriber its own rate: a client that subscribes later and slower never slows another's stream (sim_duck 2026-11-22: the
navigator got Mission Control's 5 Hz).

The gate is the one door for OUR clients, not a security boundary (RFC-0017 §3.2): the simulator's socket is a plain file.
It never resends a command and never holds the last one; a lease that ends stops the robot (Gate does that)."""

import argparse
import json
import os
import queue
import signal
import socket
import threading
import time
from pathlib import Path

from robotgate import LEASE_SECONDS, Gate, GateError, JsonlLog, load_names

TICK_S = 0.25
RATE_SLACK = 0.25     # a state up to a quarter period early still counts as due: robotd's jitter never drops one
OUT_QUEUE = 256            # lines waiting for one client; past it the oldest notification goes
UPSTREAM_TIMEOUT_S = 5.0


class UpstreamError(Exception):
    """robotd answered with a JSON-RPC error: `error` is its object, relayed to the client as it is."""

    def __init__(self, error: dict):
        super().__init__(str(error.get("message", error)))
        self.error = error


class Upstream:
    """The one connection to robotd. Ids are the proxy's; a reply wakes the call that waits for it; a message with no id
    is a notification and goes to `on_notification`."""

    def __init__(self, path: Path, on_notification, timeout_s: float = UPSTREAM_TIMEOUT_S):
        self.timeout_s = timeout_s
        self._sock = socket.socket(socket.AF_UNIX)
        self._sock.connect(str(path))
        self._rfile = self._sock.makefile("r")
        self._send_lock = threading.Lock()
        self._pending: dict = {}
        self._id = 0
        self._on_notification = on_notification
        self.alive = True
        threading.Thread(target=self._read, name="gate-upstream", daemon=True).start()

    def _read(self) -> None:
        try:
            for line in self._rfile:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mid = msg.get("id")
                if mid is not None and mid in self._pending:
                    event, box = self._pending[mid]
                    box.update(msg)
                    event.set()
                elif mid is None and "method" in msg:
                    self._on_notification(msg)
        except (OSError, ValueError):
            pass
        finally:
            self.alive = False
            for event, box in list(self._pending.values()):
                box.setdefault("error", {"code": -32000, "message": "the upstream connection closed"})
                event.set()

    def call(self, method: str, params: dict | None = None):
        if not self.alive:
            raise ConnectionError("the upstream connection is closed")
        event, box = threading.Event(), {}
        with self._send_lock:
            self._id += 1
            mid = self._id
            self._pending[mid] = (event, box)
            req = {"jsonrpc": "2.0", "id": mid, "method": method}
            if params is not None:
                req["params"] = params
            try:
                self._sock.sendall((json.dumps(req) + "\n").encode())
            except OSError as exc:
                self._pending.pop(mid, None)
                raise ConnectionError(f"the upstream connection failed: {exc}") from None
        if not event.wait(self.timeout_s):
            self._pending.pop(mid, None)
            raise TimeoutError(f"{method}: no answer from robotd in {self.timeout_s:g} s")
        self._pending.pop(mid, None)
        if "error" in box:
            raise UpstreamError(box["error"])
        return box.get("result", {})

    def close(self) -> None:
        self.alive = False
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()


class _Client:
    """One connection of a client: a reader loop, a writer thread with a bounded queue."""

    def __init__(self, proxy: "Proxy", sock: socket.socket, n: int):
        self.proxy, self.sock, self.n = proxy, sock, n
        self.cid = None
        self.name = f"anonymous-{n}"
        self.subscribed = False
        self.next_state = 0.0               # when its next robot.state is due (its own rate)
        self.out: queue.Queue = queue.Queue(OUT_QUEUE)
        self.closed = threading.Event()

    def send(self, msg: dict, droppable: bool = False) -> None:
        line = (json.dumps(msg) + "\n").encode()
        while True:
            try:
                self.out.put_nowait(line)
                return
            except queue.Full:
                if not droppable:
                    try:
                        self.out.get_nowait()          # a reply is worth more than the oldest line
                    except queue.Empty:
                        pass
                    continue
                try:
                    self.out.get_nowait()
                except queue.Empty:
                    pass

    def _write(self) -> None:
        while not self.closed.is_set():
            try:
                line = self.out.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.sock.sendall(line)
            except OSError:
                self.closed.set()
                return

    def _lease_lost(self, method: str, params: dict) -> None:
        # runs under the gate's lock: only queue, never block, never call the gate
        self.send({"jsonrpc": "2.0", "method": "gate." + method, "params": params})

    def _ensure_open(self, name: str | None = None) -> None:
        if self.cid is None:
            if name:
                self.name = name
            self.cid = self.proxy.gate.open(self.name, self._lease_lost)
            self.proxy.log({"event": "connected", "client": self.name})

    def run(self) -> None:
        threading.Thread(target=self._write, name=f"gate-w{self.n}", daemon=True).start()
        try:
            with self.sock.makefile("r") as rfile:
                for line in rfile:
                    line = line.strip()
                    if line:
                        self._handle(line)
        except (OSError, ValueError):
            pass
        finally:
            self.closed.set()
            self.proxy._drop(self)
            if self.cid is not None:
                self.proxy.gate.close(self.cid)
                self.proxy.log({"event": "disconnected", "client": self.name})
            try:
                self.sock.close()
            except OSError:
                pass

    def _handle(self, line: str) -> None:
        try:
            req = json.loads(line)
            method, rid = req["method"], req.get("id")
            params = req.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"bad request: {exc}"}})
            return
        if method == "hello":
            name = params.get("client")
            if self.cid is None and isinstance(name, str) and name.strip():
                self._ensure_open(name.strip())
            else:
                self._ensure_open()
            self.send({"jsonrpc": "2.0", "id": rid, "result": {"gate": True, "client": self.name}})
            return
        self._ensure_open()
        try:
            if method == "robot.subscribe":
                result = self.proxy.subscribe(self, params)
                self.subscribed = True
            else:
                result = self.proxy.gate.handle(self.cid, method, params)
        except GateError as exc:
            self.send({"jsonrpc": "2.0", "id": rid, "error": exc.to_rpc()})
            return
        except UpstreamError as exc:
            self.send({"jsonrpc": "2.0", "id": rid, "error": exc.error})
            return
        except (ConnectionError, TimeoutError) as exc:
            self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(exc), "data": {"gate": "upstream"}}})
            return
        except Exception as exc:                                       # noqa: BLE001 - a bug must not drop the connection
            self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}})
            return
        if rid is not None:
            self.send({"jsonrpc": "2.0", "id": rid, "result": result})


class Proxy:
    def __init__(self, listen: Path, upstream: Path, *, takeover_names=(), log: Path | None = None,
                 lease_s: float = LEASE_SECONDS, upstream_timeout_s: float = UPSTREAM_TIMEOUT_S):
        self.listen, self.upstream_path = Path(listen), Path(upstream)
        self._log = JsonlLog(log) if log else (lambda entry: None)
        self.upstream = Upstream(self.upstream_path, self._on_notification, upstream_timeout_s)
        self.gate = Gate(self.upstream.call, lease_s=lease_s, takeover_names=takeover_names, log=self.log)
        self._clients: list = []
        self._subscribers: list = []
        self._rates: dict = {}              # subscriber -> the rate it asked for (None: robotd's own)
        self._asked = None                  # the rate robotd was last asked for
        self._sub_lock = threading.Lock()   # one subscribe change at a time: robotd's last subscribe is the fastest
        self._lock = threading.Lock()
        self._n = 0
        self._stop = threading.Event()
        self._server = None

    def log(self, entry: dict) -> None:
        self._log(entry)

    def _on_notification(self, msg: dict) -> None:
        now = time.monotonic()
        with self._lock:
            targets = [(c, self._rates.get(c)) for c in self._subscribers]
        for c, hz in targets:
            if hz:
                period = 1.0 / hz
                if now < c.next_state - RATE_SLACK * period:
                    continue                # not due yet: this subscriber's own rate, not the fastest's
                # the next due time runs on by whole periods (30 Hz to 20 sends two in three), never far behind now
                c.next_state = max(c.next_state + period, now - period)
            c.send(msg, droppable=True)

    @staticmethod
    def _fastest(rates) -> float | None:
        """The rate robotd is asked for: the fastest asked, or robotd's own (None) when a subscriber asked for none."""
        rates = list(rates)
        return None if not rates or any(r is None for r in rates) else max(rates)

    def subscribe(self, client: _Client, params: dict):
        """A client's robot.subscribe: robotd is asked for the fastest rate of all subscribers (through the gate, its rules),
        the client streamed at its own. Serialised, so robotd's last subscribe is always the fastest."""
        hz = params.get("hz")
        # kept as the client gave it: robotd takes an integer rate and refuses 5.0 (invalid type ... expected u32)
        rate = hz if isinstance(hz, (int, float)) and not isinstance(hz, bool) and hz > 0 else None
        with self._sub_lock:
            with self._lock:
                others = [r for c, r in self._rates.items() if c is not client]
            want = self._fastest(others + [rate])
            upstream = {k: v for k, v in params.items() if k != "hz"}
            if want is not None:
                upstream["hz"] = want
            result = self.gate.handle(client.cid, "robot.subscribe", upstream)
            with self._lock:
                self._rates[client] = rate
                if client not in self._subscribers:
                    self._subscribers.append(client)
                self._asked = want
        if isinstance(result, dict) and "hz" in result:
            result = {**result, "hz": hz}       # the rate this client is streamed at
        return result

    def _drop(self, client: _Client) -> None:
        with self._sub_lock:
            with self._lock:
                if client in self._subscribers:
                    self._subscribers.remove(client)
                if client in self._clients:
                    self._clients.remove(client)
                self._rates.pop(client, None)
                want = self._fastest(self._rates.values())
                slower = bool(self._rates) and want != self._asked
            if slower:
                try:                        # the fastest left: robotd slowed to the fastest left, so no stream is sent unread
                    self.upstream.call("robot.subscribe", {"hz": want} if want is not None else {})
                    with self._lock:
                        self._asked = want
                except (ConnectionError, TimeoutError, UpstreamError):
                    pass

    def start(self) -> None:
        """Bind the listening socket and serve in threads. A socket file that something still answers on is not taken."""
        if self.listen.exists():
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.connect(str(self.listen))
                raise RuntimeError(f"{self.listen} is in use: another gate answers on it")
            except (ConnectionRefusedError, FileNotFoundError):
                self.listen.unlink(missing_ok=True)
            finally:
                probe.close()
        self.listen.parent.mkdir(parents=True, exist_ok=True)
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(str(self.listen))
        os.chmod(self.listen, 0o660)
        self._server.listen(16)
        self._server.settimeout(0.5)
        threading.Thread(target=self._accept, name="gate-accept", daemon=True).start()
        threading.Thread(target=self._tick, name="gate-tick", daemon=True).start()

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                sock, _ = self._server.accept()
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                return
            self._n += 1
            c = _Client(self, sock, self._n)
            with self._lock:
                self._clients.append(c)
            threading.Thread(target=c.run, name=f"gate-c{self._n}", daemon=True).start()

    def _tick(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                self.gate.tick()
            except Exception as exc:                                   # noqa: BLE001
                self.log({"event": "tick_failed", "error": f"{type(exc).__name__}: {exc}"})

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            try:
                c.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._server is not None:
            self._server.close()
        self.listen.unlink(missing_ok=True)
        self.upstream.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", help="the host file (RFC-0021; default $ROBOTICS_LAB_HOST, else ~/.config/robotics-lab/host.json)")
    ap.add_argument("--listen", type=Path, help="the gate's socket: what our clients connect to (default: the host file's gate)")
    ap.add_argument("--upstream", type=Path, help="robotd's socket (default: the host file's robot)")
    ap.add_argument("--takeover-names", type=Path, help="file of client names that may take the robot from its holder, one per line")
    ap.add_argument("--log", type=Path, help="the gate's jsonl log (RFC-0017 §3.6)")
    ap.add_argument("--lease-s", type=float, default=LEASE_SECONDS, help="the lease: 10 to 30 s (RFC-0017 §3.3)")
    args = ap.parse_args()
    if args.listen is None or args.upstream is None:
        import simhost
        sim = simhost.load(args.host)
        args.listen = args.listen or sim.sockets["gate"]
        args.upstream = args.upstream or sim.sockets["robot"]
    proxy = Proxy(args.listen, args.upstream, takeover_names=load_names(args.takeover_names) if args.takeover_names else (),
                  log=args.log, lease_s=args.lease_s)
    proxy.start()
    print(f"lab-gate: {args.listen} -> {args.upstream}", flush=True)
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    try:
        while not done.wait(1.0):
            if not proxy.upstream.alive:
                print("lab-gate: the robot's socket closed the connection", flush=True)
                break
    finally:
        proxy.stop()


if __name__ == "__main__":
    main()
