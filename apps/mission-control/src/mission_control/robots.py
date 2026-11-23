"""Robots (RFC-0014 §3.3): robot files, one link per robot, the gate in front of it, the sessions of the
clients that hold it.

The robot file is JSON, one file per robot, `robots/<id>.json` (the format of RFC-0014 §3.3.1, decided in
docs/wip/ROBOT-FILE-FORMAT-PROPOSAL.md): a `factsheet` that is a subset of VDA 5050 3.0.0's with VDA's names (robotfile.py),
and our own snake_case blocks beside it:

    {"id": "fake-1", "label": "Fake robot", "kind": "fake",
     "adapter": {"type": "fake", "call_timeout_s": 2.0},
     "factsheet": {"typeSpecification": {...}, "physicalParameters": {"maximumSpeed": 0.5, ...}, "protocolFeatures": {...}},
     "control": {"deadman_s": 0.5, "lease_s": 20.0, "takeover": ["operator-laptop"]},
     "capabilities": {sensors, recognisers, localisation, map, navigator, guardrails, skills, description},
     "guardrails": [{"name": "max_speed", "mps": 0.4}],          # the robot's own, on every run (§3.4.8)
     "rates": {"state_hz": 2.0, "map_hz": 1.0, "max_state_hz": 10.0},
     "online_after_s": 2.0, "teams": ["pair"]}

A robot with a profile (RFC-0020, phase 5 step 1) has a robot file that points at it instead: its registered name and the
adapter; its kind, factsheet, control, capabilities, guardrails and rates are the profile's, from the version
this machine runs (runfile.registry: the installation's, else the robot's own file), and the file may not repeat them:

    {"id": "duck-sim", "label": "Simulated duck", "robot": "duck", "adapter": {"type": "duck-sim"}}

The environment (the profile's variant, sim or real) is not the file's: it is the installation's `robots.<robot>.variant`, else sim for
the duck-sim adapter and real for any other. A file that still names one is refused when it differs."""

import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from pathlib import Path

from robotgate import Gate, GateError, JsonlLog
from runfile import registry
from runfile.profile import FormatError, Profile, checksum, merge_variant, validate_profile
from runfile.profilestore import StoreError

from . import guardrails, robotfile
from .errors import ApiError, conflict, invalid

MOVED = {"lease_s": "control.lease_s", "takeover": "control.takeover"}   # fields of the first format, with where they went
MAX_SESSIONS = 128
FROM_PROFILE = ("kind", "factsheet", "control", "capabilities", "guardrails", "rates")   # a pointer file's blocks: the profile's


class ConfigError(ValueError):
    pass


def read_profile(robot: str, variant: str) -> Profile:
    """The version of a robot's profile this machine runs now, in one environment; `meta` says which (checksum, version, path)."""
    try:
        path = registry.profile_file(robot)
        raw = validate_profile(json.loads(path.read_text()))
    except (LookupError, registry.ProfileSourceError, StoreError, FormatError, OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"robot {robot!r}: {exc}") from None
    if variant not in raw.get("variants", {}):
        raise ConfigError(f"robot {robot!r}: its profile has no variant {variant!r} (it has {sorted(raw.get('variants', {}))})")
    profile = Profile(merge_variant(raw, variant), variant)
    profile.meta = {"checksum": checksum(raw), "version": int(path.stem) if path.stem.isdigit() else None, "path": str(path)}
    return profile


def profile_of(raw: dict, variant: str, meta: dict) -> Profile:
    """A profile not yet stored (one about to be saved), in one environment, as read_profile gives a stored one."""
    if variant not in raw.get("variants", {}):
        raise ConfigError(f"the profile has no variant {variant!r} (it has {sorted(raw.get('variants', {}))})")
    profile = Profile(merge_variant(raw, variant), variant)
    profile.meta = meta
    return profile


