"""The navigator contract (libs/runner/CONTRACT.md), one file against both of the duck's navigators: the payload (the courses')
and the navigator API (Mission Control's), each driven through its own `call` with the navigator inside it faked (no robot,
no simulator). The same goal in the contract's shape is given to both, every outcome of the navigator is followed to its
end, and the ends must be the contract's, the same for both. The second payload (payloads/straight.py) answers the payload's
methods. Run: cd robots/duck && uv run python tests/test_contract.py"""

import atexit
import importlib.util
import shutil
import tempfile
import time
import types
from pathlib import Path

from duck_lab import payload as payload_mod
from duck_lab.nav import body as body_mod
from duck_lab.nav import server as server_mod
from duck_lab.nav.client import LeaseLost
from duck_lab.nav.run import Navigator as RealNavigator
from runfile.navcontract import (API_METHODS, CALIBRATION_METHODS, CONTRACT, ENDS, PAYLOAD_METHODS, ContractError, check_hello,
                                 check_state)

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


class FakeRunLog:
    def __init__(self, data, scene, name, kind, out, **_):
        self.key = f"duck/{scene}/{name}"

    def finish(self):
        pass


class FakeNav:
    """Navigator.go_to as `OUTCOME` says: a dict answered at once, "wait" (until a stop is asked: its end), or an
    exception raised."""

    OUTCOME: object = None
    calls: list = []

    def __init__(self, *_, **__):
        self.abort, self.stop_end, self.scale, self.semantic, self.area = None, None, 1.0, None, None
        self.loc = types.SimpleNamespace(pose=lambda: (0.0, 0.0, 0.0))
        self.profile = types.SimpleNamespace(meta={"checksum": "sha256:x", "version": 1, "source": "robot"},
                                             get=lambda path, default=None: {"robot_guards": {"fall_tilt_deg": 45.0, "fall_s": 0.3}}.get(path, default))
        self.records = []
        self.drops, self.edges, self.tilt_now = [], [], None       # what the robot-side guardrails read (phase 5 B3): the cliff check's drops, the IMU's tilt
        self.placed_at = None            # what GoalRun._place gave the localisation (contract 1.5)
        self.localisation = types.SimpleNamespace(seen=None, pose=lambda: (0.0, 0.0, 0.0), name="mapd",
                                                  place=lambda pose: (setattr(self, "placed_at", pose), (0.25, -0.5, 0.1))[1])
        watch = getattr(body_mod, "StopWatch", None)
        self._stops = watch({"hot_c": 60.0}, {"battery_min_pct": 15.0, "battery_low_s": 0.0}) if watch else None

    def _tilt(self):
        return self.tilt_now

    def go_to(self, goal, time_s):
        FakeNav.calls.append((tuple(goal), time_s))
        o = FakeNav.OUTCOME
        if isinstance(o, BaseException):
            raise o
        if o == "wait":
            end = time.monotonic() + 5.0
            while not self.abort and time.monotonic() < end:
                time.sleep(0.01)
            return {"status": self.stop_end, "why": self.abort}
        return dict(o)

    stop_goal, clear_stop = RealNavigator.stop_goal, RealNavigator.clear_stop       # the navigator's own rule
    anomaly = RealNavigator.anomaly
    on_self_stop = None
    health_stop = getattr(RealNavigator, "health_stop", None)
    _stop_on_health = getattr(RealNavigator, "_stop_on_health", None)

    def record(self, **row):
        self.records.append(row)
        if row.get("event") == "anomaly" and getattr(self, "on_anomaly", None):      # as the navigator's own record does
            self.on_anomaly({**row, "t": 1.0})

    def lease_ended(self, exc):
        self.records.append({"event": "lease_ended", "why": exc.reason})

    def close(self):
        pass


for mod in (payload_mod, server_mod):
    mod.Navigator, mod.RunLog = FakeNav, FakeRunLog
tmp = Path(tempfile.mkdtemp(prefix="contract-"))
atexit.register(shutil.rmtree, tmp, True)
SOCKETS = {"robot": tmp / "gate.sock", "depth": tmp / "depth.sock", "map": tmp / "map.sock"}


def payload():
    return payload_mod.Payload(SOCKETS, tmp / "p-out", tmp / "p-data", "apartment", "c1", "sim")


