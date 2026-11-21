"""The simulated duck (RFC-0014 §3.7, step 2): Mission Control's adapter over the two processes that stand in front of it.

- **duck-gate** (RFC-0017): every command to the robot passes this process. Mission Control is one of its clients, as
  `mission-control`; `RemoteGate` gives Mission Control's robot runtime the interface of an in-process `robotgate.Gate`
  over the gate's socket, one connection per client, so the lock, STOP and takeover are the gate's own and Mission Control
  keeps no second copy.
- **duck-nav-server** (O22, `duck_lab.nav.server`): the real navigator as its own process. `DuckNavigatorClient` is the
  navigator API of §3.7 for the goal runs: goal.start, goal.status, goal.cancel. The server holds the lease while a run
  moves the robot and writes the Observatory run; Mission Control only starts, watches and cancels.

robotd has no `robot.state` request, only the `robot.subscribe` stream: the adapter keeps one subscription through the
gate and answers `robot.state` from it, in the shape the page expects (pose in the site frame, mode, flags)."""

import json
import socket
import threading
import time
from pathlib import Path

from robotgate import GateError
from duck_lab.nav.client import StateStream
from duck_lab.nav.run import load_scale

from .errors import ApiError

GATE_NAME = "mission-control"
STATE_STALE_S = 2.0
HEALTH_EVERY_S = 10.0
CALL_TIMEOUT_S = 5.0
TERMINAL = ("reached", "done", "refused", "failed", "stopped_by_guardrail", "not_found", "cancelled", "interrupted")
POLL_EVERY_S = 0.2
FAILS_BEFORE_LOST = 15      # polls in a row that fail before the navigator is called gone (3 s)


def _addr(text: str) -> Path:
    return Path(text).expanduser()


class _Wire:
    """One connection to the gate: hello, requests with answers, and the gate's `gate.lease_lost` notifications."""

    def __init__(self, path: Path, client: str, notify=None):
        self.client, self.notify = client, notify
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(CALL_TIMEOUT_S)
        self.sock.connect(str(path))
        self.sock.settimeout(None)
        self._rfile = self.sock.makefile("r")
        self._lock = threading.Lock()
        self._pending: dict = {}
        self._id = 0
        self.alive = True
        threading.Thread(target=self._read, daemon=True).start()
        self.call("hello", {"client": client})

    def _read(self) -> None:
        try:
            for line in self._rfile:
                msg = json.loads(line)
                mid = msg.get("id")
                if mid in self._pending:
                    event, box = self._pending[mid]
                    box.update(msg)
                    event.set()
                elif mid is None and msg.get("method", "").startswith("gate.") and self.notify:
                    self.notify(msg["method"][len("gate."):], msg.get("params") or {})
        except (OSError, ValueError):
            pass
        finally:
            self.alive = False
            for event, box in list(self._pending.values()):
                box.setdefault("error", {"code": -32000, "message": "the connection to the gate closed", "data": {"gate": "upstream"}})
                event.set()

    def call(self, method: str, params: dict | None = None):
        if not self.alive:
            raise ConnectionError("the connection to the gate is closed")
        event, box = threading.Event(), {}
        with self._lock:
            self._id += 1
            mid = self._id
            self._pending[mid] = (event, box)
            req = {"jsonrpc": "2.0", "id": mid, "method": method}
            if params:
                req["params"] = params
            try:
                self.sock.sendall((json.dumps(req) + "\n").encode())
            except OSError as exc:
                self._pending.pop(mid, None)
                raise ConnectionError(f"the gate did not take {method}: {exc}") from None
        if not event.wait(CALL_TIMEOUT_S):
            self._pending.pop(mid, None)
            raise TimeoutError(f"no answer to {method} from the gate in {CALL_TIMEOUT_S:g} s")
        self._pending.pop(mid, None)
        err = box.get("error")
        if err:
            data = dict(err.get("data") or {})
            code = data.pop("gate", None)
            if code == "upstream":
                raise ConnectionError(err.get("message", "robotd does not answer"))
            if code:
                raise GateError(code, err.get("message", code), **data)
            raise RuntimeError(f"{method}: {err}")
        return box.get("result", {})

    def close(self) -> None:
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class RemoteGate:
    """The interface RobotRuntime uses of a gate (open, close, handle, who, tick), over duck-gate's socket."""

    remote = True

    def __init__(self, path: Path, link, adapter: "DuckAdapter"):
        self.path, self.link, self.adapter = path, link, adapter
        self._wires: dict = {}
        self._next = 0
        self._lock = threading.Lock()
        self._probe = None

    def open(self, client: str, notify=None) -> int:
        wire = _Wire(self.path, client, notify)
        with self._lock:
            self._next += 1
            self._wires[self._next] = wire
            return self._next

    def close(self, cid: int) -> None:
        with self._lock:
            wire = self._wires.pop(cid, None)
        if wire is not None:
            wire.close()

    def handle(self, cid: int, method: str, params: dict | None = None):
        if method == "robot.state":
            return self.link.via(lambda m, p: self.adapter.state(), method, params)
        wire = self._wires.get(cid)
        if wire is None:
            raise GateError("unknown_connection", "this connection is closed")
        return self.link.via(wire.call, method, params or {})

    def _probe_wire(self) -> _Wire:
        if self._probe is None or not self._probe.alive:
            self._probe = _Wire(self.path, GATE_NAME + "-who")
        return self._probe

    def who(self) -> dict:
        try:
            return self.link.via(lambda m, p: self._probe_wire().call(m, p), "gate.who", {})
        except OSError as exc:      # ConnectionError and TimeoutError are OSErrors: a gate that does not answer says so
            return {"holder": None, "lease_id": None, "unreachable": str(exc)}

    def health(self) -> dict:
        return self.link.via(lambda m, p: self._probe_wire().call(m, p), "robot.health", {})

    def tick(self) -> None:
        pass


