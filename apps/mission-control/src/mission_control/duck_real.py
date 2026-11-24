"""The real duck (RFC-0014 step 8, phase 5 item 4b unit B6): the simulated duck's adapter over the sockets `lab-link` forwards from the robot.

Nothing about the way to the robot changes: every command passes the gate (lab-gate on this machine, upstream the forwarded robotd
socket), the navigator API is lab-nav-server run from a host file with `truth_port: null`, the state is the gate's subscription. What
differs is that the robot is a long way away and can go away:

- **The link can be down, and Mission Control starts without it.** The ssh window of the robot's face button lasts 30 minutes
  (RFC-0002 §3.3), and the gate exits when its upstream closes. So the adapter asks the four sockets (the same read-only questions as
  `lab-link check`) in the background, and while any is dead the robot is offline and says which and why: the reason an offline robot's
  page shows, never an error that stops Mission Control. The gate's socket may be missing at start: the connection of Mission Control's
  own is made when the gate is there (`RealGate`).
- **A run on it is refused unless the robot file allows it** (`allow_real_runs`, robots.RobotConfig.real_run_refusal; core and calibration
  ask it). The adapter does not ask: a robot file whose adapter is another type but whose variant is real is held to the same rule.
- **It never reads the simulator's addresses.** The installation's entry for the robot is used only when it names the variant real; the
  defaults are the real folder's (`~/.cache/duck-real`, `lab-link`'s) and a navigator port of its own (8062), so a gate or a navigator of
  the simulator cannot answer for the real duck. A robot file that finds the installation running the duck as the simulator is refused.
- It needs no truth: the odometry scale is the profile's (the real variant's), the map is mapd's through the navigator API, and a
  calibration reference is the operator's tape.

The question the link check asks is lab-link's, one function in `runfile.linkcheck` that both use."""

import threading
import time
from pathlib import Path

from robotgate import GateError, ProtocolError
from runfile.linkcheck import CHECK_TIMEOUT_S as LINK_TIMEOUT_S, check_socket as _ask

from .duck import DuckAdapter, RemoteGate, _Wire

LINK_DIR = "~/.cache/duck-real"     # lab-link's default folder: apart from the simulator's, so one never answers for the other
NAVIGATOR = "127.0.0.1:8062"        # the simulator's navigator is 8061 (lab-nav-server's default)
LINK_EVERY_S = 5.0                  # between the checks: lab-link asks robotd every 2 s already, and a second asker is a cost on the robot
RECIPE = "docs/wip/REAL-DUCK-LINK.md"
OWN_RETRY_S = 2.0

# (name, file under the link folder, the read-only question). The names, files and questions are labrunner.link.duck_forwards'
FORWARDS = (("robot", "{robot}.sock", "robot.health"), ("depth", "{robot}-tof.sock", "tof.stream"), ("map", "{robot}-map.sock", "map.status"))
GATE = ("gate", "{robot}-gate.sock", "gate.who")


class LinkWatch:
    """The latest answer of the four sockets, asked again every `every_s` on a thread of its own (a silent socket takes `timeout_s`, and
    Mission Control's tick must not wait for it). Started by the first question, so an adapter made and never used asks nothing."""

    def __init__(self, probes, every_s: float = LINK_EVERY_S, timeout_s: float = LINK_TIMEOUT_S):
        self.probes, self.every_s, self.timeout_s = list(probes), every_s, timeout_s      # (name, path, method, is the gate)
        self._latest = None                 # (time.monotonic(), [(name, ok, why)])
        self._first = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def once(self) -> None:
        results = [(n, *_ask(p, m, self.timeout_s, g)[:2]) for n, p, m, g in self.probes]
        self._latest = (time.monotonic(), results)
        self._first.set()

    def _run(self) -> None:
        while True:
            self.once()
            time.sleep(self.every_s)

    def failures(self) -> list:
        """What is wrong with the link, one line each; empty when every socket answered lately (lab-link check: PASS)."""
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True, name="duck-real-link-watch")
                self._thread.start()
        self._first.wait(self.timeout_s * len(self.probes) + 1.0)
        latest = self._latest
        if latest is None:
            return ["the first check of the sockets has not finished"]
        at, results = latest
        if time.monotonic() - at > 3 * self.every_s + self.timeout_s * len(self.probes):
            return ["the checks of the sockets stopped running"]
        return [f"{n}: {why}" for n, ok, why in results if not ok]