def api():
    return server_mod.NavServer(SOCKETS, tmp / "a-data", tmp / "a-out")


NAVIGATORS = {"payload": payload, "navigator API": api}
GOAL = {"kind": "point", "params": {"x": 1.5, "y": -0.5}, "conditions": {"done_when": {"within_s": 7}}}


def run_goal(nav, outcome, then=None, extra=None) -> dict:
    """The goal started (with `extra` over GOAL's keys), `then` called while it runs (a cancel, a break), polled to its end; its last goal.status."""
    FakeNav.OUTCOME, FakeNav.calls = outcome, []
    started = nav.call("goal.start", {**GOAL, **(extra or {})})
    if then:
        time.sleep(0.05)
        then(nav)
    end = time.monotonic() + 5.0
    while time.monotonic() < end:
        st = nav.call("goal.status", {})
        if st["state"] in ENDS:
            return {**st, "started": started}
        time.sleep(0.01)
    return {"state": "still running", "started": started}


# --- methods and hello ------------------------------------------------------------------------------------------------
for name, make, methods in (("payload", payload, PAYLOAD_METHODS), ("navigator API", api, API_METHODS)):
    nav = make()
    hello = nav.call("hello", {"client": "runner"})
    try:
        ok = check_hello(hello) is hello
    except ContractError as e:
        ok = str(e)
    check(f"the {name} says hello with contract {CONTRACT}, its name, version, goal kinds and camera", ok is True
          and {"name", "version", "contract", "kinds", "camera"} <= set(hello) and "point" in hello["kinds"], hello)
    impl = type(nav).METHODS
    check(f"the {name} answers exactly the contract's methods for it", set(impl) == set(methods),
          sorted(set(impl) ^ set(methods)))
    try:
        nav.call("goal.frobnicate", {})
        answered = True
    except KeyError:
        answered = False
    check(f"the {name} answers no method outside the contract", not answered)

spec = importlib.util.spec_from_file_location("straight", Path(__file__).resolve().parents[1] / "payloads" / "straight.py")
straight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(straight)
check("the second payload (straight) answers exactly the payload's methods", set(straight.Straight.METHODS) == set(PAYLOAD_METHODS),
      sorted(set(straight.Straight.METHODS) ^ set(PAYLOAD_METHODS)))
bare = object.__new__(straight.Straight)
check("the second payload says hello with the contract's version", check_hello(bare.call("hello", {})) is not None)

# --- a goal: the same shape to both, and every outcome to the contract's end -------------------------------------------
CASES = [
    ("reached", {"status": "reached", "time_s": 3.0}, None, "reached"),
    ("refused, with its reason", {"status": "refused", "why": "no path on the map"}, None, "refused"),
    ("the time limit spent", {"status": "timeout", "time_s": 7}, None, "timeout"),
    ("no progress", {"status": "stalled", "why": "20 s without getting closer"}, None, "stalled"),
    ("a guardrail its runner checks broken (goal.break)", "wait",
     lambda n: n.call("goal.break", {"name": "contact", "detail": "touched the box"}), "stopped_by_guardrail"),
    ("cancelled (goal.cancel)", "wait", lambda n: n.call("goal.cancel", {"reason": "the operator"}), "cancelled"),
    ("an error in the navigator", RuntimeError("mapd gone"), None, "failed"),
    ("the robot taken over", LeaseLost("lease ended", "lease_ended", "taken_over_by_mission-control"), None, "interrupted"),
]
for label, outcome, then, want in CASES:
    seen = {}
    for name, make in NAVIGATORS.items():
        nav = make()
        st = run_goal(nav, outcome, then)
        seen[name] = st["state"]
        check(f"{name}: {label} ends {want}", st["state"] == want, (st["state"], st.get("reason")))
        check(f"{name}: {label}: goal.start answers its run key at once", bool((st["started"] or {}).get("run_key")), st["started"])
        check(f"{name}: {label}: the goal was given as the contract's shape (x, y; within_s)", FakeNav.calls == [((1.5, -0.5), 7.0)],
              FakeNav.calls)
        check(f"{name}: {label}: goal.status has state, reason, result and broken", {"state", "reason", "result", "broken"} <= set(st),
              sorted(st))
        if want not in ("reached",):
            check(f"{name}: {label}: the reason says why", bool(st.get("reason")), st.get("reason"))
        if want == "stopped_by_guardrail":
            check(f"{name}: the broken guardrail is named", st.get("broken") == {"name": "contact", "detail": "touched the box"},
                  st.get("broken"))
    check(f"{label}: both navigators end the same", len(set(seen.values())) == 1, seen)

