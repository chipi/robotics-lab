"""The duck's calibration procedures, behind the navigator API's calibration.* methods (contract 1.3, libs/runner/CONTRACT.md).

A procedure is a short, scripted motion that measures one number of the robot. The navigator drives it and reports what the robot's
own sensors said; it never reads the truth, so what the floor says (the reference) is its runner's or an operator's tape. One
procedure runs at a time, and never with a goal: either answers `busy` to the other.

    odometry_scale: walk straight at speed_mps for seconds, standing still at both ends; `measured.odom_m` is how far robotd's odometry
    says the robot went, between the marks `start` and `end` (the host's wall clock, the one a runner pairs its truth by).
    The scale is reference / odom_m, worked out by whoever has the reference (Mission Control)."""

import threading
import time

from duck_lab.nav import contract
from duck_lab.nav.client import LeaseLost, Rpc, StateStream
from duck_lab.profile import load as load_profile

TICK_S = 0.1            # a move every tick: robotd's deadman wants one inside 0.5 s
SETTLE_S = 1.5          # standing still before the start mark, and after the walk before the end mark: the marks read a still robot
MIN_ODOM_M = 0.2        # a walk the odometry saw less of is a robot that did not walk (not held, not on its feet)
SECONDS = (2.0, 30.0)   # what a walk may last

STEPS = {"odometry_scale": ("settle", "walk", "stop")}


def procedures(server) -> list:
    """What this navigator drives, each with the parameters it takes and their defaults (the profile version it runs)."""
    return [{"id": "odometry_scale", "params": defaults(server)}]


def defaults(server) -> dict:
    p = load_profile(server.variant, server.profile)
    speed = p.get("localisation.odometry.at_speed_mps") or p.get("locomotion.cruise_mps")
    return {"speed_mps": float(speed), "seconds": 8.0, "max_speed_mps": float(p.get("factsheet.physicalParameters.maximumSpeed", speed))}


def check_params(server, procedure: str, given: dict) -> dict:
    """The parameters a start runs with, or ValueError saying which is wrong."""
    if procedure not in STEPS:
        raise KeyError(procedure)
    base = defaults(server)
    unknown = set(given) - {"speed_mps", "seconds"}
    if unknown:
        raise ValueError(f"no parameter {sorted(unknown)[0]!r} (the parameters are speed_mps and seconds)")
    out = {k: given.get(k, base[k]) for k in ("speed_mps", "seconds")}
    for k, v in out.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{k} must be a number")
    if not 0 < out["speed_mps"] <= base["max_speed_mps"]:
        raise ValueError(f"speed_mps must be above 0 and at most {base['max_speed_mps']} (the robot's maximum speed)")
    if not SECONDS[0] <= out["seconds"] <= SECONDS[1]:
        raise ValueError(f"seconds must be between {SECONDS[0]:g} and {SECONDS[1]:g}")
    return {"speed_mps": float(out["speed_mps"]), "seconds": float(out["seconds"])}


class Calibration:
    """One run of a procedure: holds the robot's lease while it runs, on a thread of its own."""

    def __init__(self, server, procedure: str, params: dict):
        self.server, self.procedure, self.params = server, procedure, params
        self.state, self.step, self.reason = "running", None, None
        self.measured, self.marks = None, []
        self.cancelled = threading.Event()
        self._robot = self._stream = None

    def start(self) -> None:
        """The lease taken before the thread starts: a robot held by someone else is the start's refusal (LeaseLost), nothing began."""
        srv = self.server
        self._robot = Rpc(srv.robot_sock, client=srv.client)
        try:
            self._robot.call("gate.acquire")
            self._stream = StateStream(srv.robot_sock, hz=20, client=srv.client)
        except BaseException:
            self._close()
            raise
        threading.Thread(target=self._work, name=f"calibration-{self.procedure}", daemon=True).start()

    def cancel(self) -> None:
        self.cancelled.set()

    def snapshot(self) -> dict:
        return {"state": self.state, "procedure": self.procedure, "step": self.step, "reason": self.reason, "params": self.params,
                "measured": self.measured, "marks": list(self.marks)}

    # --- the walk -------------------------------------------------------------------------------

    def _move(self, vx: float) -> None:
        self._robot.call("robot.move", {"vx": vx, "vy": 0.0, "vyaw": 0.0})

    def _hold(self, seconds: float, vx: float = 0.0) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self.cancelled.is_set():
            self._move(vx)
            time.sleep(TICK_S)

    def _odom(self) -> list:
        end = time.monotonic() + 2.0
        while self._stream.latest is None and time.monotonic() < end:
            time.sleep(0.02)
        if self._stream.latest is None:
            raise RuntimeError("robotd sent no state: no odometry to measure")
        return list(self._stream.latest["odom"]["position"][:2])

    def _mark(self, name: str) -> list:
        at = self._odom()
        self.marks.append({"name": name, "wall_ns": time.time_ns(), "odom": at})
        return at

    def _work(self) -> None:
        state, reason = "done", None
        try:
            self.step = "settle"
            self._hold(SETTLE_S)
            start = self._mark("start")
            self.step = "walk"
            self._hold(self.params["seconds"], self.params["speed_mps"])
            self.step = "stop"
            self._hold(SETTLE_S)
            end = self._mark("end")
            moved = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
            if self.cancelled.is_set():
                state, reason = "cancelled", "cancelled by Mission Control"
            elif moved < MIN_ODOM_M:
                state, reason = "failed", f"the odometry moved {moved:.2f} m: the robot did not walk (is it standing, and free to move?)"
            else:
                self.measured = {"odom_m": round(moved, 4), "speed_mps": self.params["speed_mps"], "seconds": self.params["seconds"]}
        except LeaseLost as exc:
            state, reason = contract.of_lease(exc)
        except Exception as exc:                                  # noqa: BLE001 - a procedure's failure is its outcome
            state, reason = "failed", f"{type(exc).__name__}: {exc}"
        try:
            self._move(0.0)
        except (LeaseLost, RuntimeError, OSError):
            pass
        self._close()
        self.reason, self.step = reason, None
        self.state = state                                         # last: a poll that sees an end sees the rest

    def _close(self) -> None:
        for end in (lambda: self._robot.call("gate.release"), lambda: self._stream.close(), lambda: self._robot.close()):
            try:
                end()
            except (AttributeError, LeaseLost, RuntimeError, OSError):
                pass
