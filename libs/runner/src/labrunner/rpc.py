"""JSON-RPC 2.0 over a unix socket, newline framed (RFC-0003): the runner's client for a payload, a navigator API, a robot's
socket or a gate. The same shape as the navigator's own client (duck_lab.nav.client), kept here so the runner imports no
robot's package (RFC-0022)."""

import json
import socket
import threading
from pathlib import Path

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