for name, make in NAVIGATORS.items():
    nav = make()
    FakeNav.OUTCOME = "wait"
    nav.call("goal.start", dict(GOAL))
    time.sleep(0.05)
    busy = nav.call("goal.start", dict(GOAL))
    check(f"{name}: a second goal while one runs is answered busy", (busy.get("error") or {}).get("code") == "busy", busy)
    nav.call("goal.cancel", {})
    unknown = make().call("goal.start", {"kind": "fly", "params": {}})
    check(f"{name}: a goal kind it does not take is answered unknown_kind", (unknown.get("error") or {}).get("code") == "unknown_kind",
          unknown)

# --- a guardrail its runner checks, broken: an anomaly of the harness (RFC-0019 §2.1), the navigator's own breaks none ----------
for name, make in NAVIGATORS.items():
    nav = make()
    run_goal(nav, "wait", lambda m: m.call("goal.break", {"name": "contact", "detail": "touched the box"}))
    inner = nav.nav if name == "payload" else nav.run.nav
    an = [r for r in inner.records if r.get("event") == "anomaly"]
    check(f"must fail: {name}: goal.break is a critical guardrail_broken anomaly with source harness, naming the guardrail",
          [(a["anomaly"], a["source"], a["severity"], a["values"].get("guardrail")) for a in an]
          == [("guardrail_broken", "harness", "critical", "contact")], an)
api_nav = api()
live = api()
run_goal(live, "wait", lambda m: m.call("goal.break", {"name": "contact", "detail": "touched the box"}))
first, later = live.call("goal.status", {}), live.call("goal.status", {"anomalies_since": 1})
check("must fail: the navigator API's goal.status serves the run's anomalies live, numbered, since a number (contract 1.1)",
      [(a["anomaly"], a["n"], a["source"]) for a in first["anomalies"]] == [("guardrail_broken", 1, "harness")]
      and first["anomalies_n"] == 1 and later["anomalies"] == [] and later["anomalies_n"] == 1, (first.get("anomalies"), later.get("anomalies")))
api_nav = api()
run_goal(api_nav, "wait", lambda m: m.run._break("time_limit", "60 s spent"))
check("must fail: the navigator's own guardrail (a time limit spent) is no anomaly",
      not [r for r in api_nav.run.nav.records if r.get("event") == "anomaly"], api_nav.run.nav.records)

# --- the guardrails its runner could not check (contract 1.2): goal.start's `not_enforced`, one harness anomaly per name ------------
check("this is contract 1.2 or later (not_enforced)", tuple(map(int, CONTRACT.split("."))) >= (1, 2), CONTRACT)
check("contract 1.3: the navigator API answers the calibration methods, the payload does not (the procedures' own test is test_calibration.py)",
      tuple(map(int, CONTRACT.split("."))) >= (1, 3) and set(CALIBRATION_METHODS) <= set(server_mod.NavServer.METHODS)
      and not set(CALIBRATION_METHODS) & set(payload_mod.Payload.METHODS), CONTRACT)
for name, make in NAVIGATORS.items():
    nav = make()
    FakeNav.OUTCOME, FakeNav.calls = "wait", []
    nav.call("goal.start", {**GOAL, "not_enforced": ["contact", "fall"]})
    time.sleep(0.05)
    inner = nav.nav if name == "payload" else nav.run.nav
    an = [r for r in inner.records if r.get("event") == "anomaly"]
    check(f"must fail: {name}: goal.start's not_enforced is one minor guardrail_unenforced anomaly per name, source harness",
          [(a["anomaly"], a["source"], a["severity"], a["values"].get("guardrail")) for a in an]
          == [("guardrail_unenforced", "harness", "minor", "contact"), ("guardrail_unenforced", "harness", "minor", "fall")], an)
    check(f"{name}: and the summary names the guardrail", all(g in a["summary"] for a, g in zip(an, ("contact", "fall"))), an)
    nav.call("goal.cancel", {})
    time.sleep(0.1)
    quiet = make()
    run_goal(quiet, "wait", lambda m: m.call("goal.cancel", {}))
    inner = quiet.nav if name == "payload" else quiet.run.nav
    check(f"{name}: a goal with no not_enforced raises none", not [r for r in inner.records if r.get("event") == "anomaly"])