class RobotConfig:
    def __init__(self, raw: dict, profile: Profile | None = None):
        """`profile`: for a pointer file, this profile instead of the version this machine runs (a check before a save)."""
        if not isinstance(raw, dict):
            raise ConfigError("a robot file is a JSON object")
        self.file = raw                     # the robot file as written: reload() builds the robot from it again
        extra = set(raw) - {"id", "label", "kind", "adapter", "factsheet", "control", "capabilities", "guardrails", "rates",
                            "online_after_s", "teams", "robot", "variant"}
        if extra:
            hint = "".join(f"; {k} moved to {MOVED[k]}" for k in sorted(extra) if k in MOVED)
            raise ConfigError(f"unknown fields {sorted(extra)}{hint}")
        self.robot, self.variant, self.profile = raw.get("robot"), "real", None
        if "variant" in raw and self.robot is None:
            raise ConfigError(f"{raw.get('id')}: variant is the environment of the robot's profile: it needs robot")
        if self.robot is not None:
            named = raw.get("variant")
            if not isinstance(self.robot, str) or not (named is None or isinstance(named, str)):
                raise ConfigError(f"{raw.get('id')}: robot is a registered robot's name and variant an environment, both strings")
            # one source: the installation's, else the adapter's default (the duck-sim adapter runs on a host with a truth). Mission
            # Control does not read the host file, so it cannot ask the host as the runner does
            adapter = raw.get("adapter")
            self.variant = registry.variant(self.robot, "sim" if isinstance(adapter, dict) and adapter.get("type") == "duck-sim" else "real")
            if named is not None and named != self.variant:
                raise ConfigError(f"{raw.get('id')}: the robot file names variant {named!r}, but this machine runs robot {self.robot!r} "
                                  f"in {self.variant!r} (the installation's robots.{self.robot}.variant, else the adapter's default): "
                                  f"name it there, and remove it from the robot file")
            repeated = [k for k in FROM_PROFILE if k in raw]
            if repeated:
                raise ConfigError(f"{raw.get('id')}: {', '.join(repeated)} come from the profile of robot {self.robot!r}: "
                                  f"remove them from the robot file (one copy of the robot)")
            self.profile = profile if profile is not None else read_profile(self.robot, self.variant)
            d = self.profile.data
            raw = {**raw, "kind": d["kind"], "label": raw.get("label", d.get("label")),
                   **{k: d[k] for k in FROM_PROFILE[1:] if d.get(k) is not None}}
        self.id = raw.get("id")
        if not isinstance(self.id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.id):
            raise ConfigError(f"id must be lower case letters, digits and dashes, got {self.id!r}")
        self.label = raw.get("label", self.id)
        self.kind = raw.get("kind")
        if not isinstance(self.label, str) or not isinstance(self.kind, str) or not self.kind:
            raise ConfigError(f"{self.id}: label and kind are strings")
        self.adapter = raw.get("adapter")
        if not isinstance(self.adapter, dict) or not isinstance(self.adapter.get("type"), str):
            raise ConfigError(f"{self.id}: adapter needs a type")
        caps = raw.get("capabilities", {})
        if isinstance(caps, dict) and "drive" in caps:
            raise ConfigError(f"{self.id}: capabilities.drive moved: max_vx and max_vyaw are factsheet.physicalParameters.maximumSpeed "
                              "and maximumAngularSpeed, deadman_s is control.deadman_s")
        self.capabilities = caps
        try:
            self.factsheet = robotfile.parse_factsheet(raw.get("factsheet"))
            control = robotfile.parse_control(raw.get("control"))
        except robotfile.FormatError as exc:
            raise ConfigError(f"{self.id}: {exc}") from None
        self.control = control
        try:
            self.guardrails = guardrails.normalise_list(raw.get("guardrails"))
        except ApiError as exc:
            raise ConfigError(f"{self.id}: {exc}") from None
        try:                                # the profile's own rules (runfile.profile): one set for the robot file and the profile
            robotfile.check_max_speed(self.guardrails, self.factsheet)
            robotfile.check_capabilities(caps, self.guardrails)
            rates = robotfile.check_rates(raw.get("rates"))
        except robotfile.FormatError as exc:
            raise ConfigError(f"{self.id}: {exc}") from None
        self.rates = rates
        self.lease_s = control["lease_s"]
        self.takeover = control["takeover"]
        self.online_after_s = float(raw.get("online_after_s", max(2.0, 3.0 / rates["state_hz"])))
        self.teams = list(raw.get("teams", []))
        if not all(isinstance(t, str) and t for t in self.teams):
            raise ConfigError(f"{self.id}: teams is a list of team names")
        self.call_timeout_s = self.adapter.get("call_timeout_s")

    def reload(self) -> None:
        """A pointer file's robot read again from the version this machine runs now (after Mission Control saved or chose one):
        the kind, factsheet, control, capabilities, guardrails and rates. A file that holds the robot itself does not change."""
        if self.robot is not None:
            self.__dict__.update(RobotConfig(self.file).__dict__)


