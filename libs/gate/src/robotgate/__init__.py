"""The gate (RFC-0017): one driver per robot. Pure rules, no sockets: a transport (the simulator's
socket proxy, the fake robot) opens a connection per client, hands each JSON-RPC call to `handle`,
and calls `tick` on a timer. Stdlib only.

The lease belongs to the connection that acquired it. It ends on release, expiry (silence), a STOP,
a takeover or the connection closing; every end stops the robot first (RFC-0017 §3.4).

The gate protocol has a number (RFC-0018 §5.3), `PROTOCOL`: it is `protocol` in `gate.who`, in every other `gate.*` reply, in a
refusal's data and in a transport's answer to `hello`. A robot's own replies (`robot.*`) are the robot's and carry none. A client
reads it with `check_protocol`: a missing number is 0 (a gate before the number), accepted with one warning; a newer one is refused."""

import json
import sys
import threading
import time
from pathlib import Path

PROTOCOL = 1
LEASE_SECONDS = 20.0  # RFC-0017 §3.3: 10 to 30 s, not the deadman's 0.5 s

# Reading and the deadman-free methods pass without a lease. Anything else, an unknown method
# included, needs the lease: no lease, no motion.
OPEN_METHODS = frozenset({"robot.state", "robot.subscribe", "robot.health", "tof.frame"})
STOP_METHOD = "robot.stop"
ZERO_MOVE = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}


class GateError(Exception):
    """A refusal. `code` is for programs, the message for people; `data` rides on the reply."""

    def __init__(self, code: str, message: str, **data):
        super().__init__(message)
        self.code = code
        self.data = data

    def to_rpc(self) -> dict:
        return {"code": -32000, "message": str(self), "data": {"gate": self.code, "protocol": PROTOCOL, **self.data}}


class ProtocolError(RuntimeError):
    """A gate speaks a protocol this side does not."""


_warned = False


def check_protocol(reply, peer: str = "the gate") -> int:
    """The protocol a gate's reply says (`protocol`), for a client to read at its first one (hello). Missing: 0, accepted, said once
    per process on stderr. Newer than PROTOCOL, or not a whole number: ProtocolError naming both."""
    global _warned
    n = reply.get("protocol") if isinstance(reply, dict) else None
    if n is None:
        if not _warned:
            _warned = True
            print(f"warning: {peer} names no gate protocol (read as 0); this side speaks {PROTOCOL}", file=sys.stderr)
        return 0
    if not isinstance(n, int) or isinstance(n, bool) or n > PROTOCOL:
        raise ProtocolError(f"{peer} speaks gate protocol {n!r}; this side speaks {PROTOCOL}: update this side")
    return n


class JsonlLog:
    """RFC-0017 §3.6: one line per event, appended beside the gate's config."""

    def __init__(self, path: Path, wall=time.time):
        self.path = Path(path)
        self._wall = wall
        self._lock = threading.Lock()

    def __call__(self, entry: dict) -> None:
        line = json.dumps({"at": round(self._wall(), 3), **entry})
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(line + "\n")


def load_names(path: Path) -> frozenset:
    """The takeover list (RFC-0017 §8 question 1): one client name per line; blank lines and
    # comments are skipped. A missing file is an empty list: nobody may take over."""
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return frozenset()
    names = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return frozenset(n for n in names if n)


class _Conn:
    def __init__(self, cid: int, client: str, notify):
        self.cid = cid
        self.client = client
        self.notify = notify
        self.ended = None  # why this connection's last lease ended, until it acquires again