live = api()
FakeNav.OUTCOME = "wait"
live.call("goal.start", {**GOAL, "not_enforced": ["no_go_area"]})
time.sleep(0.05)
st = live.call("goal.status", {})
check("must fail: the navigator API serves the unenforced alarm live, numbered, through goal.status",
      [(a["anomaly"], a["n"], a["source"]) for a in st["anomalies"]] == [("guardrail_unenforced", 1, "harness")], st.get("anomalies"))
live.call("goal.cancel", {})

# --- the navigator's stop: named by what stopped it (its stop event is the contract's end, not `aborted`) ---------------
n = FakeNav()
n.stop_goal("cancelled", "the operator")
n.stop_goal("stopped_by_guardrail", "guardrail contact: touched")
check("a guardrail broken after a cancel names the stop", (n.stop_end, n.abort) == ("stopped_by_guardrail", "guardrail contact: touched"))
n.stop_goal("cancelled", "the operator again")
check("a cancel after a guardrail does not replace it", (n.stop_end, n.abort) == ("stopped_by_guardrail", "guardrail contact: touched"))
n.clear_stop()
check("the next goal starts with no stop", (n.stop_end, n.abort) == (None, None))
try:
    n.stop_goal("aborted", "x")
    refused = False
except ValueError:
    refused = True
check("a stop named outside the contract's two is refused", refused and n.abort is None)
for name, make in NAVIGATORS.items():
    nav = make()
    st = run_goal(nav, "wait", lambda m: m.call("goal.cancel", {"reason": "the operator"}))
    inner = nav.nav if name == "payload" else nav.run.nav
    check(f"{name}: a cancel stops the navigator as cancelled, with its reason", (inner.stop_end, inner.abort)
          == ("cancelled", "the operator"), (inner.stop_end, inner.abort))

# --- the navigator stops on its own health (phase 5 B2): the goal ends stopped_by_guardrail, `broken` names the cause -----------------
HEALTHY = {"healthy": True, "degraded": False, "reason": None, "battery": {"volts": 7.4, "percent": 50.0},
           "motors": {"hottest": "left_knee", "max_c": 32.0, "mean_c": 31.5}}
CAUSES = (("motor_hot", {**HEALTHY, "motors": {"hottest": "left_knee", "max_c": 64.0, "mean_c": 50.0}}),
          ("battery_low", {**HEALTHY, "battery": {"volts": 6.6, "percent": 5.0}}),
          ("robot_unhealthy", {**HEALTHY, "healthy": False, "reason": "bus: servo 3 missing"}))


def inner_of(name, nav):
    return nav.nav if name == "payload" else nav.run.nav


def poke(name, fn):
    def then(m):
        try:
            fn(inner_of(name, m))
        except Exception as e:      # noqa: BLE001 - a missing piece is a failed check, not a crash
            print(f"  ({type(e).__name__}: {e})")
    return then


for name, make in NAVIGATORS.items():
    for cause, stub in CAUSES:
        st = run_goal(make(), "wait", poke(name, lambda n, h=stub: n._stop_on_health(h)))
        check(f"must fail: {name}: a stub health with {cause} ends the goal stopped_by_guardrail, `broken` naming it",
              st["state"] == "stopped_by_guardrail" and (st.get("broken") or {}).get("name") == cause and st["reason"], (st["state"], st.get("broken"), st["reason"]))
    st = run_goal(make(), "wait", poke(name, lambda n: n.health_stop("stale_stream", "the depth stream has been silent for 3.2 s")))
    check(f"must fail: {name}: a stale stream ends the goal stopped_by_guardrail, `broken` naming stale_stream",
          st["state"] == "stopped_by_guardrail" and (st.get("broken") or {}).get("name") == "stale_stream"
          and "silent for 3.2 s" in (st["reason"] or ""), (st["state"], st.get("broken"), st["reason"]))
    both = make()
    st = run_goal(both, "wait", lambda m: (poke(name, lambda n: n._stop_on_health(HEALTHY))(m), time.sleep(0.1), m.call("goal.cancel", {"reason": "done"})))
    check(f"{name}: a healthy stub does not stop the goal (it runs until the cancel)", st["state"] == "cancelled" and st.get("broken") is None,
          (st["state"], st.get("broken")))

