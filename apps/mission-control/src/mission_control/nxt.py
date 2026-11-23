"""The NXT (RFC-0014 §3.7, step 4): Mission Control's adapter over nxt-web's HTTP API.

nxt-web is the only process on the brick's link (USB or Bluetooth), so it is the robot's gate (RFC-0017 §3.2): its exclusive lock,
its STOP and its takeover list are the robot's, and Mission Control keeps no second copy. `NxtGate` gives the robot runtime the
interface of an in-process gate (open, close, handle, who, tick) over nxt-web's `/api/lock`, `/api/drive`, `/api/stop` and
`/api/status`; a lease is tied to the session id nxt-web returns, one per Mission Control client. nxt-web does not push a lost
lease, so `who()`, which the runtime calls at every poll, looks for a session whose lease is gone and tells that client.

The NXT has no pose, no map and no navigator: its state is the tracks and the battery, and it takes no goals (its robot file says
so, and a goal is refused for lack of a navigator). Mission Control reaches it only through nxt-web; never through a device."""

import json
import threading
import time
import urllib.error
import urllib.request

from robotgate import PROTOCOL, GateError
from runfile import installation

from .errors import ApiError

CALL_TIMEOUT_S = 5.0
GATE_NAME = "mission-control"
FULL = 100          # nxt-web drives the tracks in percent, -100 to 100
BATTERY_EMPTY_MV, BATTERY_FULL_MV = 6000, 8400      # 0 % and 100 %: where the brick gives up, and a charged rechargeable pack; fresh alkalines read above


class _Conn:
    def __init__(self, client: str, notify):
        self.client, self.notify = client, notify
        self.session = None
        self.lease_id = None


def _clamp(v: float) -> int:
    return int(round(max(-FULL, min(FULL, v))))