class DuckNavigatorClient:
    """The navigator API of RFC-0014 §3.7 for goal runs: the same interface as the fake's navigator, over TCP to
    duck-nav-server. `step()` polls the server's status (decisions and objects since the last poll) and hands them to the
    callbacks; `goal_status()` is what the last poll saw."""

    def __init__(self, address: str, clock=time.monotonic):
        host, _, port = address.rpartition(":")
        self.address = (host or "127.0.0.1", int(port))
        self.clock = clock
        self._on_decision = lambda text, **data: None
        self._on_objects = lambda objs: None
        self._active = False
        self._status: dict = {"state": "idle"}
        self._dn, self._ov, self._fails, self._last = 0, -1, 0, -1e9

    def bind(self, on_decision, on_objects) -> None:
        self._on_decision, self._on_objects = on_decision, on_objects

    def _rpc(self, method: str, params: dict | None = None):
        with socket.create_connection(self.address, timeout=CALL_TIMEOUT_S) as sock:
            sock.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}) + "\n").encode())
            reply = json.loads(sock.makefile("r").readline())
        if "error" in reply:
            raise RuntimeError(reply["error"].get("message", str(reply["error"])))
        return reply["result"]

    def goal_start(self, spec: dict) -> dict:
        self._dn, self._ov, self._fails = 0, -1, 0
        try:
            out = self._rpc("goal.start", spec)
        except (OSError, RuntimeError) as exc:
            self._status = {"state": "refused", "reason": f"the navigator server did not answer: {exc}"}
            return {"run_key": None}
        if "error" in out:
            err = out["error"]
            self._status = {"state": "refused", "reason": err.get("message", str(err))}
            return {"run_key": None}
        self._active = True
        self._status = {"state": "running", "run_key": out["run_key"]}
        return {"run_key": out["run_key"]}

    def goal_status(self) -> dict:
        return dict(self._status)

    def goal_cancel(self) -> None:
        try:
            self._rpc("goal.cancel")
        except (OSError, RuntimeError):
            return
        self.settle(10.0)

    def settle(self, seconds: float) -> None:
        """Poll until the run has ended or `seconds` are up: a STOP or a cancel is seen by the navigator at its next tick."""
        end = time.monotonic() + seconds
        while self._active and time.monotonic() < end:
            self._poll()
            if not self._active:
                return
            time.sleep(0.1)

    def step(self) -> None:
        if self._active and self.clock() - self._last >= POLL_EVERY_S:
            self._last = self.clock()
            self._poll()

    def _poll(self) -> None:
        try:
            st = self._rpc("goal.status", {"decisions_since": self._dn, "objects_since": self._ov})
            self._fails = 0
        except (OSError, RuntimeError, ValueError) as exc:
            self._fails += 1
            if self._fails >= FAILS_BEFORE_LOST:
                self._active = False
                self._status = {"state": "interrupted", "reason": f"the navigator server stopped answering: {exc}"}
            return
        for d in st.get("decisions", []):
            self._on_decision(d["text"], rule=d.get("rule"), values=d.get("values") or {}, n=d["n"])
        self._dn = st.get("decisions_n", self._dn)
        if st.get("objects") is not None:
            self._ov = st["objects_v"]
            self._on_objects(st["objects"])
        self._status = {k: st.get(k) for k in ("state", "reason", "progress", "result", "broken", "run_key")}
        if st["state"] in TERMINAL:
            self._active = False