# --- the robot's own guardrails without a truth (phase 5 B3, contract 1.4): the navigator API checks what its runner could not -------
RAILS = [{"name": "fall"}, {"name": "contact"}, {"name": "drop_clearance", "m": 0.8}]
BLIND = {"conditions": {**GOAL["conditions"], "guardrails": RAILS}, "not_enforced": ["fall", "contact", "drop_clearance", "no_go_area"]}
SEEN = {"conditions": {**GOAL["conditions"], "guardrails": RAILS}}                    # a runner with the truth: nothing not enforced


def tilt_over(n):
    n.tilt_now = [60.0, 0.0]


def bumped(n):
    n.localisation.seen = {"lost": None}
    time.sleep(0.2)
    n.localisation.seen = {"lost": "bumped"}


def carried(n):
    n.localisation.seen = {"lost": None}
    time.sleep(0.2)
    n.localisation.seen = {"lost": "carried"}


def drop_near(n):
    n.drops = [(0.3, 0.0)]


check("this is contract 1.4 or later (the robot's own guardrails)", tuple(map(int, CONTRACT.split("."))) >= (1, 4), CONTRACT)
for what, poke_fn, want in (("a trunk tilted 60 deg for 0.3 s", tilt_over, "fall"), ("mapd newly lost as bumped", bumped, "contact"),
                            ("mapd newly lost as carried", carried, "contact"), ("a drop seen 0.3 m off with 0.8 m asked", drop_near, "drop_clearance")):
    st = run_goal(api(), "wait", poke("navigator API", poke_fn), BLIND)
    check(f"must fail: navigator API, no truth: {what} ends the goal stopped_by_guardrail, `broken` naming {want}",
          st["state"] == "stopped_by_guardrail" and (st.get("broken") or {}).get("name") == want and st["reason"], (st["state"], st.get("broken"), st["reason"]))
    st = run_goal(api(), "wait", lambda m, f=poke_fn: (poke("navigator API", f)(m), time.sleep(0.8), m.call("goal.cancel", {"reason": "done"})), SEEN)
    check(f"must fail: navigator API, with a truth (nothing not enforced): {what} is not the robot's to stop: the goal runs to the cancel",
          st["state"] == "cancelled" and st.get("broken") is None, (st["state"], st.get("broken")))
live = api()
run_goal(live, "wait", lambda m: m.call("goal.cancel", {}), BLIND)
inner = live.run.nav
an = [(a["anomaly"], a["values"].get("guardrail")) for a in inner.records if a.get("event") == "anomaly"]
check("must fail: the names the robot checks raise no guardrail_unenforced; the one it cannot (no_go_area) still does", an == [("guardrail_unenforced", "no_go_area")], an)
sided = [r for r in inner.records if r.get("event") == "guardrails_robot_side"]
check("must fail: one guardrails_robot_side event names them, in the truth guard's order", len(sided) == 1 and sided[0]["names"] == ["fall", "contact", "drop_clearance"], sided)
check("goal.status's progress says which the robot checks", live.call("goal.status", {})["progress"].get("guardrails_robot_side") == ["fall", "contact", "drop_clearance"])
quiet = api()
run_goal(quiet, "wait", lambda m: m.call("goal.cancel", {}), SEEN)
check("with a truth: no robot-side event, none listed", not [r for r in quiet.run.nav.records if r.get("event") == "guardrails_robot_side"]
      and quiet.call("goal.status", {})["progress"].get("guardrails_robot_side") == [])
broken = api()
run_goal(broken, "wait", poke("navigator API", tilt_over), BLIND)
check("must fail: a robot-side break is a guardrail event of the run saying side robot",
      any(r.get("event") == "guardrail" and r["name"] == "fall" and r["decision"]["values"].get("side") == "robot" for r in broken.run.nav.records),
      broken.run.nav.records[-2:])

