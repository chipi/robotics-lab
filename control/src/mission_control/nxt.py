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

from duck_lab.gate import GateError

from .errors import ApiError

CALL_TIMEOUT_S = 5.0
GATE_NAME = "mission-control"
FULL = 100          # nxt-web drives the tracks in percent, -100 to 100


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
            return {"holder": None, "lease_id": None, "unreachable": str(exc)}
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
        return who


class NxtAdapter:
    """Robot file: {"type": "nxt-web", "url": "http://127.0.0.1:8000"}. The drive capability's max_vx and max_vyaw say what a full
    track command is: a forward speed of max_vx is both tracks at 100, a turn of max_vyaw is the tracks 50 apart each way."""

    def __init__(self, options: dict, capabilities: dict, clock=time.monotonic):
        self.url = (options.get("url") or "http://127.0.0.1:8000").rstrip("/")
        drive = capabilities.get("drive") or {}
        self.max_vx = float(drive.get("max_vx") or 0.3)
        self.max_vyaw = float(drive.get("max_vyaw") or 1.5)
        self.clock = clock
        self._gate = None

    def call(self, method: str, params: dict | None = None):
        raise NotImplementedError("the NXT's calls go through its gate (make_gate)")

    def make_gate(self, link) -> NxtGate:
        self._gate = NxtGate(self.url, link, self)
        return self._gate

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

    def state(self) -> dict:
        st = self._status()
        left, right = st.get("left", 0), st.get("right", 0)
        vx = (left + right) / 2 / FULL * self.max_vx
        vyaw = (right - left) / FULL * self.max_vyaw
        return {"velocity": {"vx": round(vx, 4), "vyaw": round(vyaw, 4)},
                "mode": "moving" if left or right else "idle",
                "tracks": {"left": left, "right": right},
                "link": st.get("link"), "battery_mv": st.get("battery_mv"), "battery_pct": None,
                "fake": bool(st.get("fake")),
                "flags": {"program": st.get("program"), "deadman_stop": bool((st.get("deadman", {}).get("state") or {}).get("deadman_stop"))}}

    def health(self) -> dict:
        st = self._status()
        return {"ok": True, "battery_mv": st.get("battery_mv"), "link": st.get("link")}

    def map(self) -> dict:
        raise ApiError(404, "no_map", "the NXT has no map")

    def map_version(self) -> int:
        return 0

    def sighting(self) -> dict:
        raise ApiError(404, "no_recogniser", "the NXT has no camera")
