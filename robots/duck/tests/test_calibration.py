"""The navigator API's calibration methods (contract 1.3, duck_lab.nav.calibration) against a stand-in gate and robotd: no robot, no
simulator. odometry_scale walks straight and stands, reports the odometry's distance between its two marks, holds the lease
only while it runs, answers busy to a goal (and a goal to it), refuses a held robot and a bad parameter, and ends cancelled,
interrupted or failed as the contract says. Run: cd robots/duck && uv run python tests/test_calibration.py"""

import atexit
import json
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

from duck_lab.nav import calibration, server
from runfile.navcontract import CALIBRATION_ENDS, check_calibration_state

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


calibration.SETTLE_S = 0.3             # the walk's own seconds stay the procedure's smallest, 2 s
tmp = Path(tempfile.mkdtemp(prefix="cal-"))
atexit.register(shutil.rmtree, tmp, True)


class FakeGate:
    """A gate and robotd in one: hello, gate.acquire / release / who, robot.move (the odometry moves 1.1 x what was commanded, as the
    simulator's reads long), and a robot.subscribe stream of the odometry. `refuse` is what a move is answered with instead."""

    def __init__(self, path: Path):
        self.calls, self.x, self.holder, self.refuse, self.factor = [], 0.0, None, None, 1.1
        self._lock = threading.Lock()
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(8)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock):
        send_lock = threading.Lock()

        def send(msg):
            with send_lock:
                sock.sendall((json.dumps(msg) + "\n").encode())

        def stream():
            while True:
                try:
                    send({"jsonrpc": "2.0", "method": "robot.state", "params": {"odom": {"position": [self.x, 0.0, 0.0], "yaw": 0.0}}})
                except OSError:
                    return
                time.sleep(0.05)

        def lines():
            try:
                yield from sock.makefile("r")
            except OSError:                    # the navigator closed its connection: the end of this one
                return

        for line in lines():
            req = json.loads(line)
            m, p, rid = req["method"], req.get("params") or {}, req.get("id")
            with self._lock:
                self.calls.append((m, p))
            if m == "robot.subscribe":
                send({"jsonrpc": "2.0", "id": rid, "result": {"hz": 20}})
                threading.Thread(target=stream, daemon=True).start()
            elif m == "gate.who":
                send({"jsonrpc": "2.0", "id": rid, "result": {"holder": self.holder}})
            elif m == "robot.move" and self.refuse:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -1, "message": "no lease", "data": self.refuse}})
            elif m == "robot.move":
                self.x += p["vx"] * calibration.TICK_S * self.factor
                send({"jsonrpc": "2.0", "id": rid, "result": {"ok": True}})
            else:
                send({"jsonrpc": "2.0", "id": rid, "result": {"ok": True, "protocol": 1}})

    def methods(self):
        with self._lock:
            return [m for m, _ in self.calls]


gate = FakeGate(tmp / "gate.sock")
nav = server.NavServer({"robot": tmp / "gate.sock", "depth": tmp / "depth.sock", "map": tmp / "map.sock"}, tmp / "data", tmp / "out",
                       client="runner")


def end_of(timeout=15.0):
    stop = time.monotonic() + timeout
    while time.monotonic() < stop:
        st = nav.call("calibration.status", {})
        if st["state"] in CALIBRATION_ENDS:
            return st
        time.sleep(0.05)
    return nav.call("calibration.status", {})


idle = nav.call("calibration.status", {})
check("before any run the calibration is idle, and says nothing is measured", idle["state"] == "idle" and idle["measured"] is None and idle["marks"] == [], idle)
listed = nav.call("calibration.list", {})["procedures"]
check("it lists odometry_scale with its defaults: the speed the profile's scale was measured at, and the robot's own maximum",
      [x["id"] for x in listed] == ["odometry_scale"] and listed[0]["params"]["speed_mps"] == 0.3 and listed[0]["params"]["max_speed_mps"] == 0.3
      and listed[0]["params"]["seconds"] == 8.0, listed)

# --- a run -------------------------------------------------------------------------------------------------------------
started = nav.call("calibration.start", {"procedure": "odometry_scale", "params": {"seconds": 2}})
check("a start answers at once with what it runs", started == {"ok": True, "procedure": "odometry_scale", "params": {"speed_mps": 0.3, "seconds": 2.0}}, started)
running = nav.call("calibration.status", {})
check("while it runs the state is running, with the step and no measurement yet",
      running["state"] == "running" and running["step"] in ("settle", "walk") and running["measured"] is None, running)