# --- a start pose without a truth (phase 5 B7, contract 1.5): the navigator API takes the operator's word for where the robot stands -------
START = {"x": 2.0, "y": 1.5, "yaw": 0.5}
check("this is contract 1.5 or later (the start pose)", tuple(map(int, CONTRACT.split("."))) >= (1, 5), CONTRACT)
placed_nav = api()
st = run_goal(placed_nav, "wait", lambda m: m.call("goal.cancel", {}), {"start_pose": START})
check("navigator API: goal.start with a start pose answers `placed`: the pose taken (site frame) and the frame change",
      st["started"].get("placed") == {"pose": {**START, "frame": "site"}, "frame": {"x": 0.25, "y": -0.5, "yaw": 0.1}}, st["started"])
check("... the navigator's localisation was placed at it", placed_nav.run.nav.placed_at == (2.0, 1.5, 0.5), placed_nav.run.nav.placed_at)
ev = [r for r in placed_nav.run.nav.records if r.get("event") == "placed"]
check("... the run records a `placed` event with a decision saying the operator's word set the frame",
      len(ev) == 1 and ev[0]["pose"] == [2.0, 1.5, 0.5] and "placed by the operator" in ev[0]["decision"]["reason"], ev)
check("... and the goal runs as any: the cancel ends it", st["state"] == "cancelled", st["state"])
plain = api()
run_goal(plain, "wait", lambda m: m.call("goal.cancel", {}))
check("a goal with no start pose is not placed, and its answer has no `placed`",
      plain.run.nav.placed_at is None and not [r for r in plain.run.nav.records if r.get("event") == "placed"], plain.run.nav.records[:2])
st = run_goal(payload(), "wait", lambda m: m.call("goal.cancel", {}), {"start_pose": START})
check("the payload takes no start pose: it ignores the field, runs the goal and answers no `placed`", "placed" not in st["started"]
      and st["state"] == "cancelled", st["started"])


class NoPlace(FakeNav):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.localisation = types.SimpleNamespace(seen=None, pose=lambda: (0.0, 0.0, 0.0), name="other")


unplaceable = api()
server_mod.Navigator = NoPlace
err = unplaceable.call("goal.start", {**GOAL, "start_pose": START}).get("error") or {}
server_mod.Navigator = FakeNav
check("must fail: a localisation that cannot be placed is answered start_failed, naming it, and no goal is left running",
      err.get("code") == "start_failed" and "other localisation" in err.get("message", "") and unplaceable.run is None, err)

# --- the navigator's gate client reads the gate's protocol (RFC-0018 §5.3) ------------------------------------------------------
import json  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402

from duck_lab.nav.client import Rpc  # noqa: E402
from robotgate import ProtocolError  # noqa: E402


def gate_says(hello_result, n=[0]):
    n[0] += 1
    path = tmp / f"fake-gate-{n[0]}.sock"
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        for line in conn.makefile("r"):
            conn.sendall((json.dumps({"jsonrpc": "2.0", "id": json.loads(line)["id"], "result": hello_result}) + "\n").encode())
    threading.Thread(target=serve, daemon=True).start()
    try:
        Rpc(path, client="duck-nav-server").close()
        return None
    except ProtocolError as exc:
        return exc
    finally:
        srv.close()


check("the navigator's gate client connects to a gate of this protocol, and to one that names none",
      gate_says({"gate": True, "protocol": 1}) is None and gate_says({"gate": True}) is None)
check("must fail: and refuses a gate that speaks a newer protocol", isinstance(gate_says({"gate": True, "protocol": 2}), ProtocolError))

# --- what a reader refuses ---------------------------------------------------------------------------------------------
for hello, why in (({"name": "x", "contract": "2.0"}, "another major version"), ({"name": "x"}, "no contract version")):
    try:
        check_hello(hello)
        refused = False
    except ContractError as e:
        refused = CONTRACT in str(e)
    check(f"a navigator with {why} is refused, both versions said", refused)
check("a minor version is taken", check_hello({"name": "x", "contract": "1.7"})["contract"] == "1.7")
for state in ("aborted", "", None, "reaching"):
    try:
        check_state(state)
        refused = False
    except ContractError:
        refused = True
    check(f"state {state!r} is not the contract's", refused)
check("every end of the contract is a state", all(check_state(s) == s for s in ENDS))

print()
print("CONTRACT", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
