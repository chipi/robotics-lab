"""The fake robot (RFC-0014 §3.7, RFC-0017 §5 step 2): a point that moves, answers status, honours STOP
and the deadman, can be told to drop offline or to fail, and carries a fake site with a few objects.
It lets Mission Control be built and tested with no simulator.

`FakeRobot` is the robot's own interface, in the shape of RFC-0003 (`robot.move`, `robot.stop`,
`robot.state`, `robot.health`): a callable robot(method, params). `FakeNavigator` is the goal runner
beside it, with the navigator API of RFC-0014 §3.7 (goal_start, goal_status, goal_cancel); like the duck's
nav server it holds the gate's lease while a run moves the robot. Time comes from an injected clock, so
the tests run a minute of robot time in no time at all."""

import math
import threading
import time
from collections import deque

from robotgate import Gate, GateError

from . import geometry

DEFAULT_WORLD = {
    "bounds": [-4.0, -3.0, 4.0, 3.0],
    "dock": [0.0, 0.0, 0.0],
    "sight_range_m": 2.0,
    "cell_m": 0.5,
    "objects": [
        {"kind": "fridge", "x": 3.0, "y": 1.5, "hx": 0.4, "hy": 0.35, "height": 1.8, "landmark": 0.9, "unique": True},
        {"kind": "sofa", "x": -2.5, "y": -1.5, "hx": 0.9, "hy": 0.4, "height": 0.8, "landmark": 0.8, "unique": False},
        {"kind": "desk", "x": -2.5, "y": 1.8, "hx": 0.6, "hy": 0.3, "height": 0.75, "landmark": 0.3, "unique": False},
        {"kind": "plant", "x": 1.0, "y": -2.2, "hx": 0.2, "hy": 0.2, "height": 1.0, "landmark": 0.2, "unique": False},
    ],
    # where the fake explores: it visits these in order and looks twice at each
    "sweep": [[2.2, 1.2], [1.0, -1.6], [-1.8, -1.0], [-1.8, 1.4]],
}

LOOKS_PER_STOP = 2  # an object is confirmed after this many sightings (the fake's rule)
CONFIRM_N = 2
STUCK_S = 3.0
STUCK_EPS = 0.02
REACH_WAYPOINT_M = 0.15
FACE_TOL_RAD = math.radians(10.0)


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