class RealGate(RemoteGate):
    """The gate's socket may be missing when Mission Control starts (the link and the gate are started by hand, and the gate exits with
    its upstream): a connection is made when the gate is there, not when it is opened. The connection of Mission Control's own carries the
    gate's `someone_else_drives` notice, so `tick` makes it again when it is missing or dead. A client's connection that dies is not made
    again: its lease died with it, and the client acquires anew (RFC-0017)."""

    def __init__(self, path, link, adapter):
        super().__init__(path, link, adapter)
        self._specs: dict = {}              # cid -> (client, notify)
        self._own = None
        self._retry_at = 0.0

    def open(self, client: str, notify=None) -> int:
        with self._lock:
            self._next += 1
            cid = self._next
            self._specs[cid] = (client, notify)
            self._own = cid if self._own is None else self._own        # the first is Mission Control's own: RobotRuntime opens it first
        try:
            self._connect(cid)
        except (OSError, ProtocolError):
            pass
        return cid

    def _connect(self, cid: int) -> None:
        client, notify = self._specs[cid]
        wire = _Wire(self.path, client, notify)
        with self._lock:
            self._wires[cid] = wire

    def close(self, cid: int) -> None:
        self._specs.pop(cid, None)
        super().close(cid)

    def handle(self, cid: int, method: str, params: dict | None = None):
        if method == "robot.state":
            return super().handle(cid, method, params)
        if cid not in self._specs:
            raise GateError("unknown_connection", "this connection is closed")

        def call(m, p):
            if cid not in self._wires:
                self._connect(cid)
            return self._wires[cid].call(m, p)
        return self.link.via(call, method, params or {})

    def who(self) -> dict:
        """Not counted as an answer of the link (the simulator's is): that the gate answers says nothing about the robot behind it, and an
        online robot is one whose link check passes and whose stream is read."""
        try:
            return self._probe_wire().call("gate.who", {})
        except OSError as exc:
            return {"holder": None, "lease_id": None, "unreachable": str(exc)}

    def tick(self) -> None:
        wire = self._wires.get(self._own)
        if self._own in self._specs and (wire is None or not wire.alive) and time.monotonic() >= self._retry_at:
            self._retry_at = time.monotonic() + OWN_RETRY_S
            if wire is not None:
                self.close_wire(self._own)
            try:
                self._connect(self._own)
            except (OSError, ProtocolError):
                pass

    def close_wire(self, cid: int) -> None:
        wire = self._wires.pop(cid, None)
        if wire is not None:
            wire.close()


class RealDuckAdapter(DuckAdapter):
    """Robot file: {"id": "duck-real", "robot": "duck", "adapter": {"type": "duck-real", "allow_real_runs": false}}: a pointer to the robot's
    profile, its variant the installation's (`robots.duck.variant`) else real. Addresses, each the adapter block's when it names one: `gate_socket`
    (else `<link_dir>/<robot>-gate.sock`), `navigator` (else 127.0.0.1:8062), `link_dir` (else ~/.cache/duck-real: where `lab-link` puts
    `<robot>.sock`, `<robot>-tof.sock` and `<robot>-map.sock`), `observatory`. The installation's `robots.<robot>.gate` and `.navigator` are
    read only when that entry's variant is real. `allow_real_runs` (default false) is the rule of robots.RobotConfig.real_run_refusal."""

    gate_class = RealGate

    @staticmethod
    def _installed(inst, cfg):
        mine = inst.robot(cfg.robot) if inst is not None else None
        return mine if mine is not None and mine.variant == "real" else None

    @staticmethod
    def _default(option: str, cfg) -> str | None:
        if option == "navigator":
            return NAVIGATOR
        return str(Path(cfg.adapter.get("link_dir", LINK_DIR)).expanduser() / GATE[1].format(robot=cfg.robot)) if option == "gate_socket" else None

    def __init__(self, cfg, clock=time.monotonic):
        from .robots import ConfigError
        if cfg.variant != "real":
            raise ConfigError(f"{cfg.id}: a duck-real robot file is the real duck, but this machine runs robot {cfg.robot!r} in "
                              f"{cfg.variant!r} (the installation's robots.{cfg.robot}.variant): the real duck and the simulated one are not "
                              f"both this machine's; remove the variant from the installation, or this robot file")
        super().__init__(cfg, clock)
        self.link_dir = Path(cfg.adapter.get("link_dir", LINK_DIR)).expanduser()
        probes = [(n, self.link_dir / f.format(robot=cfg.robot), m, False) for n, f, m in FORWARDS]
        probes.append((GATE[0], self.gate_socket, GATE[2], True))
        self.watch = LinkWatch(probes)

    def state(self) -> dict:
        down = self.watch.failures()
        if down:
            raise ConnectionError(f"the real duck's link is down (lab-link check: FAIL): {'; '.join(down)}. Bring it up as in {RECIPE}")
        return super().state()