class DuckAdapter:
    """Robot file: {"type": "duck-sim", "navigator": "127.0.0.1:8061", "observatory": "http://127.0.0.1:8070"}, and
    `gate_socket`, `mapd_socket` when they are not this machine's host file's (RFC-0021: the host file says where the
    robot's sockets are; a robot file that names none takes the host's gate and map sockets). `observatory` is where the
    goal runs' Watch links point (the Observatory's /watch/<run key>)."""

    def __init__(self, cfg, clock=time.monotonic):
        options = cfg.adapter
        if "gate_socket" not in options or "mapd_socket" not in options:
            import simhost
            host = simhost.load(options.get("host"))
            options = {"gate_socket": str(host.sockets["gate"]), "mapd_socket": str(host.sockets["map"]), **options}
        self.gate_socket = _addr(options["gate_socket"])
        self.nav_address = options.get("navigator", "127.0.0.1:8061")
        self.mapd_socket = _addr(options["mapd_socket"])
        self.observatory = (options.get("observatory") or "").rstrip("/") or None
        self.clock = clock
        self.scale = load_scale(options.get("calibration", "sim"))
        self._stream = None
        self._stream_at = 0.0
        self._health = (0.0, None)
        self._gate = None
        self._map_cache = (0.0, None)

    def call(self, method: str, params: dict | None = None):
        raise NotImplementedError("the duck's calls go through its gate (make_gate)")

    def make_gate(self, link) -> RemoteGate:
        self._gate = RemoteGate(self.gate_socket, link, self)
        return self._gate

    def make_navigator(self, gate, clock=time.monotonic) -> DuckNavigatorClient:
        return DuckNavigatorClient(self.nav_address, clock)

    def watch_url(self, run_key: str | None) -> str | None:
        return f"{self.observatory}/watch/{run_key}" if self.observatory and run_key else None

    # --- state: the subscription's latest, in the page's shape ------------------------------------------

    def _on_state(self, _state: dict) -> None:
        self._stream_at = self.clock()

    def state(self) -> dict:
        if self._stream is None or self.clock() - self._stream_at > STATE_STALE_S:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self._stream = StateStream(self.gate_socket, hz=5, on_state=self._on_state, client=GATE_NAME + "-state")
            deadline = time.monotonic() + 2.0
            while self._stream.latest is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if self._stream.latest is None:
                self._stream.close()
                self._stream = None
                raise ConnectionError("no robot.state from the gate")
            self._stream_at = self.clock()
        s = self._stream.latest
        pos, yaw = s["odom"]["position"], s["odom"]["yaw"]
        applied = (s.get("move") or {}).get("applied") or [0.0, 0.0, 0.0]
        safety = s.get("safety") or {}
        out = {"pose": {"x": round(pos[0] * self.scale, 4), "y": round(pos[1] * self.scale, 4), "yaw": round(yaw, 4), "frame": "site"},
               "velocity": {"vx": round(applied[0], 4), "vyaw": round(applied[2], 4)},
               "mode": "moving" if abs(applied[0]) > 1e-3 or abs(applied[2]) > 1e-3 else "idle",
               "link": "duck-gate", "policy": s.get("policy"),
               "flags": {"fall": bool(safety.get("fallen")), "picked_up": bool(safety.get("picked_up")), "limp": bool(safety.get("limp"))}}
        out["battery_pct"] = self._battery()
        return out

    def _battery(self):
        at, value = self._health
        if self.clock() - at >= HEALTH_EVERY_S and self._gate is not None:
            try:
                value = round(self._gate.health().get("battery", {}).get("percent"), 1)
            except Exception:                                  # noqa: BLE001 - the battery is information
                pass
            self._health = (self.clock(), value)
        return value

    # --- the map: mapd's grid, in the site frame ---------------------------------------------------------

    def map(self) -> dict:
        from duck_lab.nav.client import Rpc
        rpc = Rpc(self.mapd_socket)
        try:
            g = rpc.call("map.grid", {"res_m": 0.05})
        finally:
            rpc.close()
        cells = g.get("cells", "")
        res = g.get("res_m", 0.05) * self.scale
        origin = [v * self.scale for v in g.get("origin", [0.0, 0.0])]
        data = [-1 if c == "?" else 100 if c == "#" else 0 for c in cells]
        return {"frame": "site", "kind": "occupancy_grid", "resolution_m": res, "origin": origin, "width": g.get("width", 0),
                "height": g.get("height", 0), "data": data, "version": hash(cells) & 0xFFFFFFF}

    def map_version(self) -> int:
        return self.map()["version"]

    def sighting(self) -> dict:
        raise ApiError(404, "no_sighting", "the camera runs with a goal: its sightings are in the goal run's Observatory run")