class FakeRobot:
    """The robot. Everything it does between two calls is worked out when the next call arrives, from
    the clock: a move command lasts `deadman_s`, as on the duck (RFC-0003 §2.3)."""

    def __init__(self, world: dict | None = None, *, clock=time.monotonic, max_vx: float = 0.5,
                 max_vyaw: float = 1.5, deadman_s: float = 0.5):
        self.world = {**DEFAULT_WORLD, **(world or {})}
        self.clock = clock
        self.max_vx, self.max_vyaw, self.deadman_s = max_vx, max_vyaw, deadman_s
        self.x, self.y, self.yaw = self.world["dock"]
        self.vx = self.vyaw = 0.0
        self._last_cmd = None
        self._t = clock()
        self._moved_m = 0.0
        self._lock = threading.RLock()
        self.offline = False
        self.hang = None  # a threading.Event: calls wait for it, to model a robot that stops answering
        self.flags = {"contact": False, "fall": False, "near_drop": False}
        self.wheels_locked = False  # the robot is told to move and does not: the navigator must notice
        self.explored: set = set()
        self.seen: set = set()
        self.map_version = 0
        self._last_cell = None
        self.calls = deque(maxlen=500)

    # --- the robot's own interface ---------------------------------------------------------------

    def __call__(self, method: str, params: dict | None = None):
        if self.hang is not None:
            self.hang.wait()
        with self._lock:
            if self.offline:
                raise ConnectionError("the fake robot is offline")
            self._advance()
            self.calls.append((method, params))
            if method == "robot.move":
                p = params or {}
                self.vx = max(-self.max_vx, min(self.max_vx, float(p.get("vx", 0.0))))
                self.vyaw = max(-self.max_vyaw, min(self.max_vyaw, float(p.get("vyaw", 0.0))))
                self._last_cmd = self.clock() if (self.vx or self.vyaw) else None
                return {"ok": True, "applied": {"vx": self.vx, "vyaw": self.vyaw}}
            if method == "robot.stop":
                self.vx = self.vyaw = 0.0
                self._last_cmd = None
                return {"ok": True}
            if method == "robot.state":
                return self._state()
            if method == "robot.health":
                return {"ok": True, "battery_pct": self._battery(), "link": "fake"}
            raise ValueError(f"the fake robot has no method {method}")

    def _battery(self) -> float:
        return round(max(0.0, 100.0 - 0.5 * self._moved_m), 2)

    def _state(self) -> dict:
        moving = self._last_cmd is not None
        return {
            "pose": {"x": round(self.x, 4), "y": round(self.y, 4), "yaw": round(self.yaw, 4), "frame": "site"},
            "velocity": {"vx": self.vx, "vyaw": self.vyaw},
            "mode": "moving" if moving else "idle",
            "battery_pct": self._battery(),
            "link": "fake",
            "flags": dict(self.flags),
        }

    def _advance(self) -> None:
        now = self.clock()
        t0, self._t = self._t, now
        if now <= t0:
            return
        if self._last_cmd is None:
            self._mark_explored()
            return
        dead = self._last_cmd + self.deadman_s
        moving_until = min(now, dead)
        dt = max(0.0, moving_until - t0)
        if not self.wheels_locked and dt > 0:
            steps = max(1, min(10000, math.ceil(dt / 0.02)))
            h = dt / steps
            x0, y0 = self.x, self.y
            bx0, by0, bx1, by1 = self.world["bounds"]
            for _ in range(steps):
                self.yaw = _wrap(self.yaw + self.vyaw * h)
                self.x = min(bx1, max(bx0, self.x + self.vx * math.cos(self.yaw) * h))
                self.y = min(by1, max(by0, self.y + self.vx * math.sin(self.yaw) * h))
                self._mark_explored()
            self._moved_m += math.hypot(self.x - x0, self.y - y0)
        if now >= dead:
            self.vx = self.vyaw = 0.0
            self._last_cmd = None

    def _mark_explored(self) -> None:
        cell = self.world["cell_m"]
        bx0, by0 = self.world["bounds"][:2]
        c = (int((self.x - bx0) // cell), int((self.y - by0) // cell))
        if c == self._last_cell:
            return
        self._last_cell = c
        reach = 2  # cells: about a metre of sensor reach at the default cell size
        before = len(self.explored)
        for i in range(c[0] - reach, c[0] + reach + 1):
            for j in range(c[1] - reach, c[1] + reach + 1):
                if (i - c[0]) ** 2 + (j - c[1]) ** 2 <= reach * reach and self._in_grid(i, j):
                    self.explored.add((i, j))
        if len(self.explored) != before:
            self.map_version += 1

    def _in_grid(self, i: int, j: int) -> bool:
        w, h = self._grid_size()
        return 0 <= i < w and 0 <= j < h

    def _grid_size(self) -> tuple:
        bx0, by0, bx1, by1 = self.world["bounds"]
        cell = self.world["cell_m"]
        return math.ceil((bx1 - bx0) / cell), math.ceil((by1 - by0) / cell)

    # --- what only the fake has -----------------------------------------------------------------

    def set_offline(self, offline: bool = True) -> None:
        self.offline = offline

    def inject(self, flag: str, on: bool = True) -> None:
        """A fault the navigator's guardrails watch for: contact, fall or near_drop."""
        if flag not in self.flags:
            raise KeyError(flag)
        self.flags[flag] = on

    def pose(self) -> tuple:
        with self._lock:
            self._advance()
            return self.x, self.y, self.yaw

    def sight(self) -> list:
        """What the fake camera recognises now: the objects of the fake site within its range."""
        with self._lock:
            self._advance()
            out = []
            for idx, o in enumerate(self.world["objects"]):
                d = math.hypot(o["x"] - self.x, o["y"] - self.y)
                if d <= self.world["sight_range_m"]:
                    if idx not in self.seen:
                        self.seen.add(idx)
                        self.map_version += 1
                    out.append({"idx": idx, "distance": d, **o})
            return out

    def sighting(self) -> dict:
        """The latest sighting record (ADR-0019): the camera's pose, its field of view, the detections
        with x ahead and y left, relative to the robot."""
        with self._lock:
            self._advance()
            seen = []
            for o in self.world["objects"]:
                dx, dy = o["x"] - self.x, o["y"] - self.y
                rx = dx * math.cos(self.yaw) + dy * math.sin(self.yaw)
                ry = -dx * math.sin(self.yaw) + dy * math.cos(self.yaw)
                rng = math.hypot(rx, ry)
                if rng <= self.world["sight_range_m"] and abs(math.atan2(ry, rx)) <= math.radians(60):
                    seen.append({"kind": o["kind"], "x": round(rx, 3), "y": round(ry, 3), "range_m": round(rng, 3),
                                 "radius": max(o["hx"], o["hy"]), "z0": 0.0, "z1": o["height"], "confidence": 0.9})
            return {"frame": "site", "pose": [round(self.x, 4), round(self.y, 4), round(self.yaw, 4)], "hfov_deg": 120.0,
                    "range_m": self.world["sight_range_m"], "seen": seen}

    def map(self) -> dict:
        """A coarse occupancy grid: -1 unexplored, 0 free, 100 an object the camera has seen."""
        with self._lock:
            self._advance()
            cell = self.world["cell_m"]
            bx0, by0 = self.world["bounds"][:2]
            w, h = self._grid_size()
            data = [-1] * (w * h)
            for i, j in self.explored:
                data[j * w + i] = 0
            for idx in self.seen:
                o = self.world["objects"][idx]
                for j in range(h):
                    for i in range(w):
                        cx, cy = bx0 + (i + 0.5) * cell, by0 + (j + 0.5) * cell
                        if abs(cx - o["x"]) <= o["hx"] + cell / 2 and abs(cy - o["y"]) <= o["hy"] + cell / 2:
                            data[j * w + i] = 100
            return {"frame": "site", "kind": "occupancy_grid", "resolution_m": cell, "origin": [bx0, by0],
                    "width": w, "height": h, "data": data, "version": self.map_version}


class _Refused(Exception):
    pass


class _Run:
    def __init__(self, spec: dict, t0: float):
        self.spec = spec
        self.t0 = t0
        self.state = "running"
        self.reason = None
        self.result = None
        self.broken = None
        self.lost = None
        self.gen = None
        self.pose = (0.0, 0.0, 0.0)
        self.target = None  # (x, y) the robot is heading for, for the progress
        self.found = None  # the object a go_to_object run settled on
        self.objs: dict = {}  # the fake camera's map of this run, keyed by the world's index
        self.moving_cmd = False
        self.ref_pose = None
        self.ref_t = t0
        self.stuck_said = False
        self.visited = 0
        self.progress: dict = {}


class FakeNavigator:
    """The fake's goal runner. One run at a time. `step()` is called about ten times a second; each call
    reads the robot's state through the gate, checks the guardrails and sends one `robot.move`."""

    CLIENT = "fake-navigator"

    def __init__(self, robot: FakeRobot, gate: Gate, clock=time.monotonic):
        self.robot, self.gate, self.clock = robot, gate, clock
        self.run: _Run | None = None
        self._cid = None
        self._on_decision = lambda text, **data: None
        self._on_objects = lambda objs: None

    def bind(self, on_decision, on_objects) -> None:
        self._on_decision, self._on_objects = on_decision, on_objects

    # --- the navigator API (RFC-0014 §3.7) ------------------------------------------------------

    def goal_start(self, spec: dict) -> dict:
        """spec: {kind, params, budget?, conditions: {done_when, guardrails}, seed: {objects, areas}}.
        Returns {run_key} (None: the fake writes no Observatory run) or refuses with its reason."""
        if self.run is not None and self.run.state == "running":
            raise RuntimeError("a goal is running")
        r = _Run(spec, self.clock())
        self.run = r
        try:
            self._plan_start(r)
        except _Refused as exc:
            r.state, r.reason = "refused", str(exc)
            return {"run_key": None}
        self._cid = self.gate.open(self.CLIENT, lambda method, params: self._lease_lost(r, params))
        try:
            self.gate.handle(self._cid, "gate.acquire")
        except GateError as exc:
            self.gate.close(self._cid)
            r.state, r.reason = "refused", str(exc)
            return {"run_key": None}
        r.gen = self._script(r)
        self._decide(f"goal {spec['kind']} started")
        return {"run_key": None}

    def goal_status(self) -> dict:
        r = self.run
        if r is None:
            return {"state": "idle"}
        return {"state": r.state, "reason": r.reason, "progress": dict(r.progress), "result": r.result,
                "broken": r.broken}

    def goal_cancel(self) -> None:
        r = self.run
        if r is not None and r.state == "running":
            self._finish(r, "cancelled", "cancelled by Mission Control", None)

    def step(self) -> None:
        r = self.run
        if r is None or r.state != "running":
            return
        now = self.clock()
        elapsed = now - r.t0
        if r.lost:
            self._end_lost(r)
            return
        try:
            state = self.gate.handle(self._cid, "robot.state")
        except GateError as exc:
            self._refused_by_gate(r, exc)
            return
        except Exception as exc:
            self._finish(r, "interrupted", f"the robot stopped answering: {exc}", None)
            return
        p = state["pose"]
        r.pose = (p["x"], p["y"], p["yaw"])
        self._watch(r, state, now, elapsed)
        if r.state != "running":
            return
        r.progress = self._progress(r, elapsed)
        try:
            outcome = next(r.gen)
        except StopIteration as done:
            outcome = done.value
        except GateError as exc:
            self._refused_by_gate(r, exc)
            return
        except _Refused as exc:
            self._finish(r, "refused", str(exc), None)
            return
        if outcome is not None and r.state == "running":
            self._finish(r, *outcome)

    # --- guardrails, deadlines, stuck --------------------------------------------------------------

    def _watch(self, r: _Run, state: dict, now: float, elapsed: float) -> None:
        guards = {g["name"]: g for g in r.spec["conditions"]["guardrails"]}
        flags = state["flags"]
        for name, flag in (("contact", "contact"), ("fall", "fall"), ("drop_clearance", "near_drop")):
            if name in guards and flags.get(flag):
                self._break(r, name, f"{name}: the robot reports {flag}")
                return
        for g in r.spec["conditions"]["guardrails"]:
            if g["name"] == "no_go_area" and geometry.point_in_polygon([r.pose[0], r.pose[1]], g["outline"]):
                self._break(r, "no_go_area", f"the robot is inside the no-go area {g['area']}")
                return
        within = r.spec["conditions"]["done_when"].get("within_s")
        limit = guards["time_limit"]["seconds"] if "time_limit" in guards else None
        if limit is not None and elapsed > limit and (within is None or limit <= within):
            self._break(r, "time_limit", f"the time limit of {limit:g} s is spent")
            return
        if within is not None and elapsed > within:
            if r.spec["kind"] == "go_to_object" and r.found is None:
                self._finish(r, "not_found", f"no {self._what(r)} found within {within:g} s", None)
            else:
                self._finish(r, "timeout", f"the time limit of {within:g} s was spent before it was reached", None)
            return
        moved = r.ref_pose is None or math.hypot(r.pose[0] - r.ref_pose[0], r.pose[1] - r.ref_pose[1]) > STUCK_EPS \
            or abs(_wrap(r.pose[2] - r.ref_pose[2])) > 0.05
        if moved or not r.moving_cmd:
            r.ref_pose, r.ref_t = r.pose, now
        elif now - r.ref_t > STUCK_S:
            if "stuck" in guards:
                self._break(r, "stuck", f"no progress for {STUCK_S:g} s while commanded to move")
            elif not r.stuck_said:
                r.stuck_said = True
                self._decide("stuck: no progress while commanded to move; stuck is not in this goal's guardrails, so it goes on")

    def _break(self, r: _Run, name: str, detail: str) -> None:
        r.broken = {"name": name, "detail": detail}
        self._decide(f"guardrail broken: {detail}", guardrail=name)
        self._finish(r, "stopped_by_guardrail", detail, None)

    # --- finishing ---------------------------------------------------------------------------------

    def _finish(self, r: _Run, state: str, reason: str | None, result, *, release: bool = True) -> None:
        if r.state != "running":
            return
        r.state, r.reason, r.result = state, reason, result
        if release and self._cid is not None:
            try:
                self.gate.handle(self._cid, "gate.release")
            except Exception:
                pass
        if self._cid is not None:
            self.gate.close(self._cid)
            self._cid = None
        self._decide(f"ended {state}" + (f": {reason}" if reason else ""))

    def _lease_lost(self, r: _Run, params: dict) -> None:
        r.lost = params.get("reason") or "lease lost"

    def _end_lost(self, r: _Run) -> None:
        """The lease is gone: a STOP cancels the run, a takeover or anything else interrupts it."""
        if r.lost.startswith("taken_over_by"):
            self._finish(r, "interrupted", f"the robot was {r.lost.replace('_', ' ')}", None, release=False)
        elif r.lost.startswith("stopped_by"):
            self._finish(r, "cancelled", f"{r.lost.replace('_', ' ')}", None, release=False)
        else:
            self._finish(r, "interrupted", f"the lease ended: {r.lost}", None, release=False)

    def _refused_by_gate(self, r: _Run, exc: GateError) -> None:
        # The gate's lease-lost callback and Mission Control's ticker race: when step() reaches the gate first, the refusal
        # carries the same reason the callback would have (2026-11-20: STOP ALL read "interrupted" 1 run in 4).
        if exc.code == "lease_ended":
            r.lost = r.lost or exc.data.get("reason") or "lease lost"
            self._end_lost(r)
        else:
            self._finish(r, "interrupted", str(exc), None, release=False)

    def _decide(self, text: str, **data) -> None:
        self._on_decision(text, **data)

    # --- planning at the start -------------------------------------------------------------------

    def _seed_areas(self, r: _Run) -> dict:
        return {a["id"]: a for a in r.spec["seed"]["areas"]}

    def _no_go(self, r: _Run) -> list:
        return [g for g in r.spec["conditions"]["guardrails"] if g["name"] == "no_go_area"]

    def _check_path(self, r: _Run, a, b) -> None:
        for g in self._no_go(r):
            if geometry.segment_hits_polygon(a, b, g["outline"]):
                raise _Refused(f"no path that avoids the no-go area {g['area']}")

    def _plan_start(self, r: _Run) -> None:
        kind, p = r.spec["kind"], r.spec["params"]
        bx0, by0, bx1, by1 = self.robot.world["bounds"]
        here = self.robot.pose()
        if kind == "point":
            tx, ty = p["x"], p["y"]
            if not (bx0 <= tx <= bx1 and by0 <= ty <= by1):
                raise _Refused("no path: the point is outside the world")
            for o in self.robot.world["objects"]:
                if abs(tx - o["x"]) <= o["hx"] and abs(ty - o["y"]) <= o["hy"]:
                    raise _Refused(f"no path: the point is inside a {o['kind']}")
            self._check_path(r, here[:2], (tx, ty))
        elif kind == "go_to_area":
            outline = self._seed_areas(r)[p["area"]]["outline"]
            self._check_path(r, here[:2], geometry.interior_point(outline))

    # --- the scripts: one generator per goal, one yield per tick -----------------------------------

    def _script(self, r: _Run):
        kind = r.spec["kind"]
        return getattr(self, f"_do_{kind}")(r)

    def _cmd(self, r: _Run, vx: float, vyaw: float) -> None:
        cap = self.robot.max_vx
        for g in r.spec["conditions"]["guardrails"]:
            if g["name"] == "max_speed":
                cap = min(cap, g["mps"])
        vx = max(-cap, min(cap, vx))
        r.moving_cmd = abs(vx) > 0.02 or abs(vyaw) > 0.1
        self.gate.handle(self._cid, "robot.move", {"vx": vx, "vy": 0.0, "vyaw": vyaw})

    def _goto(self, r: _Run, tx: float, ty: float, reach: float) -> bool:
        """One tick of driving to (tx, ty); True when within `reach` of it."""
        x, y, yaw = r.pose
        r.target = (tx, ty)
        dist = math.hypot(tx - x, ty - y)
        if dist <= reach:
            self._cmd(r, 0.0, 0.0)
            return True
        err = _wrap(math.atan2(ty - y, tx - x) - yaw)
        vmax = self.robot.max_vyaw
        if abs(err) > 0.35:
            self._cmd(r, 0.0, max(-vmax, min(vmax, 2.0 * err)))
        else:
            self._cmd(r, dist, max(-vmax, min(vmax, 2.0 * err)))
        return False

    def _face(self, r: _Run, tx: float, ty: float) -> bool:
        x, y, yaw = r.pose
        err = _wrap(math.atan2(ty - y, tx - x) - yaw)
        if abs(err) <= FACE_TOL_RAD:
            self._cmd(r, 0.0, 0.0)
            return True
        vmax = self.robot.max_vyaw
        self._cmd(r, 0.0, max(-vmax, min(vmax, 2.0 * err)))
        return False

    def _progress(self, r: _Run, elapsed: float) -> dict:
        x, y, yaw = r.pose
        areas = [a for a in r.spec["seed"]["areas"] if geometry.point_in_polygon([x, y], a["outline"])]
        area = min(areas, key=lambda a: geometry.area(a["outline"]))["id"] if areas else None
        prog = {"elapsed_s": round(elapsed, 1), "pose": {"x": round(x, 3), "y": round(y, 3), "yaw": round(yaw, 3), "frame": "site"},
                "area": area, "guardrails_ok": [g["name"] for g in r.spec["conditions"]["guardrails"]]}
        if r.target is not None:
            prog["distance_left_m"] = round(math.hypot(r.target[0] - x, r.target[1] - y), 3)
        if r.spec["kind"] in ("explore", "inventory"):
            prog["waypoints_visited"] = r.visited
            prog["cells_explored"] = len(self.robot.explored)
        return prog

    def _do_point(self, r: _Run):
        p, reach = r.spec["params"], r.spec["conditions"]["done_when"]["within_m"]
        self._decide(f"heading for ({p['x']:g}, {p['y']:g})")
        while not self._goto(r, p["x"], p["y"], reach * 0.8):
            yield
        self._decide("reached the point")
        return "reached", None, None

    def _do_go_to_area(self, r: _Run):
        area = self._seed_areas(r)[r.spec["params"]["area"]]
        target = geometry.interior_point(area["outline"])
        self._decide(f"heading for a free point inside {area['name']}", area=area["id"])
        while not geometry.point_in_polygon([r.pose[0], r.pose[1]], area["outline"]):
            self._goto(r, target[0], target[1], 0.05)
            yield
        self._cmd(r, 0.0, 0.0)
        self._decide(f"inside {area['name']}")
        return "reached", None, None

    # the fake camera: what a look adds to this run's map, and a report of the whole map (ADR-0019)

    def _look(self, r: _Run) -> None:
        for o in self.robot.sight():
            have = r.objs.get(o["idx"])
            if have is None:
                have = r.objs[o["idx"]] = {"id": f"nav-{o['idx']}", "kind": o["kind"], "x": o["x"], "y": o["y"],
                                           "hx": o["hx"], "hy": o["hy"], "height": o["height"], "landmark": o["landmark"],
                                           "unique": o["unique"], "n": 0, "confirmed": False, "confidence": 0.0,
                                           "parts": [[o["x"], o["y"], o["hx"], o["hy"], 0.0, 0.0, o["height"]]]}
                self._decide(f"saw a {o['kind']} at ({o['x']:g}, {o['y']:g})", object_kind=o["kind"])
            have["n"] += 1
            have["confidence"] = round(min(0.95, 0.5 + 0.15 * have["n"]), 2)
            if have["n"] >= CONFIRM_N and not have["confirmed"]:
                have["confirmed"] = True
                self._decide(f"confirmed the {o['kind']}", object_kind=o["kind"])
        self._on_objects([dict(o) for o in r.objs.values()])

    def _sweep(self, r: _Run, waypoints: list, budget_s: float, stop_when=None):
        """Visit the waypoints, looking twice at each. Returns why it ended."""
        for wx, wy in waypoints:
            if self._skip_waypoint(r, wx, wy):
                continue
            self._decide(f"picked the waypoint ({wx:g}, {wy:g})")
            while not self._goto(r, wx, wy, REACH_WAYPOINT_M):
                yield
                if self.clock() - r.t0 > budget_s:
                    return "budget"
            r.visited += 1
            for _ in range(LOOKS_PER_STOP):
                self._look(r)
                yield
            if stop_when is not None and stop_when():
                return "found"
            if self.clock() - r.t0 > budget_s:
                return "budget"
        self._decide("no frontier left")
        return "no_frontier_left"

    def _skip_waypoint(self, r: _Run, wx: float, wy: float) -> bool:
        for g in self._no_go(r):
            if geometry.segment_hits_polygon(r.pose[:2], (wx, wy), g["outline"]):
                self._decide(f"skipped ({wx:g}, {wy:g}): the path would enter the no-go area {g['area']}")
                return True
        return False

    def _waypoints(self, r: _Run, areas: list | None) -> list:
        sweep = self.robot.world["sweep"]
        if areas is None:
            return list(sweep)
        outlines = [self._seed_areas(r)[a]["outline"] for a in areas]
        return [w for w in sweep if any(geometry.point_in_polygon(w, o) for o in outlines)]

    def _coverage(self, r: _Run, ended_by: str) -> dict:
        return {"cells_explored": len(self.robot.explored), "objects_found": len(r.objs), "ended_by": ended_by}

    def _do_explore(self, r: _Run):
        p = r.spec["params"]
        waypoints = self._waypoints(r, [p["area"]] if "area" in p else None)
        ended = yield from self._sweep(r, waypoints, r.spec["budget"]["minutes"] * 60.0)
        return "done", None, self._coverage(r, "budget" if ended == "budget" else "no_frontier_left")

    def _do_inventory(self, r: _Run):
        areas = r.spec["params"]["areas"] or None
        waypoints = self._waypoints(r, areas)
        ended = yield from self._sweep(r, waypoints, r.spec["budget"]["minutes"] * 60.0)
        seed_areas = list(self._seed_areas(r).values())
        confirmed = [o for o in r.objs.values() if o["confirmed"]]
        brief = lambda o: {"id": o["id"], "kind": o["kind"], "x": o["x"], "y": o["y"], "n": o["n"], "confidence": o["confidence"]}
        listed = []
        for a in seed_areas:
            if areas is None or a["id"] in areas:
                listed.append({"area": a["id"], "name": a["name"],
                               "objects": [brief(o) for o in confirmed if geometry.point_in_polygon([o["x"], o["y"]], a["outline"])]})
        inside = {o["id"] for entry in listed for o in entry["objects"]}
        result = {"areas": listed, "none_defined": [brief(o) for o in confirmed if o["id"] not in inside] if areas is None else [],
                  **self._coverage(r, "budget" if ended == "budget" else "no_frontier_left")}
        return "done", None, result

    # go_to_object: the site's map first, then exploring until one is confirmed (RFC-0014 §3.4.1)

    def _what(self, r: _Run) -> str:
        p = r.spec["params"]
        return p.get("label") or p.get("id") or p.get("kind")

    def _candidates(self, r: _Run) -> list:
        p = r.spec["params"]
        pool = [dict(o) for o in r.spec["seed"]["objects"]] + [o for o in r.objs.values() if o["confirmed"]]
        if "label" in p:
            pool = [o for o in pool if (o.get("label") or "").lower() == p["label"].lower()]
        elif "id" in p:
            pool = [o for o in pool if o["id"] == p["id"]]
        else:
            pool = [o for o in pool if o["kind"] == p["kind"]]
        if "area" in p:
            outline = self._seed_areas(r)[p["area"]]["outline"]
            pool = [o for o in pool if geometry.point_in_polygon([o["x"], o["y"]], outline)]
        x, y, _ = r.pose
        return sorted(pool, key=lambda o: math.hypot(o["x"] - x, o["y"] - y))

    def _do_go_to_object(self, r: _Run):
        done_when = r.spec["conditions"]["done_when"]
        found = self._candidates(r)
        if not found:
            self._decide(f"no {self._what(r)} in the site's map; exploring to find one")
            budget_s = r.spec["budget"]["minutes"] * 60.0
            yield from self._sweep(r, self._waypoints(r, None), budget_s, stop_when=lambda: bool(self._candidates(r)))
            found = self._candidates(r)
            if not found:
                return "not_found", f"no {self._what(r)} found; nothing left to explore or the budget is spent", None
        obj = r.found = found[0]
        self._decide(f"going to the {obj['kind']} {obj['id']}", object=obj["id"])
        half = max(obj.get("hx", 0.3), obj.get("hy", 0.3))
        x, y, _ = r.pose
        d = math.hypot(obj["x"] - x, obj["y"] - y) or 1.0
        stand_d = half + 0.25
        stand = (obj["x"] - (obj["x"] - x) / d * stand_d, obj["y"] - (obj["y"] - y) / d * stand_d)
        self._check_path(r, (x, y), stand)
        while not self._goto(r, stand[0], stand[1], 0.1):
            yield
        while not self._face(r, obj["x"], obj["y"]):
            yield
        x, y, yaw = r.pose
        gap = math.hypot(obj["x"] - x, obj["y"] - y) - half
        facing = abs(math.degrees(_wrap(math.atan2(obj["y"] - y, obj["x"] - x) - yaw)))
        if gap > done_when["within_m"] or facing > done_when["facing_deg"]:
            return "failed", f"stood {gap:.2f} m from the outline facing {facing:.0f} degrees off: outside the goal's limits", None
        self._decide(f"at the {obj['kind']}: {gap:.2f} m from its outline, {facing:.0f} degrees off")
        return "reached", None, {"object": {k: obj[k] for k in ("id", "kind", "x", "y")} | {"label": obj.get("label"), "frame": "site"},
                                 "stand": {"x": round(x, 3), "y": round(y, 3), "yaw": round(yaw, 3), "frame": "site"}}


class FakeAdapter:
    """What Mission Control needs of any robot's adapter (RFC-0014 §3.3.1): `call` (the robot's own
    interface), `make_navigator(gate, clock)`, `map()` and `sighting()`. The robot file's
    adapter options: {"type": "fake", "world": {...}}; the limits are the factsheet's maximumSpeed and maximumAngularSpeed and the
    control block's deadman_s."""

    def __init__(self, cfg, clock=time.monotonic):
        options = cfg.adapter
        limits = cfg.factsheet.get("physicalParameters", {})
        self.robot = FakeRobot(options.get("world"), clock=clock, max_vx=limits.get("maximumSpeed", 0.5),
                               max_vyaw=limits.get("maximumAngularSpeed", 1.5), deadman_s=cfg.control["deadman_s"])
        self.call = self.robot

    def make_navigator(self, gate: Gate, clock=time.monotonic) -> FakeNavigator:
        return FakeNavigator(self.robot, gate, clock)

    def map(self) -> dict:
        return self.robot.map()

    def map_version(self) -> int:
        return self.robot.map_version

    def sighting(self) -> dict:
        return self.robot.sighting()
