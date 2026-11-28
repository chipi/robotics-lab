"""The simulated duck (RFC-0014 §3.7, step 2): Mission Control's adapter over the two processes that stand in front of it.

- **duck-gate** (RFC-0017): every command to the robot passes this process. Mission Control is one of its clients, as
  `mission-control`; `RemoteGate` gives Mission Control's robot runtime the interface of an in-process `robotgate.Gate`
  over the gate's socket, one connection per client, so the lock, STOP and takeover are the gate's own and Mission Control
  keeps no second copy.
- **lab-nav-server** (O22, RFC-0022: `labrunner.navapi`, the runner in front of the navigator API `duck_lab.nav.server`): the real navigator as its own process. `DuckNavigatorClient` is the
  navigator API of §3.7 for the goal runs: goal.start, goal.status, goal.cancel. The server holds the lease while a run
  moves the robot and writes the Observatory run; Mission Control only starts, watches and cancels.

robotd has no `robot.state` request, only the `robot.subscribe` stream: the adapter keeps one subscription through the
gate and answers `robot.state` from it, in the shape the page expects (pose in the site frame, mode, flags). The pose is
the navigator API's `site_pose` of robotd's odometry: the navigator owns the frame and the scale, this adapter has neither.

The adapter imports neither the duck's navigator nor the host library (phase 5 step 1): the map comes through the navigator
API's `map`, the addresses from the installation file (runfile.installation), else the robot file's adapter block."""

import json
import math
import socket
import threading
import time
from pathlib import Path

from robotgate import GateError, ProtocolError, check_protocol
from runfile import installation
from runfile.navcontract import ContractError, ENDS, check_calibration_state, check_hello, check_state, speaks

from .errors import ApiError

GATE_NAME = "mission-control"
GATE_UPSTREAM_NAME = "robotics-lab-gate"     # what the gate calls itself to robotd (labrunner.gate CLIENT_NAME): robotd shows it as `move.source` when the gate moves the robot
STATE_STALE_S = 2.0
HEALTH_EVERY_S = 10.0
CALL_TIMEOUT_S = 5.0
SITE_POSE_TIMEOUT_S = 1.0     # the state poll asks the navigator for the pose each time: a navigator that hangs must not hold the state loop for CALL_TIMEOUT_S
POLL_EVERY_S = 0.2
FAILS_BEFORE_LOST = 15      # polls in a row that fail before the navigator is called gone (3 s)


def _addr(text: str) -> Path:
    return Path(text).expanduser()


def stream_hz(rates: dict) -> int:
    """The rate Mission Control subscribes to a robot's state at (the operator's decision h): the whole number ceil(state_hz),
    at most max_state_hz. The gate and robotd take whole numbers only; state_hz stays the rate Mission Control reads at."""
    hz = math.ceil(rates["state_hz"])
    cap = rates.get("max_state_hz")
    return max(1, min(hz, math.floor(cap))) if cap is not None else hz