check("a goal answers busy while a calibration runs, and a second calibration too",
      nav.call("goal.start", {"kind": "point", "params": {"x": 1, "y": 0}})["error"]["code"] == "busy"
      and nav.call("calibration.start", {"procedure": "odometry_scale"})["error"]["code"] == "busy")
done = end_of()
check_calibration_state(done["state"])
check("it ends done with the odometry's distance (1.1 x 0.3 m/s x 2 s) between the marks start and end",
      done["state"] == "done" and abs(done["measured"]["odom_m"] - 0.66) < 0.12 and done["measured"]["speed_mps"] == 0.3
      and [m["name"] for m in done["marks"]] == ["start", "end"] and done["marks"][0]["wall_ns"] < done["marks"][1]["wall_ns"], done)
check("the marks are the host's wall clock, to the second", abs(done["marks"][1]["wall_ns"] / 1e9 - time.time()) < 5.0)
m = gate.methods()
check("the lease was taken, and given back after the last move, which was a stop",
      m.count("gate.acquire") == 1 and m.count("gate.release") == 1 and m.index("gate.release") > max(i for i, x in enumerate(m) if x == "robot.move")
      and [p for x, p in gate.calls if x == "robot.move"][-1]["vx"] == 0.0, m[-6:])
check("a calibration holds no lease between runs: a goal's own checks start from a free robot", nav.call("calibration.cancel", {}) == {"ok": True})
check("a finished run's result stays until the next start", nav.call("calibration.status", {})["measured"]["odom_m"] == done["measured"]["odom_m"])

# --- refusals ----------------------------------------------------------------------------------------------------------
check("a speed above the robot's maximum is refused, naming it", "at most 0.3" in nav.call("calibration.start", {"procedure": "odometry_scale", "params": {"speed_mps": 0.5}})["error"]["message"])
check("a walk of 1 s is refused (the smallest is 2 s)", nav.call("calibration.start", {"procedure": "odometry_scale", "params": {"seconds": 1}})["error"]["code"] == "bad_params")
check("an unknown parameter is refused by name", "frobnicate" in nav.call("calibration.start", {"procedure": "odometry_scale", "params": {"frobnicate": 1}})["error"]["message"])
check("an unknown procedure is refused, listing the ones it has", "odometry_scale" in nav.call("calibration.start", {"procedure": "pivot_creep"})["error"]["message"])
gate.holder = "someone-else"
before = gate.methods().count("gate.acquire")
held = nav.call("calibration.start", {"procedure": "odometry_scale"})
check("a robot held by another client is refused as held, naming the holder, and the lease is not asked for",
      held["error"]["code"] == "held" and held["error"]["holder"] == "someone-else" and gate.methods().count("gate.acquire") == before, held)
gate.holder = None

# --- how it ends otherwise ---------------------------------------------------------------------------------------------
nav.call("calibration.start", {"procedure": "odometry_scale", "params": {"seconds": 5}})
time.sleep(0.8)
nav.call("calibration.cancel", {})
cancelled = end_of()
check("a cancel stands the robot and ends it cancelled, with nothing measured", cancelled["state"] == "cancelled" and cancelled["measured"] is None, cancelled)

gate.refuse = {"gate": "lease_ended", "reason": "taken_over_by operator-laptop"}
nav.call("calibration.start", {"procedure": "odometry_scale", "params": {"seconds": 2}})
taken = end_of()
check("a takeover ends it interrupted, saying who", taken["state"] == "interrupted" and "taken over by operator-laptop" in taken["reason"], taken)
gate.refuse = {"gate": "lease_ended", "reason": "stopped_by page"}
nav.call("calibration.start", {"procedure": "odometry_scale", "params": {"seconds": 2}})
stopped = end_of()
check("a STOP ends it cancelled, saying who", stopped["state"] == "cancelled" and "stopped by page" in stopped["reason"], stopped)
gate.refuse, gate.factor = None, 0.0
nav.call("calibration.start", {"procedure": "odometry_scale", "params": {"seconds": 2}})
still = end_of()
check("a robot whose odometry did not move ends it failed, saying so", still["state"] == "failed" and "did not walk" in still["reason"], still)
check("the next goal is not refused by a finished calibration", nav.call("goal.start", {"kind": "nope"})["error"]["code"] == "unknown_kind")

if failures:
    print(f"FAIL test_calibration: {len(failures)} failed: {failures}")
    raise SystemExit(1)
print("PASS test_calibration")
