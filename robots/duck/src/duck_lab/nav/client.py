"""JSON-RPC 2.0 over the duck's Unix sockets (RFC-0003): robotd and mapd. The same code drives the
simulator (~/.cache/duck-sim/*.sock) and, through ssh-forwarded sockets, the real duck (RFC-0002 §3.3)."""

import json
import os
import socket
import threading
from pathlib import Path

SIM = Path(os.path.expanduser("~/.cache/duck-sim"))
GATE_LEASE_CODES = ("lease_ended", "held", "no_lease")


class LeaseLost(RuntimeError):
    """The gate (RFC-0017) refused a command because this client has no lease: it ended (`lease_ended`, with `reason`:
    expired, stopped_by <who>, taken_over_by <who>, released), another client holds the robot (`held`) or it was never
    acquired (`no_lease`). A navigator that gets this stops: the robot is already stopped, by the gate."""

    def __init__(self, message: str, code: str, reason: str | None = None, holder: str | None = None):
        super().__init__(message)
        self.code, self.reason, self.holder = code, reason, holder


class Rpc:
    """Request/response on one socket. Not for streams. With `client`, the first message is hello {client} (the name a gate
    knows this connection by); the robot's own socket has no gate and never needs it."""

    def __init__(self, path: Path, timeout: float = 5.0, client: str | None = None):
        self._sock = socket.socket(socket.AF_UNIX)
        self._sock.settimeout(timeout)
        self._sock.connect(str(path))
        self._f = self._sock.makefile("rw")
        self._id = 0
        self._lock = threading.Lock()
        if client:
            self.call("hello", {"client": client})

    def call(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            self._id += 1
            req = {"jsonrpc": "2.0", "id": self._id, "method": method}
            if params is not None:
                req["params"] = params
            self._f.write(json.dumps(req) + "\n")
            self._f.flush()
            while True:
                msg = json.loads(self._f.readline())
                if msg.get("id") == self._id:
                    break
        if "error" in msg:
            data = (msg["error"].get("data") or {}) if isinstance(msg["error"], dict) else {}
            if data.get("gate") in GATE_LEASE_CODES:
                raise LeaseLost(f"{method}: {msg['error'].get('message')}", data["gate"], data.get("reason"), data.get("holder"))
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    def close(self) -> None:
        self._sock.close()


class StateStream:
    """robot.subscribe in a thread; keeps the latest robot.state and calls on_state for each."""

    def __init__(self, path: Path, hz: int = 20, on_state=None, client: str | None = None):
        self.latest = None
        self._on_state = on_state
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_UNIX)
        self._sock.connect(str(path))
        self._sock.settimeout(1.0)
        f = self._sock.makefile("rw")
        if client:
            f.write(json.dumps({"jsonrpc": "2.0", "id": 0, "method": "hello", "params": {"client": client}}) + "\n")
        f.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "robot.subscribe", "params": {"hz": hz}}) + "\n")
        f.flush()
        self._f = f
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                line = self._f.readline()
            except (TimeoutError, socket.timeout):
                continue
            if not line:
                return
            msg = json.loads(line)
            if msg.get("method") == "robot.state":
                self.latest = msg["params"]
                if self._on_state:
                    self._on_state(self.latest)

    def close(self) -> None:
        self._stop.set()
        self._sock.close()


def odom_pose(state: dict) -> tuple:
    o = state["odom"]
    return o["position"][0], o["position"][1], o["yaw"]