class _Wire:
    """One connection to the gate: hello, requests with answers, and the gate's `gate.lease_lost` notifications."""

    def __init__(self, path: Path, client: str, notify=None):
        self.client, self.notify = client, notify
        self.hello: dict = {}
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
        try:
            self.hello = self.call("hello", {"client": client})        # the gate's own answer (its protocol), kept for the facts
            check_protocol(self.hello)
        except ProtocolError:
            self.alive = False
            self.sock.close()
            raise

    def _read(self) -> None:
        try:
            for line in self._rfile:
                msg = json.loads(line)
                mid = msg.get("id")
                if mid in self._pending:
                    event, box = self._pending[mid]
                    box.update(msg)
                    event.set()
                elif mid is None:
                    self._note(msg.get("method", ""), msg.get("params") or {})
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

    def _note(self, method: str, params: dict) -> None:
        if method.startswith("gate.") and self.notify:
            self.notify(method[len("gate."):], params)

    def close(self) -> None:
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class _Stream(_Wire):
    """Mission Control's own robot.subscribe through the gate: the latest robot.state, `on_state` called for each."""

    def __init__(self, path: Path, client: str, hz: int, on_state=None):
        self.latest, self._on_state = None, on_state
        super().__init__(path, client)
        # the answer is not waited for here (the states that follow are the answer), but it is kept: a refusal is `refused`
        self.answered, self._answer = threading.Event(), {}
        with self._lock:
            self._pending["subscribe"] = (self.answered, self._answer)
            self.sock.sendall((json.dumps({"jsonrpc": "2.0", "id": "subscribe", "method": "robot.subscribe",
                                           "params": {"hz": hz}}) + "\n").encode())

    @property
    def refused(self) -> str | None:
        """The gate's (or the robot's) refusal of the subscription, in its words, once answered; else None."""
        err = self._answer.get("error") if self.answered.is_set() and "result" not in self._answer else None
        return err.get("message", str(err)) if err else None

    def _note(self, method: str, params: dict) -> None:
        if method == "robot.state":
            self.latest = params
            if self._on_state:
                self._on_state(params)
        else:
            super()._note(method, params)


class RemoteGate:
    """The interface RobotRuntime uses of a gate (open, close, handle, who, tick), over duck-gate's socket."""

    remote = True

    def __init__(self, path: Path, link, adapter: "DuckAdapter"):
        self.path, self.link, self.adapter = path, link, adapter
        self._wires: dict = {}
        self._next = 0
        self._lock = threading.Lock()
        self._probe = None
        self._own = None            # the first connection opened: Mission Control's own (RobotRuntime opens it first), the one its reads go on

    def open(self, client: str, notify=None) -> int:
        wire = _Wire(self.path, client, notify)
        with self._lock:
            self._next += 1
            self._wires[self._next] = wire
            self._own = self._next if self._own is None else self._own
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

    def read(self, method: str, params: dict | None = None):
        """A read-only call of robotd's on Mission Control's own connection (the first opened): the facts and the
        skill list (RFC-0032). The gate lets a read through with no lease."""
        if self._own is None:
            raise ConnectionError("Mission Control has no connection to the gate yet")
        return self.handle(self._own, method, params)

    def hello(self) -> dict:
        wire = self._wires.get(self._own)
        return dict(getattr(wire, "hello", None) or {})

    def tick(self) -> None:
        pass