def load_robot_files(directory) -> list:
    """Every robots/*.json of a directory, in file order; a bad file is an error naming it."""
    out, seen = [], set()
    for path in sorted(Path(directory).glob("*.json")):
        if path.name == "planner.json":      # the planner's settings (planner.py) sit beside the robot files, not in them
            continue
        try:
            cfg = RobotConfig(json.loads(path.read_text()))
        except (ConfigError, json.JSONDecodeError) as exc:
            raise ConfigError(f"{path.name}: {exc}") from None
        if cfg.id in seen:
            raise ConfigError(f"{path.name}: the robot id {cfg.id} is used twice")
        seen.add(cfg.id)
        out.append(cfg)
    return out


class Link:
    """One robot's connection (§3.3.1): every call counts as an answer or an error, so `online` is a
    measured fact (the last answer within a bound), never a flag. With a timeout, a call that does not
    answer is abandoned on its own thread and raises, so a hung robot holds up nobody else; a late
    answer may still arrive and the robot's deadman covers it."""

    def __init__(self, call, clock=time.monotonic, timeout_s: float | None = None):
        self._call = call
        self._clock = clock
        self.timeout_s = timeout_s
        self.ok_at = None
        self.errors = 0
        self.last_error = None
        self.last_stop_ok = None

    def __call__(self, method: str, params: dict | None = None):
        return self.via(self._call, method, params)

    def via(self, call, method: str, params: dict | None = None):
        """The same, through another callable: a gate in another process has one connection per client, and each
        goes through the one Link, so what the robot answered is one fact."""
        try:
            result = self._run(call, method, params or {})
        except GateError:
            self.ok_at = self._clock()          # the gate answered: it refused, the link is up
            raise
        except Exception as exc:
            self.errors += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            if method == "robot.stop":
                self.last_stop_ok = False
            raise
        self.ok_at = self._clock()
        if method == "robot.stop":
            self.last_stop_ok = True
        return result

    def _run(self, call, method: str, params: dict):
        if self.timeout_s is None:
            return call(method, params)
        box: dict = {}

        def work():
            try:
                box["result"] = call(method, params)
            except BaseException as exc:
                box["error"] = exc

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        worker.join(self.timeout_s)
        if worker.is_alive():
            raise TimeoutError(f"no answer to {method} in {self.timeout_s:g} s")
        if "error" in box:
            raise box["error"]
        return box["result"]

    def online(self, within_s: float) -> bool:
        return self.ok_at is not None and self._clock() - self.ok_at <= within_s


def gate_error(exc: GateError) -> ApiError:
    status = {"not_allowed": 403, "unknown_method": 400}.get(exc.code, 409)
    return ApiError(status, exc.code, str(exc), **exc.data)


class Session:
    """A client's hold on a robot over HTTP. HTTP has no connection to tie a lease to, so the lease is tied
    to a session id that `acquire` returns and the holder sends with every motion command; a lease
    that ends (expiry, STOP, takeover) ends the session, and a client that comes back late must
    acquire again (RFC-0017 §3.3, as nxt-web's lock does)."""

    def __init__(self, cid: int, client: str):
        self.cid, self.client, self.ended = cid, client, None