class Gate:
    """`robot` is a callable robot(method, params) -> result that reaches the robot's own
    interface. `notify` callbacks given to `open` run under the gate's lock: they must not block
    and must not call back into the gate."""

    def __init__(self, robot, *, clock=time.monotonic, wall=time.time, lease_s: float = LEASE_SECONDS,
                 takeover_names=(), log=None):
        self._robot = robot
        self._clock = clock
        self._wall = wall
        self.lease_s = lease_s
        self.takeover_names = frozenset(takeover_names)
        self._log = log or (lambda entry: None)
        self._lock = threading.RLock()
        self._conns: dict[int, _Conn] = {}
        self._next_cid = 0
        self._lease_id = 0
        self._holder: _Conn | None = None
        self._since_wall = 0.0
        self._renewed = 0.0

    # --- connections -------------------------------------------------------------------------

    def open(self, client: str, notify=None) -> int:
        """A client's first message, hello {client}. Returns the connection id."""
        with self._lock:
            self._next_cid += 1
            conn = _Conn(self._next_cid, client, notify or (lambda method, params: None))
            self._conns[conn.cid] = conn
            return conn.cid

    def close(self, cid: int) -> None:
        """The connection is gone: if it held the robot, stop it and free it at once."""
        with self._lock:
            conn = self._conns.pop(cid, None)
            if conn is not None and self._holder is conn:
                self._end("disconnected", conn, f"disconnect of {conn.client}", notify=False)

    def tick(self) -> None:
        """Expire a holder that has been silent too long. A transport calls this on a timer."""
        with self._lock:
            holder = self._holder
            if holder is not None and self._clock() - self._renewed > self.lease_s:
                self._end("expired", holder, f"no command for {self.lease_s:g} s")

    # --- calls -------------------------------------------------------------------------------

    def handle(self, cid: int, method: str, params: dict | None = None):
        """One JSON-RPC call from a connection. Returns the result or raises GateError."""
        params = params or {}
        with self._lock:
            conn = self._conns.get(cid)
            if conn is None:
                raise GateError("unknown_connection", "this connection is closed")
            self.tick()
            if method.startswith("gate."):
                return self._gate_call(conn, method, params)
            if method == STOP_METHOD:
                return self._stop_from(conn)
            if method in OPEN_METHODS:
                return self._robot(method, params)
            self._require_lease(conn, method)
            self._renewed = self._clock()
            return self._robot(method, params)

    def _gate_call(self, conn: _Conn, method: str, params: dict):
        return {"protocol": PROTOCOL, **self._gate_reply(conn, method)}

    def _gate_reply(self, conn: _Conn, method: str) -> dict:
        if method == "gate.who":
            return self.who()
        if method == "gate.acquire":
            return self._acquire(conn)
        if method == "gate.release":
            return self._release(conn)
        if method == "gate.keepalive":
            self._require_lease(conn, method)
            self._renewed = self._clock()
            return {"lease_id": self._lease_id, "expires_in_s": self.lease_s}
        if method == "gate.takeover":
            return self._takeover(conn)
        raise GateError("unknown_method", f"the gate has no method {method}")

    def who(self) -> dict:
        with self._lock:
            self.tick()
            holder = self._holder
            if holder is None:
                return {"protocol": PROTOCOL, "holder": None, "lease_id": self._lease_id}
            return {"protocol": PROTOCOL, "holder": holder.client, "since": self._since_wall, "lease_id": self._lease_id,
                    "expires_in_s": round(max(0.0, self.lease_s - (self._clock() - self._renewed)), 3)}

    # --- the rules ---------------------------------------------------------------------------

    def _acquire(self, conn: _Conn) -> dict:
        if self._holder is conn:
            self._renewed = self._clock()
            return self._lease_reply()
        if self._holder is not None:
            self._log({"event": "refused", "client": conn.client, "why": "held", "holder": self._holder.client})
            raise GateError("held", f"driven by {self._holder.client} since {self._since_text()}",
                            holder=self._holder.client, since=self._since_wall)
        self._grant(conn)
        return self._lease_reply()

    def _release(self, conn: _Conn) -> dict:
        if self._holder is not conn:
            raise GateError("not_holder", "this connection does not hold the robot")
        self._end("released", conn, f"released by {conn.client}", notify=False)
        return {"ok": True}

    def _takeover(self, conn: _Conn) -> dict:
        if conn.client not in self.takeover_names:
            self._log({"event": "refused", "client": conn.client, "why": "takeover_not_allowed"})
            raise GateError("not_allowed", f"{conn.client} is not on the takeover list")
        if self._holder is conn:
            self._renewed = self._clock()
            return self._lease_reply()
        old = self._holder
        if old is not None:
            self._end(f"taken_over_by {conn.client}", old, f"taken over by {conn.client}", event="taken_over",
                      by=conn.client)
        self._grant(conn)
        return self._lease_reply()

    def _stop_from(self, conn: _Conn):
        """STOP from any connection, with or without a lease, and it latches (RFC-0017 §3.4)."""
        self._log({"event": "stop", "client": conn.client})
        holder = self._holder
        if holder is not None:
            self._end(f"stopped_by {conn.client}", holder, f"stopped by {conn.client}", event="lease_ended",
                      by=conn.client)
            return {"ok": True}
        return self._gate_stop()

    def _require_lease(self, conn: _Conn, method: str) -> None:
        if self._holder is conn:
            return
        if conn.ended is not None:
            raise GateError("lease_ended", f"your lease ended: {conn.ended}; acquire again", reason=conn.ended)
        if self._holder is not None:
            raise GateError("held", f"driven by {self._holder.client} since {self._since_text()}",
                            holder=self._holder.client, since=self._since_wall)
        raise GateError("no_lease", f"{method} needs the lease: gate.acquire first")

    def _grant(self, conn: _Conn) -> None:
        self._lease_id += 1
        self._holder = conn
        self._since_wall = self._wall()
        self._renewed = self._clock()
        conn.ended = None
        self._log({"event": "acquired", "client": conn.client, "lease_id": self._lease_id})

    def _end(self, reason: str, conn: _Conn, text: str, *, notify: bool = True, event: str | None = None, **extra) -> None:
        """Every end of a lease: stop the robot first, then free it, record it, tell the holder."""
        self._gate_stop()
        self._holder = None
        conn.ended = reason
        self._log({"event": event or reason.split()[0], "client": conn.client, "lease_id": self._lease_id,
                   "why": text, **extra})
        if notify:
            conn.notify("lease_lost", {"lease_id": self._lease_id, "reason": reason})

    def _gate_stop(self):
        """robot.stop, then an explicit zero move: robotd keeps its last request after the deadman
        fired and mapd would never see a stop (RFC-0017 §3.4). A failing robot must not keep the
        lease alive, so each call is tried and a failure is logged."""
        result = None
        for method, params in ((STOP_METHOD, {}), ("robot.move", ZERO_MOVE)):
            try:
                reply = self._robot(method, params)
                result = reply if method == STOP_METHOD else result
            except Exception as exc:
                self._log({"event": "stop_failed", "method": method, "error": f"{type(exc).__name__}: {exc}"})
        return result if result is not None else {}

    def _lease_reply(self) -> dict:
        return {"lease_id": self._lease_id, "expires_in_s": self.lease_s}

    def _since_text(self) -> str:
        return time.strftime("%H:%M", time.localtime(self._since_wall))