class DuckNavigatorClient:
    """The navigator API of RFC-0014 §3.7 for goal runs: the same interface as the fake's navigator, over TCP to
    lab-nav-server. `step()` polls the server's status (decisions and objects since the last poll) and hands them to the
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
        self.on_start = None        # called with goal.start's answer when a goal has started (the adapter reads its profile then)
        self.on_anomaly = None      # called with each anomaly the navigator raises (contract 1.1's goal.status `anomalies`)
        self._an = 0

    def bind(self, on_decision, on_objects) -> None:
        self._on_decision, self._on_objects = on_decision, on_objects

    def _rpc(self, method: str, params: dict | None = None, timeout: float = CALL_TIMEOUT_S):
        with socket.create_connection(self.address, timeout=timeout) as sock:
            sock.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}) + "\n").encode())
            reply = json.loads(sock.makefile("r").readline())
        if "error" in reply:
            raise RuntimeError(reply["error"].get("message", str(reply["error"])))
        return reply["result"]

    def goal_start(self, spec: dict) -> dict:
        self._dn, self._ov, self._fails, self._an = 0, -1, 0, 0
        try:
            hello = check_hello(self._rpc("hello"))     # asked at every goal: the server behind the address can be restarted between two
            if spec.get("start_pose") and not speaks(hello, "1.5"):
                # a navigator below 1.5 would ignore the field and run the goal in the wrong frame: worse than no run
                self._status = {"state": "refused", "reason": f"the navigator speaks contract {hello.get('contract')}: it takes no start pose (1.5)"}
                return {"run_key": None}
            out = self._rpc("goal.start", spec)
        except ContractError as exc:
            self._status = {"state": "refused", "reason": str(exc)}
            return {"run_key": None}
        except (OSError, RuntimeError) as exc:
            self._status = {"state": "refused", "reason": f"the navigator server did not answer: {exc}"}
            return {"run_key": None}
        if "error" in out:
            err = out["error"]
            self._status = {"state": "refused", "reason": err.get("message", str(err))}
            return {"run_key": None}
        if spec.get("start_pose") and not out.get("placed"):
            self._rpc("goal.cancel", {"reason": "the navigator did not place the robot"})
            self._status = {"state": "refused", "reason": "the navigator answered no `placed` to the start pose: it was not heard, so the goal is cancelled"}
            return {"run_key": None}
        self._active = True
        self._status = {"state": "running", "run_key": out["run_key"]}
        if self.on_start:
            note = self.on_start(out)
            if note:
                self._on_decision(note, rule="profile", values=out.get("profile") or {})
        return {"run_key": out["run_key"]}

    def goal_status(self) -> dict:
        return dict(self._status)

    def goal_cancel(self) -> None:
        try:
            self._rpc("goal.cancel")
        except (OSError, RuntimeError):
            return
        self.settle(10.0)

    # --- calibration (contract 1.3): the navigator drives, its runner adds the truth's reference, Mission Control keeps the meaning ---

    def calibration_list(self) -> list:
        """The procedures the navigator drives: none from one that speaks less than 1.3, which has no such methods."""
        if not speaks(check_hello(self._rpc("hello")), "1.3"):
            return []
        return self._rpc("calibration.list")["procedures"]

    def calibration_start(self, procedure: str, params: dict) -> dict:
        return self._rpc("calibration.start", {"procedure": procedure, "params": params})

    def calibration_status(self) -> dict:
        st = self._rpc("calibration.status")
        check_calibration_state(st.get("state"))
        return st

    def calibration_cancel(self) -> None:
        self._rpc("calibration.cancel")

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
            st = self._rpc("goal.status", {"decisions_since": self._dn, "objects_since": self._ov, "anomalies_since": self._an})
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
        for a in st.get("anomalies") or []:     # a 1.0 navigator answers none: none raised
            if self.on_anomaly:
                self.on_anomaly(a)
        self._an = st.get("anomalies_n", self._an)
        if st.get("objects") is not None:
            self._ov = st["objects_v"]
            self._on_objects(st["objects"])
        self._status = {k: st.get(k) for k in ("state", "reason", "progress", "result", "broken", "run_key")}
        try:
            check_state(st.get("state"))
        except ContractError as exc:            # the navigator's failure, said: a run never waits on a state it cannot end
            self._status.update(state="failed", reason=str(exc))
        if self._status["state"] in ENDS:
            self._active = False


class DuckAdapter:
    """Robot file: {"robot": "duck", "adapter": {"type": "duck-sim"}}: a pointer to the robot's profile
    (robots.py). Addresses, each the robot file's adapter block's when it names one (`gate_socket`, `navigator`,
    `observatory`: a file that names an address means it), else this machine's installation file's (`robots.<robot>.gate` and
    `.navigator`, `observatory`), else the navigator's default 127.0.0.1:8061; a gate named nowhere is an error saying where to
    name it. The map is the navigator API's `map`: Mission Control opens nothing of the robot's past its gate and its navigator
    API. `observatory` is where the goal runs' Watch links point (the Observatory's /watch/<run key>)."""

    def __init__(self, cfg, clock=time.monotonic):
        from .robots import ConfigError
        if cfg.profile is None:
            raise ConfigError(f"{cfg.id}: a {cfg.adapter.get('type')} robot file points at its robot's profile (\"robot\": \"duck\")")
        options = cfg.adapter
        try:
            inst = installation.load(required=False)
        except installation.InstallationError as exc:
            raise ConfigError(f"{cfg.id}: {exc}") from None
        mine = self._installed(inst, cfg)
        where = inst.source if inst is not None else installation.where()

        def socket_of(option: str, key: str, what: str) -> Path:
            value = options.get(option) or (getattr(mine, key) if mine is not None else None) or self._default(option, cfg)
            if not value:
                raise ConfigError(f"{cfg.id}: where is the robot's {what}? name robots.{cfg.robot}.{key} in {where}, or {option} "
                                  f"in the robot file's adapter block")
            return _addr(str(value))

        self.gate_socket = socket_of("gate_socket", "gate", "gate")
        self.nav_address = options.get("navigator") or (mine.navigator if mine is not None else None) or self._default("navigator", cfg)
        self._map_nav = DuckNavigatorClient(self.nav_address, clock)
        self.observatory = (options.get("observatory") or (inst.observatory if inst is not None else None) or "").rstrip("/") or None
        self.cfg, self.clock = cfg, clock
        self.profile = cfg.profile
        self._stream = None
        self._stream_at = 0.0
        self._health = (0.0, None)
        self._gate = None
        # the names robotd shows as `move.source` for what is ours: the gate's own, and the robot file's `own_sources` if it names more
        self.own_sources = (GATE_UPSTREAM_NAME, *options.get("own_sources", ()))

    # Where an adapter reads its addresses beyond the robot file's block: the installation's entry for the robot, and a default per address.
    # The real duck's adapter overrides both: the installation's entry is the simulator's unless it says it is the real one.
    @staticmethod
    def _installed(inst, cfg):
        return inst.robot(cfg.robot) if inst is not None else None

    @staticmethod
    def _default(option: str, cfg) -> str | None:
        return "127.0.0.1:8061" if option == "navigator" else None

    gate_class = RemoteGate

    def call(self, method: str, params: dict | None = None):
        raise NotImplementedError("the duck's calls go through its gate (make_gate)")

    def make_gate(self, link) -> RemoteGate:
        self._gate = self.gate_class(self.gate_socket, link, self)
        return self._gate

    def make_navigator(self, gate, clock=time.monotonic) -> DuckNavigatorClient:
        nav = DuckNavigatorClient(self.nav_address, clock)
        nav.on_start = self._goal_started
        return nav

    # --- the profile: the version this machine runs, read again when a goal starts ----------------------

    def _goal_started(self, reply: dict) -> str | None:
        """A goal has started: the profile read again (a version saved since applies from this run: the joints' names), and checked
        against the one the navigator says it runs. A difference is said, as a decision on the goal run."""
        from .robots import ConfigError, read_profile
        try:
            self.profile = read_profile(self.cfg.robot, self.cfg.variant)
        except ConfigError as exc:
            return f"Mission Control could not read the robot's profile again ({exc}): profile version {self.profile.meta['version']} stays"
        theirs = (reply.get("profile") or {}).get("checksum")
        mine = self.profile.meta["checksum"]
        if theirs and theirs != mine:
            return (f"the navigator runs profile {theirs[:15]}… (version {reply['profile'].get('version')}), Mission Control reads "
                    f"{mine[:15]}… (version {self.profile.meta['version']})")
        return None

    def watch_url(self, run_key: str | None) -> str | None:
        return f"{self.observatory}/watch/{run_key}" if self.observatory and run_key else None

    # --- state: the subscription's latest, in the page's shape ------------------------------------------

    def _site_pose(self, pos, yaw) -> dict:
        """The pose block of the state: the navigator's answer for robotd's odometry, or, when it gives none (down, hung, below contract
        1.8), why: no pose, never one this adapter made from a scale of its own."""
        try:
            a = self._map_nav._rpc("site_pose", {"odom": {"x": pos[0], "y": pos[1], "yaw": yaw}}, SITE_POSE_TIMEOUT_S)
        except (OSError, RuntimeError, ValueError) as exc:
            return {"pose_error": f"site_pose: {type(exc).__name__}: {exc}"}
        if not (isinstance(a, dict) and a.get("frame") == "site" and all(isinstance(a.get(k), (int, float)) for k in ("x", "y", "yaw"))):
            return {"pose_error": f"site_pose: the navigator gave no site pose ({a.get('error') if isinstance(a, dict) and a.get('error') else 'it speaks a contract below 1.8'})"}
        return {"pose": {"x": round(a["x"], 4), "y": round(a["y"], 4), "yaw": round(a["yaw"], 4), "frame": "site"}}

    def _on_state(self, _state: dict) -> None:
        self._stream_at = self.clock()

    def state(self) -> dict:
        if self._stream is None or self.clock() - self._stream_at > STATE_STALE_S:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self._stream = _Stream(self.gate_socket, GATE_NAME + "-state", hz=stream_hz(self.cfg.rates), on_state=self._on_state)
            deadline = time.monotonic() + 2.0
            while self._stream.latest is None and not self._stream.refused and time.monotonic() < deadline:
                time.sleep(0.02)
            if self._stream.latest is None:
                why = self._stream.refused
                self._stream.close()
                self._stream = None
                raise ConnectionError(f"the gate refused robot.subscribe: {why}" if why else "no robot.state from the gate")
            self._stream_at = self.clock()
        s = self._stream.latest
        pos, yaw = s["odom"]["position"], s["odom"]["yaw"]
        applied = (s.get("move") or {}).get("applied") or [0.0, 0.0, 0.0]
        safety = s.get("safety") or {}
        out = {**self._site_pose(pos, yaw),
               "velocity": {"vx": round(applied[0], 4), "vyaw": round(applied[2], 4)},
               "mode": "moving" if abs(applied[0]) > 1e-3 or abs(applied[2]) > 1e-3 else "idle",
               "link": "duck-gate", "policy": s.get("policy"),
               "flags": {"fall": bool(safety.get("fallen")), "picked_up": bool(safety.get("picked_up")), "limp": bool(safety.get("limp"))},
               # who moved it last and whether its own autonomy is on, as robotd names them (RFC-0032 section 3.2): robotd leaves `autonomous` out when false
               **({"move": {"source": s["move"]["source"]}} if isinstance((s.get("move") or {}).get("source"), str) else {}), "autonomous": bool(s.get("autonomous"))}
        out["battery_pct"] = self._battery()
        names, angles = list(self.profile.joints.names), s.get("joints") or []
        if len(angles) == len(names):                       # robotd's JOINT_NAMES order, the profile's `joints.names`; none reported: no key
            out["joints"] = {n: round(a, 4) for n, a in zip(names, angles)}
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

    # --- the map: the navigator API's (mapd's grid), in the site frame -----------------------------------

    def _grid(self) -> dict:
        """The robot's map as its navigator API answers `map {units: "site"}`: mapd's grid in true metres, in the frame the latest start
        pose set. A navigator below contract 1.8 ignores the unit and answers mapd's metres: not shown as the site's."""
        g = self._map_nav._rpc("map", {"units": "site"})
        if "error" in g:
            raise ConnectionError(f"the navigator API has no map: {g['error']}")
        if g.get("units") != "site":
            raise ConnectionError("the navigator speaks a contract below 1.8: its map is in mapd's metres, which Mission Control no longer scales")
        return g

    def map(self) -> dict:
        g = self._grid()
        cells = g.get("cells", "")
        res = g.get("res_m", 0.05)
        origin = list(g.get("origin", [0.0, 0.0]))
        data = [-1 if c == "?" else 100 if c == "#" else 0 for c in cells]
        return {"frame": "site", "kind": "occupancy_grid", "resolution_m": res, "origin": origin, "width": g.get("width", 0),
                "height": g.get("height", 0), "data": data, "version": hash(cells) & 0xFFFFFFF}

    def map_version(self) -> int:
        return self.map()["version"]

    def sighting(self) -> dict:
        raise ApiError(404, "no_sighting", "the camera runs with a goal: its sightings are in the goal run's Observatory run")

    # --- RFC-0032: what the robot is and runs, and what it can be asked to do (read-only calls of robotd's, through the gate) ---

    ABSENT = (("update.status", "updaterd", "the update state"), ("system.info", "configd", "the robot's name and serial"))

    def _read(self, method: str, absent: list):
        """One read of robotd's through the gate. The gate or robotd refusing it (no such method, not allowed) is that part absent, with the
        reason; a link that does not answer raises, so the whole read fails the way any read of the robot does."""
        if self._gate is None:
            raise ConnectionError("no connection to the gate yet")
        try:
            return self._gate.read(method)
        except (GateError, RuntimeError) as exc:
            absent.append({"method": method, "service": "robotd", "reason": str(exc)})
            return None

    def facts(self) -> dict:
        """The facts (RFC-0032 section 3.1) from `robot.modelApi` (the model API: interface) and `robot.policies` (what fills each slot:
        behaviours), the raw reply of each kept under `raw`. Not reachable through the robotd socket the gate fronts, so absent with that
        reason: `update.status` (updaterd's), `system.info` (configd's: name, serial), and robotd's own version (its `hello`, which the gate
        answers itself; the version reaches the gate's log only)."""
        absent: list = []
        api = self._read("robot.modelApi", absent)
        policies = self._read("robot.policies", absent)
        if api is None and policies is None:
            raise GateError("facts_unavailable", "robotd gave neither robot.modelApi nor robot.policies: " + "; ".join(a["reason"] for a in absent))
        absent += [{"method": m, "service": svc, "reason": f"{svc} serves {m} ({what}), not robotd: Mission Control's link is the robotd socket behind the gate"}
                   for m, svc, what in self.ABSENT]
        absent.append({"method": "hello", "service": "robotd", "reason": "the gate answers hello itself; robotd's daemon_version is in the gate's log only"})
        hello = self._gate.hello() if self._gate is not None else {}
        series = (self.cfg.factsheet.get("typeSpecification") or {}).get("seriesName")
        slots = [{"slot": s.get("slot"), "artefact": None if not s.get("path") else {"kind": "onnx", "origin": s.get("origin"), "path": s["path"]},
                  "overridden": bool(s.get("overridden")), "error": s.get("error")} for s in (policies or {}).get("slots", [])]
        return {"identity": {"model": series} if series else {},
                "software": [],
                "interface": {**({"model_api": api["model_api"]} if isinstance(api, dict) and "model_api" in api else {}),
                              **({"gate_protocol": hello["protocol"]} if "protocol" in hello else {})},
                "behaviours": slots,
                "absent": absent,
                "raw": {"robot.modelApi": api, "robot.policies": policies, "hello": hello}}

    def actions(self) -> list:
        """`robot.skills` as actions: a table skill is a `motion` (a network the robot runs for `duration`), a built-in one (`ground_pick`,
        `sit_toggle`: robotd drives them itself) the same without a length. Pollen's emotions and sounds are not in this reply."""
        absent: list = []
        reply = self._read("robot.skills", absent)
        if reply is None:
            raise GateError("actions_unavailable", f"robot.skills: {absent[0]['reason']}")
        out = [{"actionType": s["name"], "kind": "motion", "duration_s": s.get("duration"),
                "backed_by": {"kind": "onnx", "path": s["path"]} if s.get("path") else None, "raw": s} for s in reply.get("skills", [])]
        out += [{"actionType": n, "kind": "motion", "raw": {"name": n, "built_in": True}} for n in reply.get("built_in", [])]
        return out