class RobotRuntime:
    OWN_SOURCE = "mission-control"

    def __init__(self, cfg: RobotConfig, adapter, *, clock, wall, bus, log_dir=None):
        self.cfg, self.adapter, self.clock, self.bus, self.wall = cfg, adapter, clock, bus, wall
        self.link = Link(adapter.call, clock, cfg.call_timeout_s)
        sink = JsonlLog(Path(log_dir) / f"gate-{cfg.id}.jsonl", wall) if log_dir else None
        self._sink = sink
        if hasattr(adapter, "make_gate"):
            # a gate in its own process (duck-gate, RFC-0017 §3.2): its lease, takeover list and log are its own
            self.gate = adapter.make_gate(self.link)
        else:
            self.gate = Gate(self.link, clock=clock, wall=wall, lease_s=cfg.lease_s, takeover_names=cfg.takeover, log=self._log,
                             own_sources=(self.OWN_SOURCE,))
        self._holder = None
        self.navigator = adapter.make_navigator(self.gate, clock) if cfg.capabilities.get("navigator") else None
        self.mutex = threading.RLock()
        self.sessions: OrderedDict = OrderedDict()
        self._conn = self.gate.open(self.OWN_SOURCE, self._notified)  # Mission Control's own connection: reads and polls
        self.status = None
        self.status_at = None
        self._next_poll = 0.0
        self._next_map = 0.0
        self._map_version = None
        self._was_online = None
        self.active = None  # the goal run on this robot now (a core.ActiveRun)
        self.calibration, self.calibration_n = None, 0      # the latest calibration run (calibration.py) and how many there have been

    def _notified(self, method: str, params: dict) -> None:
        """The gate says something else drives (RFC-0017 §3.8): an alarm on the bus, as the robot's own alarms are, so the page lists it."""
        if method == "someone_else_drives":
            signal = params.get("signal")
            self.bus.emit("anomaly", robot=self.cfg.id, goal_run=None, watch=None, anomaly={
                "anomaly": "someone_else_drives", "severity": "critical", "source": "gate", "t": self.wall(),
                "summary": f"something other than the lease holder drives the robot ({signal}); the robot was stopped and the lease ended",
                "values": {k: v for k, v in params.items()}})

    def _log(self, entry: dict) -> None:
        if self._sink:
            self._sink(entry)
        self.bus.emit("lock", robot=self.cfg.id, **entry)

    # --- measured facts ----------------------------------------------------------------------------

    def online(self) -> bool:
        return self.link.online(self.cfg.online_after_s)

    def poll(self, force: bool = False) -> None:
        """Read the robot's state at its rate (§3.2.2) and note whether it answered."""
        now = self.clock()
        if force or now >= self._next_poll:
            self._next_poll = now + 1.0 / self.cfg.rates["state_hz"]
            try:
                self.status = self.gate.handle(self._conn, "robot.state")
                self.status_at = now
                self.bus.emit("state", robot=self.cfg.id, **self.status)
                if not getattr(self.gate, "remote", False):     # a remote gate (duck-gate) watches its own stream
                    self.gate.observe_state(self.status)
            except Exception:
                pass
        if self.cfg.capabilities.get("map") and now >= self._next_map:
            # paced whether or not it changed: a robot's map can be a call through its navigator API, beside its goals
            self._next_map = now + 1.0 / self.cfg.rates["map_hz"]
            try:
                version = self.adapter.map_version()
                if version != self._map_version:
                    self._map_version = version
                    self.bus.emit("map", robot=self.cfg.id, map=self.adapter.map())
            except Exception:
                pass
        if getattr(self.gate, "remote", False):
            try:
                holder = self.gate.who().get("holder")
                if holder != self._holder:
                    self._holder = holder
                    self.bus.emit("lock", robot=self.cfg.id, event="holder", holder=holder)
            except Exception:
                pass
        online = self.online()
        if online != self._was_online:
            self._was_online = online
            self.bus.emit("robot-online" if online else "robot-offline", robot=self.cfg.id,
                          error=None if online else self.link.last_error)

    # --- the lock: sessions over the gate ---------------------------------------------------------

    def _prune(self) -> None:
        while len(self.sessions) > MAX_SESSIONS:
            for token, s in self.sessions.items():
                if s.ended is not None:
                    self.sessions.pop(token)
                    self.gate.close(s.cid)
                    break
            else:
                return

    def acquire(self, client: str, takeover: bool = False) -> dict:
        if not isinstance(client, str) or not client.strip():
            raise invalid("client names who is asking: a non-empty string")
        client = client.strip()
        session = Session(0, client)

        def notify(method, params):
            if method == "lease_lost":
                session.ended = params.get("reason")

        cid = self.gate.open(client, notify)
        session.cid = cid
        try:
            reply = self.gate.handle(cid, "gate.takeover" if takeover else "gate.acquire")
        except GateError as exc:
            self.gate.close(cid)
            raise gate_error(exc) from None
        token = secrets.token_hex(8)
        self.sessions[token] = session
        self._prune()
        return {"session": token, **reply}

    def _session(self, token) -> Session:
        s = self.sessions.get(token) if isinstance(token, str) else None
        if s is None:
            raise conflict("no_lease", "unknown session: acquire the lock first (POST /lock)")
        return s

    def renew(self, token) -> dict:
        s = self._session(token)
        try:
            return self.gate.handle(s.cid, "gate.keepalive")
        except GateError as exc:
            raise gate_error(exc) from None

    def release(self, token) -> None:
        s = self._session(token)
        try:
            self.gate.handle(s.cid, "gate.release")
        except GateError as exc:
            raise gate_error(exc) from None
        finally:
            self.sessions.pop(token, None)
            self.gate.close(s.cid)

    def drive(self, token, vx: float, vyaw: float) -> dict:
        s = self._session(token)
        try:
            return self.gate.handle(s.cid, "robot.move", {"vx": vx, "vy": 0.0, "vyaw": vyaw})
        except GateError as exc:
            raise gate_error(exc) from None

    def stop(self, client: str) -> dict:
        """STOP: through the gate on a connection of its own, from anyone, with no lease (RFC-0017 §3.4).
        `confirmed` says whether the robot answered robot.stop; an offline robot's STOP is accepted and
        cannot be confirmed (§3.8)."""
        self.link.last_stop_ok = None
        try:
            cid = self.gate.open(client)
            try:
                self.gate.handle(cid, "robot.stop")
            finally:
                self.gate.close(cid)
        except OSError as exc:                     # a gate in another process that does not answer: accepted, not confirmed
            self.link.last_stop_ok = False
            self.link.last_error = f"{type(exc).__name__}: {exc}"
        confirmed = self.link.last_stop_ok is True
        self.bus.emit("stop", robot=self.cfg.id, client=client, confirmed=confirmed)
        return {"robot": self.cfg.id, "confirmed": confirmed, "online": self.online()}


def make_adapter(cfg: RobotConfig, clock):
    """The adapter for a robot file's adapter type. Built: fake; duck-sim (the simulated duck behind lab-gate and lab-nav-server,
    RFC-0014 step 2); nxt-web (the NXT behind nxt-web's HTTP API and lock, step 4)."""
    if cfg.adapter["type"] == "fake":
        from .fake import FakeAdapter
        return FakeAdapter(cfg, clock)
    if cfg.adapter["type"] == "duck-sim":
        from .duck import DuckAdapter
        return DuckAdapter(cfg, clock)
    if cfg.adapter["type"] == "nxt-web":
        from .nxt import NxtAdapter
        return NxtAdapter(cfg, clock)
    raise ConfigError(f"{cfg.id}: no adapter for the type {cfg.adapter['type']!r} (built: fake, duck-sim, nxt-web)")
