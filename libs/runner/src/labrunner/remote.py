"""The runner's side of the payload (RFC-0021 §3, step 2): the navigator started as its own process with only the robot's
connections (the robot's registered PAYLOAD: duck_lab.payload for the duck), driven over its contract, and its run copied
into the official one with the truth put in (runfile.truthcopy) while it runs. The runner keeps what the payload never
gets: the host file, the truth, the judge.

    with Remote(host, run_out, scene_id, name, data, key, truth_log) as nav:     # nav.go_to, nav.loc.pose(), nav.record
        ...
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from labrunner import robots
from labrunner.rpc import Rpc
from runfile import build as runbuild
from runfile import keys, scenefile
from runfile.navcontract import ContractError, ENDS, check_hello, check_state
from runfile.profilestore import describe
from runfile.truthcopy import TruthCopy

STARTED_S = 60.0         # the payload process answers within this, or it is stopped
POLL_S = 0.1             # how often a goal's status is asked
COPY_S = 0.2             # how often the payload's run is copied into the official one (the live view's lag)
STOP_S = 10.0            # the payload ends this long after `stop`, else SIGTERM, then SIGKILL


class PayloadError(RuntimeError):
    """The payload process did not start, died, or answered with an error."""


def event(kind: str, text: str, /, **raw) -> dict:          # positional: a row's own fields may be named `kind` (a goal's)
    """The runner's own event, in the shape a navigator row's event has in a run (runfile.adapters.duck)."""
    return {"kind": kind, "text": text, "notable": True, "t_src": None, "raw": raw}


REPO = Path(__file__).resolve().parent       # the checkout whose commit a run's build names (git finds its root from here)


def add_impairment_arg(ap) -> None:
    ap.add_argument("--depth-impairment", type=int, metavar="SEED", default=None,
                    help="simulate the real depth sensor's impairments (the profile's numbers, seed SEED; run i of a batch uses SEED + i); "
                         "default off; a real robot refuses it")


def add_controller_args(ap) -> None:
    ap.add_argument("--local-controller", choices=("rules", "learned"), default=None,
                    help="the navigator's local controller (RFC-0025 section 3.7): rules (the profile's rules@1, the default) or learned "
                         "(an ONNX model, with --model); the simulator only, a real robot refuses it")
    ap.add_argument("--model", type=Path, metavar="PATH", default=None, help="the ONNX model of --local-controller learned")


def controller_setting(args, ap) -> dict | None:
    """The run's local controller from the options: None for the profile's own, else {"name": "learned", "model": path}. A usage
    error (exit 2) for a model with no learned controller, a learned one with no model, or a model that is not a file."""
    if args.local_controller != "learned":
        if args.model is not None:
            ap.error("--model is the model of --local-controller learned")
        return None
    if args.model is None:
        ap.error("--local-controller learned needs --model PATH")
    if not args.model.is_file():
        ap.error(f"--model {args.model}: not a file")
    return {"name": "learned", "model": str(args.model)}


def controller_options(setting: dict | None) -> list:
    return ["--local-controller", setting["name"], "--model", setting["model"]] if setting else []


def refuse_controller_unless_sim(setting: dict | None, variant: str) -> None:
    if setting and variant != "sim":
        raise ValueError(f"--local-controller learned is the simulator's for now: the {variant!r} robot refuses it (RFC-0025 R8)")


def impairment_seed(seed: int | None, i: int, probe: bool = False) -> int | None:
    """Run i's impairment seed from the option's: SEED + i in a batch, SEED itself for a probe (one fixed run)."""
    return None if seed is None else seed if probe else seed + i


def impairment_in_force(variant: str, seed: int | None, profile=None) -> dict | None:
    """What the depth impairment is for this run: the option's setting, else the profile version's own (a stored version may
    have it on, read from `profile` when the caller has it); None when it is not on. A real robot has no such block."""
    if seed is not None:
        return {"enabled": True, "seed": seed}
    if variant != "sim":
        return None
    try:
        block = (profile or robots.profile(variant)).sensors.tof8x8.get("impairment")
    except (OSError, ValueError, AttributeError, KeyError):
        return None
    return dict(block.data if hasattr(block, "data") else block) if block else None


PROC = Path("/proc")       # where a process's sockets are read, when the host has it (a test points it elsewhere)
# what a navigator's process does not inherit: the host file (it gets the sockets) and the installation file (it gets its profile
# as an argument and never reads this machine's installation: the operator's decision i)
NOT_INHERITED = ("ROBOTICS_LAB_HOST", "ROBOTICS_LAB_INSTALLATION")


def navigator_env() -> dict:
    """The environment a navigator's process starts with: this one, less NOT_INHERITED."""
    return {k: v for k, v in os.environ.items() if k not in NOT_INHERITED}


