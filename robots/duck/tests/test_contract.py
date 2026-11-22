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
from duck_lab.nav import server as server_mod
from duck_lab.nav.client import LeaseLost
from duck_lab.nav.run import Navigator as RealNavigator
from runfile.navcontract import (API_METHODS, CONTRACT, ENDS, PAYLOAD_METHODS, ContractError, check_hello,
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
        self.profile = types.SimpleNamespace(meta={"checksum": "sha256:x", "version": 1, "source": "robot"})
        self.records = []

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

    def record(self, **row):
        self.records.append(row)

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


def run_goal(nav, outcome, then=None) -> dict:
    """The goal started, `then` called while it runs (a cancel, a break), polled to its end; its last goal.status."""
    FakeNav.OUTCOME, FakeNav.calls = outcome, []
    started = nav.call("goal.start", dict(GOAL))
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