class NxtGate:
    """The interface RobotRuntime uses of a gate, over nxt-web's HTTP lock."""

    remote = True

    def __init__(self, base: str, link, adapter: "NxtAdapter"):
        self.base, self.link, self.adapter = base, link, adapter
        self._conns: dict = {}
        self._next = 0
        self._lock = threading.Lock()

    # --- connections: a client of Mission Control is a connection here, a session at nxt-web ---------------------

    def open(self, client: str, notify=None) -> int:
        with self._lock:
            self._next += 1
            self._conns[self._next] = _Conn(client, notify)
            return self._next

    def close(self, cid: int) -> None:
        with self._lock:
            self._conns.pop(cid, None)

    def tick(self) -> None:
        pass

    # --- HTTP ---------------------------------------------------------------------------------------------------

    def _http(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=CALL_TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                reply = json.loads(exc.read())
            except ValueError:
                raise ConnectionError(f"nxt-web answered {exc.code} to {path}") from None
            code = reply.get("lock")
            if code:
                data = {k: v for k, v in reply.items() if k not in ("ok", "error", "lock")}
                raise GateError(code, reply.get("error", code), **data) from None
            raise RuntimeError(reply.get("error") or f"nxt-web answered {exc.code} to {path}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ConnectionError(f"nxt-web does not answer at {self.base}: {getattr(exc, 'reason', exc)}") from None

    def _conn(self, cid: int) -> _Conn:
        conn = self._conns.get(cid)
        if conn is None:
            raise GateError("unknown_connection", "this connection is closed")
        return conn

    # --- the gate's methods -------------------------------------------------------------------------------------

    def handle(self, cid: int, method: str, params: dict | None = None):
        params = params or {}
        if method == "robot.state":
            return self.link.via(lambda m, p: self.adapter.state(), method, params)
        return self.link.via(lambda m, p: self._call(cid, m, p), method, params)

    def _call(self, cid: int, method: str, params: dict):
        conn = self._conn(cid)
        if method in ("gate.acquire", "gate.takeover"):
            reply = self._http("POST", "/api/lock", {"action": "takeover" if method == "gate.takeover" else "acquire", "client": conn.client})
            conn.session, conn.lease_id = reply["session"], reply["lease_id"]
            return {"lease_id": reply["lease_id"], "expires_in_s": reply["expires_in_s"]}
        if method == "gate.release":
            if conn.session is None:
                raise GateError("not_holder", "this connection does not hold the robot")
            session, conn.session = conn.session, None
            self._http("POST", "/api/lock", {"action": "release", "session": session})
            return {"ok": True}
        if method == "gate.keepalive":
            if conn.session is None:
                raise GateError("no_lease", "this connection does not hold the robot: acquire first")
            return self._http("POST", "/api/lock", {"action": "keepalive", "session": conn.session})
        if method == "gate.who":
            return self._http("GET", "/api/lock")
        if method == "robot.move":
            left, right = self.adapter.tracks(params.get("vx", 0.0), params.get("vyaw", 0.0))
            self._http("POST", "/api/drive", {"left": left, "right": right, "session": conn.session})
            return {"ok": True, "applied": [params.get("vx", 0.0), 0.0, params.get("vyaw", 0.0)]}
        if method == "robot.stop":
            self._http("POST", "/api/stop", {"client": conn.client})
            return {"ok": True}
        if method == "robot.health":
            return self.adapter.health()
        raise GateError("unknown_method", f"the NXT gate has no method {method}")

    def who(self) -> dict:
        """The lock's holder, from nxt-web. A session of ours whose lease is no longer the current one is told (the lease_lost
        of the duck's gate), with nxt-web's own reason, which a keepalive with the dead session returns."""
        try:
            who = self.link.via(lambda m, p: self._http("GET", "/api/lock"), "gate.who", {})
        except OSError as exc:
            return {"protocol": PROTOCOL, "holder": None, "lease_id": None, "unreachable": str(exc)}
        for conn in list(self._conns.values()):
            if conn.session is not None and (who.get("holder") is None or who.get("lease_id") != conn.lease_id):
                session, conn.session = conn.session, None
                try:
                    self._http("POST", "/api/lock", {"action": "keepalive", "session": session})
                    reason = "lost"
                except GateError as exc:
                    reason = exc.data.get("reason") or str(exc)
                except OSError:
                    reason = "lost"
                if conn.notify:
                    conn.notify("lease_lost", {"reason": reason})
        return {"protocol": PROTOCOL, **who}


class NxtWatcher:
    """The NXT's alarms (RFC-0019's record, source "robot"), from each poll's state: a low battery, a lost link, a deadman stop, an
    obstacle stop. The runtime asks `update` after every poll and puts what it returns on the bus, where the page's fit verdict and
    the robot's `alarms` read them like the duck's. The NXT has no navigator, which is where the duck's alarms come from.

    One alarm of a name is not raised twice inside its gap: a held drive meets the same wall every 200 ms, and the battery sags under
    load. Only the low battery is raised again while it holds (every 30 s, so a major alarm stays inside the page's 60 s window);
    the others fire on the change."""

    LOW_PCT, CLEAR_PCT = 20, 25         # low below 20 %, until it is over 25 % (a hysteresis: a sag under load is not a recovery)
    GAP_S = {"obstacle_stop": 10.0, "deadman_stop": 10.0, "link_lost": 10.0, "low_battery": 30.0}

    def __init__(self):
        self._last: dict = {}
        self._flags = {"obstacle_stop": False, "deadman_stop": False}
        self._low = False
        self._was_online = False

    def _raise(self, name: str, severity: str, module: str, summary: str, now: float, **values) -> list:
        if name in self._last and now - self._last[name] < self.GAP_S[name]:
            return []
        self._last[name] = now
        return [{"anomaly": name, "severity": severity, "source": "robot", "module": module, "t": now, "summary": summary, "values": values}]

    def update(self, status: dict | None, online: bool, now: float) -> list:
        out = []
        if self._was_online and not online:
            out += self._raise("link_lost", "major", "nxt-web", "the NXT stopped answering: nxt-web or the brick's link is gone; "
                               "the brick stops its tracks by itself when commands stop", now)
        self._was_online = online
        if status is None:
            return out
        flags = status.get("flags") or {}
        rng = ((status.get("sensors") or {}).get("ultrasonic") or {}).get("range_m")
        if flags.get("obstacle_stop") and not self._flags["obstacle_stop"]:
            out += self._raise("obstacle_stop", "minor", "robotd-lite", "the brick stopped the tracks: something is closer than 15 cm ahead"
                               + (f" ({rng * 100:.0f} cm)" if rng is not None else ""), now, range_m=rng)
        if flags.get("deadman_stop") and not self._flags["deadman_stop"]:
            out += self._raise("deadman_stop", "major", "robotd-lite", "the tracks stopped because no drive command arrived for 0.5 s", now)
        self._flags = {k: bool(flags.get(k)) for k in self._flags}
        pct = status.get("battery_pct")
        if pct is not None:
            self._low = pct < self.LOW_PCT or (self._low and pct < self.CLEAR_PCT)
            if self._low:
                out += self._raise("low_battery", "major", "nxt-web", f"the battery is at {pct} %; the brick will stop driving soon", now,
                                   battery_pct=pct, battery_mv=status.get("battery_mv"))
        return out


class NxtAdapter:
    """Robot file: {"type": "nxt-web", "url": "http://127.0.0.1:8000", "full_speed_mps": 0.3, "full_turn_rps": 1.5}. `full_speed_mps` and
    `full_turn_rps` say what a full track command is: a forward speed of full_speed_mps is both tracks at 100, a turn of full_turn_rps is
    the tracks 50 apart each way. For a robot file that points at the registered NXT they are the profile's locomotion.cruise_mps and
    yaw_max_rad_s, and the address is the installation's `connections.nxt-web`; a file that holds the robot itself, or an adapter block
    that names them, keeps its own. Else the factsheet's maximumSpeed and maximumAngularSpeed when the file has those; the NXT's
    speeds are not measured, so they are assumed values, and the factsheet's limits are left out."""

    def __init__(self, cfg, clock=time.monotonic):
        from .robots import ConfigError

        options = cfg.adapter
        limits = cfg.factsheet.get("physicalParameters", {})
        locomotion = cfg.profile.data.get("locomotion", {}) if cfg.profile is not None else {}
        self.url = (options.get("url") or self._connection(cfg, ConfigError) or "http://127.0.0.1:8000").rstrip("/")
        self.max_vx = options.get("full_speed_mps") or locomotion.get("cruise_mps") or limits.get("maximumSpeed")
        self.max_vyaw = options.get("full_turn_rps") or locomotion.get("yaw_max_rad_s") or limits.get("maximumAngularSpeed")
        if not self.max_vx or not self.max_vyaw:
            raise ConfigError(f"{cfg.id}: the nxt-web adapter needs full_speed_mps and full_turn_rps (or the profile's locomotion.cruise_mps and "
                              "yaw_max_rad_s, or the factsheet's maximumSpeed and maximumAngularSpeed) to turn a speed into a track command")
        self.max_vx, self.max_vyaw = float(self.max_vx), float(self.max_vyaw)
        # the brick's battery in millivolts, as a percent of this span: assumed, not measured (NXT-MVP1.md D1 measures the pack); a
        # robot file may set its own, as for the speeds
        self.empty_mv = float(options.get("battery_empty_mv", BATTERY_EMPTY_MV))
        self.full_mv = float(options.get("battery_full_mv", BATTERY_FULL_MV))
        # the sensors the profile (or the robot file) declares, by the id the state names them with: {id: (nxt-web's port, kind)}
        self.sensors = {s["id"]: (str(s["port"]), s.get("kind")) for s in cfg.capabilities.get("sensors", []) if "port" in s}
        self.clock = clock
        self._gate = None

    @staticmethod
    def _connection(cfg, error) -> str | None:
        """nxt-web's address from this machine's installation (`robots.<robot>.connections.nxt-web`), for a robot file that points at a
        registered robot; None when it names none."""
        if cfg.robot is None:
            return None
        try:
            inst = installation.load(required=False)
        except installation.InstallationError as exc:
            raise error(f"{cfg.id}: {exc}") from None
        r = inst.robot(cfg.robot) if inst is not None else None
        return r.connections.get("nxt-web") if r is not None else None

    def call(self, method: str, params: dict | None = None):
        raise NotImplementedError("the NXT's calls go through its gate (make_gate)")

    def make_gate(self, link) -> NxtGate:
        self._gate = NxtGate(self.url, link, self)
        return self._gate

    def make_watcher(self) -> NxtWatcher:
        return NxtWatcher()

    def make_navigator(self, gate, clock=time.monotonic):
        raise ApiError(501, "not_built", "the NXT has no navigator")

    def watch_url(self, run_key):
        return None

    def tracks(self, vx: float, vyaw: float) -> tuple:
        fwd = max(-1.0, min(1.0, float(vx) / self.max_vx)) * FULL
        turn = max(-1.0, min(1.0, float(vyaw) / self.max_vyaw)) * FULL / 2
        return _clamp(fwd - turn), _clamp(fwd + turn)

    def _status(self) -> dict:
        req = urllib.request.Request(self.url + "/api/status")
        try:
            with urllib.request.urlopen(req, timeout=CALL_TIMEOUT_S) as resp:
                st = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ConnectionError(f"nxt-web does not answer at {self.url}: {getattr(exc, 'reason', exc)}") from None
        if not st.get("connected"):
            raise ConnectionError(f"nxt-web has no brick: {st.get('error') or 'not connected'}")
        return st

    def battery_pct(self, mv) -> int | None:
        if mv is None:
            return None
        return int(round(max(0.0, min(1.0, (mv - self.empty_mv) / (self.full_mv - self.empty_mv))) * 100))

    def _sensors(self, st: dict) -> dict:
        """Each declared sensor's newest reading, from nxt-web's sampler (`/api/status` `sensors`, by port). One that nxt-web does not
        report (another program owns the brick) is left out, never made up. An ultrasonic reads 255 cm when nothing is in range."""
        out = {}
        for sid, (port, kind) in self.sensors.items():
            reading = (st.get("sensors") or {}).get(port)
            if reading is None:
                continue
            if kind == "range":
                cm = reading.get("value")
                out[sid] = {"range_m": None if cm is None or cm >= 255 else round(cm / 100, 2)}
            else:
                out[sid] = {"value": reading.get("value"), "label": reading.get("label")}
            if reading.get("error"):
                out[sid]["error"] = reading["error"]
        return out

    def state(self) -> dict:
        st = self._status()
        stops = st.get("stops") or {}
        # the tracks nxt-web last commanded; a brick that stopped itself (the obstacle, the deadman) is not moving, whatever was asked
        halted = bool(stops.get("deadman_stop") or stops.get("obstacle_stop"))
        left, right = st.get("left", 0), st.get("right", 0)
        vx = 0.0 if halted else (left + right) / 2 / FULL * self.max_vx
        vyaw = 0.0 if halted else (right - left) / FULL * self.max_vyaw
        # flags are the conditions that make it not fit to go: the running program is a fact, not a flag, so it stands beside them
        return {"velocity": {"vx": round(vx, 4), "vyaw": round(vyaw, 4)},
                "mode": "stopped" if halted and (left or right) else "moving" if left or right else "idle",
                "tracks": {"left": left, "right": right},
                "link": st.get("link"), "battery_mv": st.get("battery_mv"), "battery_pct": self.battery_pct(st.get("battery_mv")),
                "fake": bool(st.get("fake")), "program": st.get("program"),
                "sensors": self._sensors(st),
                "flags": {"deadman_stop": bool(stops.get("deadman_stop")), "obstacle_stop": bool(stops.get("obstacle_stop"))}}

    def health(self) -> dict:
        st = self._status()
        return {"ok": True, "battery_mv": st.get("battery_mv"), "battery_pct": self.battery_pct(st.get("battery_mv")), "link": st.get("link")}

    def map(self) -> dict:
        raise ApiError(404, "no_map", "the NXT has no map")

    def map_version(self) -> int:
        return 0

    def sighting(self) -> dict:
        raise ApiError(404, "no_recogniser", "the NXT has no camera")