def truth_connections(pid: int, port: int) -> int | None:
    """The TCP connections process `pid` holds to `port` on this host: its own sockets (/proc/<pid>/fd) matched by inode in
    the kernel's TCP tables; where there is no /proc (macOS), `lsof` on the process. None when the process is gone or
    neither can say: not measured, never 0."""
    if PROC.exists():
        try:
            fds = list((PROC / str(pid) / "fd").iterdir())
        except FileNotFoundError:
            return None
        inodes = set()
        for fd in fds:
            try:
                link = os.readlink(fd)
            except OSError:
                continue
            if link.startswith("socket:["):
                inodes.add(link[8:-1])
        n = 0
        for table in ("net/tcp", "net/tcp6"):
            try:
                lines = (PROC / table).read_text().splitlines()[1:]
            except OSError:
                continue
            for line in lines:
                f = line.split()
                if len(f) > 9 and f[9] in inodes and int(f[2].rsplit(":", 1)[1], 16) == port:
                    n += 1
        return n
    try:
        os.kill(pid, 0)               # lsof says nothing for a process that is gone: that is not 0
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    try:
        out = subprocess.run(["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-Fn"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    # -Fn: one `n<local>-><remote>` line per connection; lsof exits 1 when the process has none at all
    return sum(1 for line in out.stdout.splitlines() if line.startswith("n") and "->" in line
               and line.rsplit("->", 1)[1].rsplit(":", 1)[-1] == str(port))


def judge_scene(scene: str, path: Path | None = None) -> dict | None:
    """The scene file a run is judged in, as the run records it (runfile.scenefile.describe): `path`, else the repository's
    scenes/<scene>/scene.json; None when there is neither."""
    path = Path(path) if path is not None else scenefile.REPOSITORY / scene / "scene.json"
    return scenefile.describe(path) if path.exists() else None


def judge_truth(host, unenforced=()) -> dict:
    """What a run records about the truth it was judged by, beside judge_profile and judge_scene: whether the host had any (its
    truth_port), why not, and the truth guardrails the goal asked for that no one checked."""
    has = host.truth_port is not None
    return {"available": has, "reason": None if has else f"truth_port is null in {host.source}", "unenforced": list(unenforced)}


class _Loc:
    def __init__(self, remote: "Remote"):
        self.remote = remote

    def pose(self):
        p = self.remote.call("goal.status").get("pose")
        return tuple(p) if p else None


class Remote:
    """The payload as a navigator for the course code (go_to, loc.pose(), record, scale), across a process boundary."""

    def __init__(self, host, run_out: Path, scene: str, name: str, data: Path, key: str, truth_log, variant: str = "sim",
                 copy: TruthCopy | None = None, run: dict | None = None, payload: list | None = None,
                 camera: Path | None = None, extra: list | None = None, robot: Path | None = None, client: str | None = None,
                 scene_file: Path | None = None, depth_impairment: int | None = None, local_controller: dict | None = None):
        """`copy`: an official run already being written (an evaluation's earlier goals), which this payload's run is copied
        on into (TruthCopy.next_source), else a new one; `run`: its run record's fields that are the runner's (`kind`);
        `camera`: the camera's socket the runner serves (labrunner.camera), handed to the payload as one of the robot's;
        `extra`: more of the payload's own options (a navigator's test switches); `robot`: another robot socket than the
        host's (a gate's), spoken to as `client`; `scene_file`: the scene description the run is judged in (a challenge's, written
        for it), else the repository's for `scene` when there is one (runfile.scenefile), recorded as judge_scene;
        `depth_impairment`: the simulated depth sensor's impairments on, with this seed (the payload's --depth-impairment), refused for
        a variant that is not the simulator's; `local_controller`: {"name": "learned", "model": path}, handed on as --local-controller and
        --model, the same refusal. The run records its build (runfile.build), read here, at the run's start."""
        if depth_impairment is not None and variant != "sim":
            raise ValueError(f"--depth-impairment is the simulator's: the {variant!r} robot's depth frames are not impaired")
        refuse_controller_unless_sim(local_controller, variant)
        # the profile version this machine runs the robot on, resolved once before anything starts (a named one that does not exist
        # refuses the run here): the file the referee judges by (labrunner.geometry) is the file handed to the navigator, so both
        # read one version, and the official run records it as judge_profile; only the robot's own navigator takes --profile
        profile = robots.given_profile() if payload is None else None
        self.build = runbuild.of(REPO, host, variant, impairment_in_force(variant, depth_impairment), ctrl=runbuild.controller(local_controller))
        run = {**(run or {}), "judge_profile": describe(robots.profile_file()), "judge_scene": judge_scene(scene, scene_file),
               "judge_truth": judge_truth(host), "build": self.build}
        self.host, self.run_out = host, Path(run_out)
        self.dir = Path(tempfile.mkdtemp(prefix="pl-"))           # short: a unix socket path is limited to ~100 bytes
        self.sock = self.dir / "payload.sock"
        self.payload_data = self.run_out / "payload-data"         # the payload's own run: not the Observatory's data folder
        src = keys.run_dir(self.payload_data, keys.make_key(robots.get().NAME, scene, name))
        if copy is None:
            self.copy = TruthCopy(src, keys.run_dir(Path(data), key), key, truth_log.nearest, run=run)
        else:
            self.copy = copy
            copy.next_source(src)
        self._lock = threading.Lock()                             # the copy is written by the pump and by the runner's events
        self._stop = threading.Event()
        cmd = (list(payload) if payload else robots.navigator_command("PAYLOAD")) + [     # the robot's navigator, or any that keeps the contract
               "--robot", str(robot or host.sockets["robot"]), "--depth", str(host.sockets["depth"]), "--map", str(host.sockets["map"]),
               "--listen", str(self.sock), "--out", str(self.run_out), "--data", str(self.payload_data),
               "--scene", scene, "--name", name, "--variant", variant] + (["--camera", str(camera)] if camera else []) + \
            (["--client", client] if client else []) + (["--profile", str(profile)] if profile else []) + \
            (["--depth-impairment", str(depth_impairment)] if depth_impairment is not None else []) + \
            controller_options(local_controller) + list(extra or [])
        env = navigator_env()                                     # nothing of the host but its sockets, nothing of the installation
        self.log = open(self.run_out / "payload.log", "a")       # an evaluation's payloads, one after another
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        self.rpc = None
        try:
            self._connect()
            hello = check_hello(self.call("hello"))     # another major version of the contract: refused, both said
        except Exception:
            self.close()
            raise
        self.name, self.kinds, self.scale = hello["name"], hello["kinds"], hello.get("scale")
        self.loc = _Loc(self)
        self._pump = threading.Thread(target=self._pumping, name="truth-copy", daemon=True)
        self._pump.start()

    def _connect(self) -> None:
        end = time.monotonic() + STARTED_S
        while True:
            if self.proc.poll() is not None:
                raise PayloadError(f"the payload ended before it answered (exit {self.proc.returncode}): see {self.run_out / 'payload.log'}")
            try:
                self.rpc = Rpc(self.sock, timeout=300.0)
                return
            except OSError:
                if time.monotonic() > end:
                    raise PayloadError(f"the payload did not answer on {self.sock} within {STARTED_S:.0f} s") from None
                time.sleep(0.2)

    def call(self, method: str, params: dict | None = None) -> dict:
        if self.proc.poll() is not None:
            raise PayloadError(f"the payload died (exit {self.proc.returncode}): see {self.run_out / 'payload.log'}")
        try:
            return self.rpc.call(method, params)
        except (OSError, json.JSONDecodeError) as e:
            raise PayloadError(f"{method}: the payload stopped answering ({type(e).__name__}: {e})") from None

    def _pumping(self) -> None:
        while not self._stop.wait(COPY_S):
            self.pump()

    def pump(self) -> None:
        with self._lock:
            try:
                self.copy.pump()
            except FileNotFoundError:
                pass                       # the payload has not opened its run yet

    def record(self, **row) -> None:
        """A runner's event in the official run (the course's per-goal row, an invariant, the verdict), at the run's time."""
        ev = row.pop("event")
        text = row.get("why") or " ".join(f"{k} {v}" for k, v in row.items() if k in ("n", "status", "rule"))
        with self._lock:
            if self.copy.rec is not None:
                self.copy.add(self.copy.last_t, "event", event(ev, f"{ev} {text}".strip(), **row))

    def localise(self) -> tuple | None:
        try:
            return tuple(self.call("localise")["pose"])
        except RuntimeError:
            return None

    def _goal(self, spec: dict) -> dict:
        """A goal in the contract's shape, followed to its end: the last goal.status."""
        started = self.call("goal.start", spec)
        if "error" in started:
            raise PayloadError(f"goal.start {spec['kind']}: {started['error'].get('message')} ({started['error'].get('code')})")
        while True:
            st = self.call("goal.status")
            try:
                state = check_state(st.get("state"))
            except ContractError as e:
                raise PayloadError(str(e)) from None
            if state in ENDS:
                return st
            time.sleep(POLL_S)

    def go_to(self, goal, timeout_s: float) -> dict:
        """As Navigator.go_to: {status, why, ...} with the contract's end as `status`, the goal in the payload's map."""
        st = self._goal({"kind": "point", "params": {"x": float(goal[0]), "y": float(goal[1])},
                         "conditions": {"done_when": {"within_s": float(timeout_s)}}})
        out = dict(st.get("result") or {})
        out["status"], out["why"] = st["state"], st.get("reason")
        return out

    def explore(self, minutes: float, **opts) -> dict:
        """`opts`: the explore goal's options (objects, find, site, object_costs, relocalise: duck_lab.payload)."""
        st = self._goal({"kind": "explore", "params": opts, "budget": {"minutes": float(minutes)}})
        if st["state"] == "failed" or st.get("result") is None:
            raise PayloadError(f"explore {st['state']} in the payload: {st.get('reason')}")
        return st["result"]

    def break_goal(self, name: str, detail: str) -> None:
        """A guardrail the runner checks by the truth broke (its truth guard, an invariant): the goal ends stopped_by_guardrail."""
        try:
            self.call("goal.break", {"name": name, "detail": detail})
        except PayloadError:
            pass

    def close(self, verdict: str | None = None, finish: bool = True):
        """The payload stopped (asked, then signalled); the robot stopped by the runner itself as well; the run copied whole.
        `finish`: the official run ends here (False: an evaluation's next goal copies on into it)."""
        self._stop.set()
        try:
            if self.rpc is not None and self.proc.poll() is None:
                self.call("stop")
        except (PayloadError, RuntimeError):
            pass
        try:
            self.proc.wait(STOP_S)
        except subprocess.TimeoutExpired:
            for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
                try:
                    os.killpg(self.proc.pid, sig)
                    self.proc.wait(wait)
                    break
                except (subprocess.TimeoutExpired, ProcessLookupError):
                    continue
        self._zero_move()
        if self.rpc is not None:
            self.rpc.close()
        self.log.close()
        self.sock.unlink(missing_ok=True)
        try:
            self.dir.rmdir()
        except OSError:
            pass
        with self._lock:
            if not finish:
                self.copy.pump()        # all of this payload's run, before the next one's
                return None
            return self.copy.finish(verdict) if self.copy.rec is not None or self.copy.follower.dir.exists() else None

    def truth_connections(self, port: int) -> int | None:
        """How many TCP connections the payload's process holds to `port` now (the truth's): its own sockets (/proc/<pid>/fd)
        matched by inode against the kernel's TCP tables, or where there is no /proc (macOS) `lsof`; None when neither can
        tell (not measured, not zero). The body server's port also takes joint targets (op `write`), so a connection would
        be an actuation path too."""
        return truth_connections(self.proc.pid, port)

    def _zero_move(self) -> None:
        """robotd keeps the last command it was given: a payload that died mid-goal leaves the duck walking."""
        try:
            r = Rpc(self.host.sockets["robot"], timeout=2.0)
            try:
                r.call("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
            finally:
                r.close()
        except (OSError, RuntimeError):
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
