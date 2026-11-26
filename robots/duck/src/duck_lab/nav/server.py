"""The navigator API: the duck's navigator as its own process (RFC-0014 §3.7, O22), for Mission Control.

    python -m duck_lab.nav.server --robot GATE.sock --depth T.sock --map M.sock [--camera C.sock] --listen API.sock \
        --data DIR --out DIR

It is given only the robot's sockets and never reads the simulator's truth: in the simulator it runs behind its runner
(`lab-nav-server`, labrunner.navapi: RFC-0021 step 6, RFC-0022), which an operator starts, which Mission Control talks to, and
which keeps the truth, the truth guardrails and the official recording.

A small JSON-RPC server (newline framed, on a unix socket or TCP on loopback) that owns one `Navigator` per goal. Mission Control starts a goal
of any kind of RFC-0014 §3.4.1 with `goal.start`, polls `goal.status`, and cancels with `goal.cancel`. The server takes the
robot's lease from the gate at `goal.start` (the navigator is the process that sends `robot.move`, RFC-0017 §3.2) and gives
it back at the end of the run; STOP never goes through it. Every goal run is also an Observatory run, `duck/<scene>/mc<id>-...`,
which names its goal run in the run record (`goal_run`, apps/observatory/CONTRACT.md), and `goal.start` answers with its key at once.

It keeps the navigator contract (libs/runner/CONTRACT.md) as a navigator API. Methods:
  hello -> {name, version, contract, kinds, camera}
  goal.start {kind, params, budget, conditions {done_when, guardrails}, seed {objects, areas}, goal_run {id, name, kind}, scene?,
      not_enforced?}  (not_enforced since contract 1.2: guardrails its runner cannot check, one harness anomaly each, except from 1.4
      the contact, fall and drop_clearance this navigator checks by the robot's own sensors: guardrails.RobotSide;
      start_pose? {x, y, yaw} since 1.5: where the operator says the robot stands on the map, which sets the goal's frame)
      -> {run_key, profile, placed? {pose, frame}}, or {error} when another client holds the robot (the gate's own refusal), a goal is
      running here, or the start pose is not a pose or is inside a no-go area (bad_start_pose)
  goal.status {decisions_since, objects_since, anomalies_since} -> {state, reason, progress, result, broken, run_key, decisions: [...],
      decisions_n, anomalies: [...], anomalies_n, objects: [...] | null, objects_v}  (anomalies since contract 1.1)
  goal.cancel {reason?} -> {ok}
  goal.break {name, detail} -> {ok}: a guardrail its runner checks (by the truth) broke; the run stops stopped_by_guardrail
  goal.anomaly {kind, summary, values?} -> {ok}: an anomaly of the harness its runner measured (since contract 1.6: rtf_low), recorded once
      per kind in the run, source "harness"; the run goes on
  state -> the robot's latest state (while a goal runs)       objects -> the semantic map now (ADR-0019 shape)
  inventory -> RFC-0016's inventory                           map {units?} -> mapd's grid (in the placed frame of the latest goal that had a start pose);
                                                              units "site" (since 1.8): res_m and origin in true metres, answered with units "site"
  site_pose {odom {x, y, yaw}} -> {x, y, yaw, frame "site", placed} | {error bad_pose}: robotd's odometry pose (unscaled) in the site frame,
      placed by the latest goal's start pose and scaled by the odometry scale that goal ran (since 1.8; not the navigator's belief)
  calibration.list -> {procedures: [{id, params}]}            calibration.start {procedure, params?} -> {ok, procedure, params} | {error}
  calibration.status -> {state, procedure, step, reason, params, measured, marks}      calibration.cancel -> {ok}   (contract 1.3; duck_lab.nav.calibration)
`seed.objects` are Mission Control's confirmed objects of the site (their ids are Mission Control's; they come back as `seed`
beside the navigator's own ids), `seed.areas` the operator's outlines [{id, name, type, outline}].

States of a run: the contract's (running, then reached, done, refused, not_found, timeout, stalled, stopped_by_guardrail,
cancelled, interrupted, failed). The guardrails it checks are its own (the speed cap, the no-go area in the planner, the clock, stuck); the
ones only the truth can tell are its runner's (guardrails.TruthGuard), which breaks the run with `goal.break`. The kinds that
look for objects (go_to_object, inventory, explore) need the camera's socket."""

import argparse
import json
import math
import socketserver
import threading
import time
from pathlib import Path

from duck_lab.nav import calibration, contract
from duck_lab.nav.calibration import Calibration
from duck_lab.nav.client import LeaseLost, Rpc
from duck_lab.nav.explore_run import Explorer
from duck_lab.nav.frames import compose, move_grid
from duck_lab.nav.guardrails import ROBOT_SIDE, Guard, RobotSide
from duck_lab.nav.camera import CameraClient
from duck_lab.nav.run import Navigator, decision
from duck_lab.nav.runlog import RunLog
from duck_lab.profile import load as load_profile
from runfile.navcontract import CALIBRATION_METHODS, ENDS, HARNESS_ANOMALIES
from worldmodel.objects import load_kinds
from worldmodel.semantic_map import CONFIRM_N, SemanticMap
from worldmodel.site import Area, inside

NAME, VERSION = "duck-nav-server", "0.2.0"
GOAL_KINDS = ("point", "go_to_object", "go_to_area", "explore", "inventory")


def bad_start_pose(spec: dict) -> str | None:
    """Why `start_pose` (contract 1.5) cannot be taken, or None. No truth reads where the robot stands, so what can be checked is the
    word itself: three finite numbers, and not inside a no-go area the goal carries (the planner would refuse to leave it)."""
    sp = spec.get("start_pose")
    if sp is None:
        return None
    if not isinstance(sp, dict) or not all(isinstance(sp.get(k), (int, float)) and not isinstance(sp.get(k), bool)
                                           and math.isfinite(sp[k]) for k in ("x", "y", "yaw")):
        return "start_pose is {x, y, yaw}: metres in the map's frame and radians, all numbers"
    for g in (spec.get("conditions") or {}).get("guardrails") or []:
        if g.get("name") == "no_go_area" and g.get("outline") and inside((sp["x"], sp["y"]), [tuple(p) for p in g["outline"]]):
            return f"the start pose ({sp['x']:.2f}, {sp['y']:.2f}) is inside the no-go area {g.get('area')}"
    return None


def interior_point(polygon: list) -> tuple:
    """A point inside the outline: the centroid, else the middle of the longest chord at a few heights."""
    n = len(polygon)
    a = cx = cy = 0.0
    for i, (x0, y0) in enumerate(polygon):
        x1, y1 = polygon[(i + 1) % n]
        w = x0 * y1 - x1 * y0
        a += w
        cx += (x0 + x1) * w
        cy += (y0 + y1) * w
    if abs(a) > 1e-9:
        c = (cx / (3 * a), cy / (3 * a))
        if inside(c, polygon):
            return c
    ys = [p[1] for p in polygon]
    best, best_len = polygon[0], -1.0
    for k in range(1, 20):
        y = min(ys) + (max(ys) - min(ys)) * k / 20
        xs = sorted(x0 + (y - y0) * (x1 - x0) / (y1 - y0) for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1])
                    if (y0 > y) != (y1 > y))
        for j in range(0, len(xs) - 1, 2):
            if xs[j + 1] - xs[j] > best_len:
                best_len, best = xs[j + 1] - xs[j], ((xs[j] + xs[j + 1]) / 2, y)
    return best


class SeededMap(SemanticMap):
    """The site's objects at the start of a run, and `find` limited to an area when the goal names one."""

    only_in = None          # a polygon

    def find(self, name, pose=None):
        if self.only_in is None:
            return super().find(name, pose)
        real = self.confirmed
        self.confirmed = lambda: [o for o in real() if inside((o.x, o.y), self.only_in)]
        try:
            return super().find(name, pose)
        finally:
            del self.confirmed


def seed_map(objects: list, kinds: dict) -> tuple:
    """(a SeededMap of Mission Control's objects, {navigator id: Mission Control id}). An object of a kind the catalogue does
    not have is left out: the navigator could not recognise or approach it."""
    data, ids, count = [], {}, {}
    for o in objects:
        if o.get("kind") not in kinds or not o.get("parts"):
            continue
        count[o["kind"]] = count.get(o["kind"], 0) + 1
        nid = f"{o['kind']}_{count[o['kind']]}"
        ids[nid] = o["id"]
        label = o.get("label")
        data.append({"id": nid, "kind": o["kind"], "x": o["x"], "y": o["y"], "n": max(int(o.get("n", 1)), CONFIRM_N),
                     "parts": o["parts"], "first_t": 0.0, "last_t": 0.0, "confidence": o.get("confidence", 0.9),
                     "sources": ["site"], "evidence": [], "label": label, "named_by": "operator" if label else None,
                     "pinned": bool(label)})
    return SeededMap.from_json({"objects": data}, kinds), ids


class GoalRun:
    """One goal: its Observatory run, its navigator, its thread."""

    def __init__(self, server: "NavServer", spec: dict):
        self.server, self.spec = server, spec
        self.kind = spec["kind"]
        self.params = spec.get("params") or {}
        self.done_when = (spec.get("conditions") or {}).get("done_when") or {}
        self.guardrails = (spec.get("conditions") or {}).get("guardrails") or []
        self.robot_side: list = []       # the truth guardrails its runner could not check and this navigator checks by the robot (_arm_guardrails)
        self.goal_run = spec.get("goal_run") or {}
        self.state, self.reason, self.result, self.broken = "starting", None, None, None
        self.progress: dict = {}
        self.decisions: list = []
        self.anomalies: list = []        # the run's anomalies as written (RFC-0019 §2.1's record, with `t` and `n`), served live
        self.told: set = set()           # the harness anomalies its runner has told (harness_anomaly)
        self.objects_v = 0
        self.nav = None
        self.runlog = None
        self.run_key = None
        self.explorer = None
        self.cancelled: str | None = None
        self.placed: dict | None = None      # the start pose and the frame it set (`start_pose`, contract 1.5)
        self.t0 = time.monotonic()
        self.target = None
        self.seed_ids: dict = {}
        self.areas: list = []
        self.camera = None
        self._lock = threading.Lock()

    # --- starting ---------------------------------------------------------------------------------

    def start(self) -> str:
        srv = self.server
        label = self.goal_run.get("id", int(time.time()))
        name = f"mc{label}-{time.strftime('%Y%m%d-%H%M%S')}"
        out = srv.out / name
        out.mkdir(parents=True, exist_ok=True)
        self.runlog = RunLog(srv.data, self.spec.get("scene") or srv.scene, name, "goal-run", out,
                             goal_run={"id": int(label), "name": str(self.goal_run.get("name") or self.kind), "kind": self.kind,
                                       "robot": "duck"})
        self.run_key = self.runlog.key
        try:
            self.nav = Navigator(sockets=srv.sockets,
                                 log=out / "ticks.jsonl", runlog=self.runlog,
                                 client=srv.client, calibration=srv.variant, profile_path=srv.profile,
                                 depth_impairment=srv.depth_impairment)
        except BaseException:
            self.runlog.finish()
            raise
        self.nav.on_decision = self._on_decision
        self.nav.on_anomaly = self._on_anomaly
        self.nav.on_self_stop = self._noted
        self.out = out
        try:
            self.placed = self._place()
        except BaseException:
            self.nav.close()
            self.runlog.finish()
            raise
        self._prepare()
        for name in self.spec.get("not_enforced") or []:
            if name not in self.robot_side:
                self.nav.anomaly("guardrail_unenforced", f"the runner cannot check {name}: it has no truth", values={"guardrail": str(name)})
        self.state = "running"
        threading.Thread(target=self._work, name=f"goal-{label}", daemon=True).start()
        return self.run_key

    def _place(self) -> dict | None:
        """`start_pose` (contract 1.5): the robot's belief takes the operator's word for where it stands on the map. What it says is
        recorded as a decision of the run, so a run reads as one that was placed, not localised."""
        sp = self.spec.get("start_pose")
        if sp is None:
            return None
        place = getattr(self.nav.localisation, "place", None)
        if place is None:
            raise RuntimeError(f"the {self.nav.localisation.name} localisation of this robot cannot be placed on the map")
        pose = (float(sp["x"]), float(sp["y"]), float(sp["yaw"]))
        frame = [round(v, 4) for v in place(pose)]
        shown = {"x": pose[0], "y": pose[1], "yaw": pose[2], "frame": "site"}
        self.nav.record(event="placed", pose=list(pose), frame=frame,
                        decision=decision("placed", f"placed by the operator at ({pose[0]:.2f}, {pose[1]:.2f}) facing "
                                          f"{math.degrees(pose[2]):.0f} deg: no truth reads it, so the map's frame is set by this word",
                                          pose=list(pose), frame=frame))
        return {"pose": shown, "frame": {"x": frame[0], "y": frame[1], "yaw": frame[2]}}

    def _prepare(self) -> None:
        kinds = load_kinds()
        seed = self.spec.get("seed") or {}
        self.areas = [Area(a["id"], a["name"], [tuple(p) for p in a["outline"]], a.get("type")) for a in seed.get("areas", [])]
        semantic, self.seed_ids = seed_map(seed.get("objects", []), kinds)
        by_id = {a.aid: a for a in self.areas}
        if self.kind == "go_to_object" and self.params.get("area") in by_id:
            semantic.only_in = by_id[self.params["area"]].polygon
        cam = self.server.sockets.get("camera")
        if cam:
            self.camera = CameraClient(cam)
            self.nav.enable_objects(self.camera, kinds, semantic=semantic,
                                    area_at=lambda xy: next((a for a in self.areas if inside(xy, a.polygon)), None))
        self.kinds = kinds
        self._arm_guardrails()

    def _arm_guardrails(self) -> None:
        """The merged guardrails of the goal run (Mission Control's list: robot, site and goal level, strictest wins)."""
        cfg = self.nav.profile.get("robot_guards")
        robot = RobotSide(self.guardrails, self.spec.get("not_enforced") or [], cfg) if cfg else None
        robot = robot if robot and robot.names else None
        self.robot_side = robot.names if robot else []
        if self.robot_side:
            self.nav.record(event="guardrails_robot_side", names=self.robot_side,
                            decision=decision("guardrail", "the runner has no truth: the robot's own sensors check " + ", ".join(self.robot_side),
                                              guardrails=self.robot_side))
        left = [n for n in ROBOT_SIDE if n not in set(self.spec.get("not_enforced") or [])]      # the runner's truth judges these (E2)
        shadow = RobotSide(self.guardrails, left, cfg) if cfg else None
        shadow = shadow if shadow and shadow.names else None
        if shadow:
            self.nav.record(event="guardrails_robot_record", names=list(shadow.names),
                            decision=decision("guardrail", "the runner's truth judges " + ", ".join(shadow.names) + "; the robot's own sensors only record what they would have done",
                                              guardrails=list(shadow.names)))
        self.guard = Guard(self.nav, self.guardrails, self._break, self.t0, robot, shadow, self._would_break)
        self.guard.arm()

    def _would_break(self, name: str, detail: str) -> None:
        """The robot's own check of a guardrail its runner judges by the truth (E2) says it would have stopped the goal: a minor
        `robot_guard`, nothing else changes. Minor, not critical: the truth is the referee, and where it agrees its `guardrail_broken`
        is the critical one; this record is for the run's reader to see where the robot's sensors and the truth part."""
        self.nav.anomaly("robot_guard", f"the robot's own sensors would have stopped the goal ({name}); the runner's truth judges it: {detail}",
                         "minor", values={"guardrail": name, "detail": detail, "enforced": False})

    def _break(self, name: str, detail: str, by_runner: bool = False) -> None:
        """A guardrail broke: the run stops, with which one, and the decision says why (it is in the Observatory run too). `by_runner`:
        one its runner checks by the truth (`goal.break`), also an anomaly of the harness; the navigator's own (Guard) are rules doing
        their job (a time limit spent), not anomalies."""
        with self._lock:
            if self.broken is not None:
                return
            self.broken = {"name": name, "detail": detail}
        self.nav.record(event="guardrail", name=name, decision=decision("guardrail", f"guardrail broken: {detail}", guardrail=name,
                                                                        **({"side": "robot"} if name in self.robot_side else {})))
        if name in self.robot_side and not by_runner:
            self.nav.anomaly("robot_guard", f"the robot's own sensors stopped the goal ({name}): {detail}",
                             values={"guardrail": name, "detail": detail, "enforced": True})
        if by_runner:
            self.nav.anomaly("guardrail_broken", f"the runner's truth guard: {name}: {detail}", values={"guardrail": name, "detail": detail})
        self.nav.stop_goal("stopped_by_guardrail", f"guardrail {name}: {detail}")

    def harness_anomaly(self, kind: str, summary: str, values: dict) -> None:
        """An anomaly its runner measured (contract 1.6), once per kind: a runner tells it at every poll it holds, the run records it once."""
        with self._lock:
            if kind in self.told:
                return
            self.told.add(kind)
        self.nav.anomaly(kind, summary, values=values)

    def _noted(self, name: str, detail: str) -> None:
        """The navigator stopped the goal on the robot's own health (motor_hot, battery_low, robot_unhealthy, stale_stream): `broken`
        names it, as for a guardrail broken from outside; the navigator has recorded the event and does the stop."""
        with self._lock:
            if self.broken is None:
                self.broken = {"name": name, "detail": detail}

    # --- what a poll sees ---------------------------------------------------------------------------

    def _on_decision(self, row: dict) -> None:
        d = row["decision"]
        with self._lock:
            self.decisions.append({"n": len(self.decisions) + 1, "t": row.get("t"), "text": d.get("reason", ""),
                                   "rule": d.get("rule"), "values": d.get("values") or {}})
        if d.get("rule") == "stuck" and any(g["name"] == "stuck" for g in self.guardrails):
            self._break("stuck", d.get("reason", "walking without getting anywhere"))

    def _on_anomaly(self, row: dict) -> None:
        with self._lock:
            self.anomalies.append({**{k: v for k, v in row.items() if k != "event"}, "n": len(self.anomalies) + 1})

    def _objects(self) -> list:
        nav = self.nav
        if nav is None or nav.semantic is None:
            return []
        with nav._sem_lock:
            out = []
            for o in nav.semantic.objects:
                s = o.summary()
                s["seed"] = self.seed_ids.get(o.oid)
                s["unique"] = bool(self.kinds.get(o.kind, {}).get("unique"))
                out.append(s)
        return out

    def snapshot(self, decisions_since: int = 0, objects_since: int = -1, anomalies_since: int = 0) -> dict:
        objs = self._objects()
        version = hash(json.dumps([(o["id"], o["n"], o["confirmed"], round(o["x"], 1), round(o["y"], 1)) for o in objs])) & 0xFFFFFFF
        with self._lock:
            decisions = self.decisions[decisions_since:]
            n = len(self.decisions)
            anomalies, an = self.anomalies[anomalies_since:], len(self.anomalies)
        return {"state": self.state, "reason": self.reason, "progress": self._progress(), "result": self.result, "broken": self.broken,
                "run_key": self.run_key, "decisions": decisions, "decisions_n": n,
                "anomalies": anomalies, "anomalies_n": an,
                "objects": objs if version != objects_since else None, "objects_v": version}

    def _progress(self) -> dict:
        nav = self.nav
        if nav is None:
            return {}
        pose = nav.loc.pose()
        p = {"elapsed_s": round(time.monotonic() - self.t0, 1), "area": nav.area,
             "guardrails_ok": [g["name"] for g in self.guardrails if not self.broken], "guardrails_robot_side": self.robot_side}
        if pose is not None:
            p["pose"] = {"x": round(pose[0], 3), "y": round(pose[1], 3), "yaw": round(pose[2], 3), "frame": "site"}
            if self.target is not None:
                p["distance_left_m"] = round(math.dist(pose[:2], self.target), 3)
        if self.explorer is not None:
            p["legs"] = sum(1 for e in self.explorer.events if e.get("event") == "leg")
        return p

    # --- running --------------------------------------------------------------------------------------

    def cancel(self, reason: str | None = None) -> None:
        self.cancelled = reason or "cancelled by Mission Control"
        if self.nav is not None:
            self.nav.stop_goal("cancelled", self.cancelled)

    def _work(self) -> None:
        try:
            state, reason, result = getattr(self, f"_do_{self.kind}")()
        except LeaseLost as exc:
            if self.nav is not None:
                self.nav.lease_ended(exc)            # (said once: Navigator.move said it when its own command was the one refused)
            (state, reason), result = contract.of_lease(exc), None
        except Exception as exc:                                 # noqa: BLE001 - a goal's failure is its outcome
            state, reason, result = "failed", f"{type(exc).__name__}: {exc}", None
        state, reason = contract.settle(state, reason, self.broken, self.cancelled)
        self._finish(state, reason, result)

    def _finish(self, state: str, reason, result) -> None:
        nav = self.nav
        final_objects = self._objects()
        self.progress = self._progress()
        try:
            nav.close()
            if self.camera is not None:
                self.camera.close()
        except Exception:                                          # noqa: BLE001
            pass
        if nav.semantic is not None:
            with nav._sem_lock:
                (self.out / "semantic_map.json").write_text(json.dumps(nav.semantic.to_json(), indent=1))
        self.runlog.finish()
        self.final_objects = final_objects
        self.result, self.reason = result, reason
        self.state = state                                         # last: a poll that sees a terminal state sees the rest

    def _outcome(self, out: dict) -> tuple:
        return (*contract.of_go_to(out), None)              # _work turns a cancel or a guardrail into its own state

    def _within_s(self, default: float) -> float:
        return contract.within_s(self.spec, default)

    def _minutes(self) -> float:
        return contract.minutes(self.spec)

    def _do_point(self) -> tuple:
        x, y = float(self.params["x"]), float(self.params["y"])
        self.target = (x, y)
        return self._outcome(self.nav.go_to((x, y), self._within_s(contract.DEFAULT_POINT_S)))

    def _do_go_to_area(self) -> tuple:
        area = next((a for a in self.areas if a.aid == self.params["area"]), None)
        if area is None:
            return "refused", f"no area {self.params['area']!r} in the seed", None
        self.target = interior_point(area.polygon)
        out = self.nav.go_to(self.target, self._within_s(300.0))
        state, reason, result = self._outcome(out)
        pose = self.nav.loc.pose()
        if state == "reached" and (pose is None or not inside(pose[:2], area.polygon)):
            return "failed", f"stopped at {self.target[0]:.2f}, {self.target[1]:.2f}, which the belief puts outside the area", None
        return state, reason, result

    def _explorer(self) -> Explorer:
        self.explorer = Explorer(self.nav, self.out)
        return self.explorer

    def _ended_by(self, ex: Explorer) -> str | None:
        kinds = {e.get("event") for e in ex.events}
        if "no_frontier_left" in kinds:
            return "no_frontier_left"
        if "trapped" in kinds:
            return "trapped"
        return "budget"

    def _coverage(self, ex: Explorer, ended_by: str) -> dict:
        grid = self.nav.mapd.call("map.grid", {"res_m": 0.05})
        known = sum(1 for c in grid.get("cells", "") if c != "?")
        return {"cells_explored": known, "objects_found": len(self.nav.semantic.objects) if self.nav.semantic else 0, "ended_by": ended_by}

    def _do_go_to_object(self) -> tuple:
        p = self.params
        name = p.get("label") or p.get("id") or p.get("kind")
        sem = self.nav.semantic
        known = sem.kind_of(name) is not None or any(
            (o.label or "").lower() == name.strip().lower() or o.oid == name or self.seed_ids.get(o.oid) == name for o in sem.objects)
        if "id" in p:                                          # Mission Control's id: the seed's, by the navigator's own
            name = next((nid for nid, mid in self.seed_ids.items() if mid == p["id"]), p["id"])
            known = True
        if not known:
            return "not_found", f"no kind, label or id {name!r} the navigator knows", None
        ex = self._explorer()
        ex.find = name
        res = ex.run(self._minutes())
        found = res.get("found")
        if found and found.get("status") == "reached":
            o = next((o for o in sem.objects if o.oid == found["object"]), None)
            stand = found.get("stand") or []
            return "reached", None, {
                "object": {"id": o.oid, "seed": self.seed_ids.get(o.oid), "kind": o.kind, "x": round(o.x, 3), "y": round(o.y, 3),
                           "label": o.label, "frame": "site"},
                "stand": {"x": stand[0], "y": stand[1], "yaw": stand[2], "frame": "site"} if len(stand) >= 3 else None}
        tried = [e for e in ex.events if e.get("event") == "found" and e.get("status") not in ("not_found", None)]
        if tried:
            return "failed", f"the {tried[-1].get('kind')} was found but the robot could not get to it: {tried[-1].get('why')}", None
        if self._ended_by(ex) == "trapped":
            return "failed", "the robot was trapped while looking", None
        return "not_found", f"no {name} found; " + ("nothing left to explore" if self._ended_by(ex) == "no_frontier_left"
                                                      else "the budget is spent"), None

    def _do_explore(self) -> tuple:
        p = self.params
        ex = self._explorer()
        if "area" in p:
            area = next((a for a in self.areas if a.aid == p["area"]), None)
            if area is None:
                return "refused", f"no area {p['area']!r} in the seed", None
            ex.within = lambda xy: inside(xy, area.polygon)
        ex.run(self._minutes())
        ended = self._ended_by(ex)
        if ended == "trapped":
            return "failed", "the robot was trapped", None
        return "done", None, self._coverage(ex, ended)

    def _do_inventory(self) -> tuple:
        wanted = self.params.get("areas") or []
        ex = self._explorer()
        if wanted:
            polys = [a.polygon for a in self.areas if a.aid in wanted]
            ex.within = lambda xy: any(inside(xy, poly) for poly in polys)
        ex.run(self._minutes())
        ended = self._ended_by(ex)
        if ended == "trapped":
            return "failed", "the robot was trapped", None
        with self.nav._sem_lock:
            confirmed = list(self.nav.semantic.confirmed())

        def brief(o):
            return {"id": o.oid, "seed": self.seed_ids.get(o.oid), "kind": o.kind, "x": round(o.x, 3), "y": round(o.y, 3), "n": o.n,
                    "confidence": round(o.confidence, 2)}

        listed, placed = [], set()
        for a in self.areas:
            if wanted and a.aid not in wanted:
                continue
            objs = [o for o in confirmed if inside((o.x, o.y), a.polygon)]
            placed.update(o.oid for o in objs)
            listed.append({"area": a.aid, "name": a.name, "objects": [brief(o) for o in objs]})
        none = [brief(o) for o in confirmed if o.oid not in placed] if not wanted else []
        return "done", None, {"areas": listed, "none_defined": none, **self._coverage(ex, ended)}


class NavServer:
    def __init__(self, sockets: dict, data: Path, out: Path, scene: str = "apartment", client: str = "duck-nav-server",
                 variant: str | None = "sim", profile: Path | None = None, depth_impairment: int | None = None):
        # sockets: the navigator's ("robot": a gate's, "depth", "map", and "camera" when it has one), handed in by its runner
        self.sockets, self.data, self.out, self.scene, self.client = sockets, data, out, scene, client
        self.variant, self.profile = variant, profile       # the profile version every goal's navigator runs (phase 5 step 1)
        if depth_impairment is not None and variant != "sim":
            raise ValueError(f"--depth-impairment is the simulator's: the {variant or 'real'!r} duck's depth frames are not impaired")
        self.depth_impairment = {"enabled": True, "seed": depth_impairment} if depth_impairment is not None else None      # every goal's navigator's setting
        self.robot_sock = sockets["robot"]
        self.run: GoalRun | None = None
        self.placed_frame: dict | None = None       # the latest goal's start-pose frame, which `map` is answered in
        self.frame: tuple | None = None             # (that frame or None, the odometry scale that goal ran): one fact, read together by `site_pose`
        self._base_scale: float | None = None       # the scale of the profile this server hands its goals, before any goal has run
        self.calibration: Calibration | None = None
        self._lock = threading.Lock()

    def _gate_holder(self) -> str | None:
        """Who holds the robot now, asked before a run is created: a refusal must leave no empty run in the Observatory."""
        try:
            rpc = Rpc(self.robot_sock, client=self.client + "-probe")
        except OSError:
            return None
        try:
            return rpc.call("gate.who").get("holder")
        except RuntimeError:
            return None
        finally:
            rpc.close()

    def _map(self) -> dict:
        rpc = Rpc(Path(self.sockets["map"]))         # its own connection: the goal's mapd connection is its navigator's alone
        try:
            return rpc.call("map.grid", {"res_m": 0.05})
        finally:
            rpc.close()

    METHODS = ("hello", "goal.start", "goal.status", "goal.cancel", "goal.break", "goal.anomaly", "map", "state", "objects", "inventory", "site_pose") + CALIBRATION_METHODS

    def call(self, method: str, p: dict):
        if method not in self.METHODS:
            raise UnknownMethod(method)
        if method == "hello":
            return contract.hello(NAME, VERSION, GOAL_KINDS, bool(self.sockets.get("camera")))
        if method.startswith("calibration."):
            return self.calibrate(method, p)
        if method == "goal.start":
            return self.start(p)
        run = self.run
        if method == "goal.status":
            if run is None:
                return {"state": "idle", "reason": None, "result": None, "broken": None}
            return run.snapshot(int(p.get("decisions_since", 0)), int(p.get("objects_since", -1)), int(p.get("anomalies_since", 0)))
        if method == "goal.break":
            if run is not None and run.state not in ENDS:
                run._break(str(p.get("name") or "guardrail"), str(p.get("detail") or "broken, says the runner"), by_runner=True)
            return {"ok": True}
        if method == "goal.anomaly":
            kind = p.get("kind")
            if kind not in HARNESS_ANOMALIES:
                return {"error": {"code": "bad_anomaly", "message": f"the runner may tell {', '.join(HARNESS_ANOMALIES)}, not {kind!r}"}}
            if run is not None and run.state not in ENDS:
                run.harness_anomaly(kind, str(p.get("summary") or kind), p.get("values") or {})
            return {"ok": True}
        if method == "goal.cancel":
            if run is not None and run.state not in ENDS:
                run.cancel(p.get("reason"))
            return {"ok": True}
        if method == "map":
            grid = self._map()                  # the robot's map, between goals too: its clients never open mapd themselves
            f = self.placed_frame               # in the frame the latest goal's start pose set (mapd's metres, as the grid is)
            grid = move_grid(grid, (f["x"], f["y"], f["yaw"])) if f and grid.get("cells") else grid
            if p.get("units") == "site":        # the scale after the move, so the cells are those of the unscaled answer
                k = self._frame()[1]
                grid = {**grid, "res_m": grid["res_m"] * k, "origin": [v * k for v in grid["origin"]], "units": "site"}
            return grid
        if method == "site_pose":
            return self.site_pose(p)
        if method in ("state", "objects", "inventory"):
            if run is None or run.nav is None or run.state in ENDS:
                return {"error": "no goal is running"} if method != "objects" else {"objects": []}
            nav = run.nav
            if method == "state":
                return nav.state.latest or {}
            if method == "objects":
                return {"objects": run._objects()}
            if method == "inventory":
                with nav._sem_lock:
                    return nav.semantic.inventory(nav._map_raw)
        raise KeyError(method)

    def _frame(self) -> tuple:
        if self.frame is None and self._base_scale is None:
            self._base_scale = float(load_profile(self.variant, self.profile).localisation.odometry.scale)
        return self.frame or (None, self._base_scale)

    def site_pose(self, p: dict) -> dict:
        """robotd's odometry pose in the site frame: the frame the latest goal's start pose set (none: mapd's), true metres by the
        scale that goal ran (not the belief's by_speed steps or fixes: this is the odometry, as the page has always shown it)."""
        o = p.get("odom")
        try:
            pose = tuple(o[k] for k in ("x", "y", "yaw"))
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in pose):
                raise ValueError
        except (TypeError, KeyError, ValueError):
            return {"error": {"code": "bad_pose", "message": "odom is {x, y, yaw}: three finite numbers"}}
        placed, k = self._frame()
        frame = (placed["x"] * k, placed["y"] * k, placed["yaw"]) if placed else (0.0, 0.0, 0.0)
        x, y, yaw = compose(frame, (pose[0] * k, pose[1] * k, pose[2]))
        return {"x": x, "y": y, "yaw": yaw, "frame": "site", "placed": placed is not None}

    def start(self, spec: dict) -> dict:
        with self._lock:
            if self.run is not None and self.run.state not in ENDS:
                return {"error": {"code": "busy", "message": "a goal is running here"}}
            if self.calibration is not None and self.calibration.state == "running":
                return {"error": {"code": "busy", "message": "a calibration is running here"}}
            if spec.get("kind") in ("go_to_object", "inventory") and not self.sockets.get("camera"):
                return {"error": {"code": "no_camera", "message": f"a {spec['kind']} goal looks for objects: this navigator has no camera"}}
            if spec.get("kind") not in GOAL_KINDS:
                return {"error": {"code": "unknown_kind", "message": f"no goal kind {spec.get('kind')!r}"}}
            why = bad_start_pose(spec)
            if why:
                return {"error": {"code": "bad_start_pose", "message": why}}
            holder = self._gate_holder()
            if holder not in (None, self.client, self.client + "-probe"):
                return {"error": {"code": "held", "message": f"driven by {holder}", "holder": holder}}
            run = GoalRun(self, spec)
            try:
                key = run.start()
            except LeaseLost as exc:
                return {"error": {"code": exc.code, "message": str(exc), "holder": exc.holder}}
            except Exception as exc:                                # noqa: BLE001
                return {"error": {"code": "start_failed", "message": f"{type(exc).__name__}: {exc}"}}
            self.run = run
            self.placed_frame = run.placed["frame"] if run.placed else None
            self.frame = (self.placed_frame, run.nav.scale)
            meta = getattr(run.nav.profile, "meta", None) or {}
            # the profile this goal runs, as its run records it: a client scaling the robot's poses checks it reads the same one
            answer = {"run_key": key, "profile": {k: meta.get(k) for k in ("checksum", "version", "source")}}
            if run.placed:
                answer["placed"] = run.placed          # a client that sent a start pose and reads none here was not heard (a 1.4 navigator)
            return answer

    def calibrate(self, method: str, p: dict) -> dict:
        """calibration.list / start / status / cancel (contract 1.3): one procedure at a time, never with a goal."""
        cal = self.calibration
        if method == "calibration.list":
            return {"procedures": calibration.procedures(self)}
        if method == "calibration.status":
            return cal.snapshot() if cal is not None else {"state": "idle", "procedure": None, "step": None, "reason": None, "params": None,
                                                           "measured": None, "marks": []}
        if method == "calibration.cancel":
            if cal is not None and cal.state == "running":
                cal.cancel()
            return {"ok": True}
        with self._lock:
            if (self.run is not None and self.run.state not in ENDS) or (cal is not None and cal.state == "running"):
                return {"error": {"code": "busy", "message": "a goal or a calibration is running here"}}
            procedure = p.get("procedure")
            try:
                params = calibration.check_params(self, procedure, p.get("params") or {})
            except KeyError:
                return {"error": {"code": "unknown_procedure", "message": f"no procedure {procedure!r} (it has {[x['id'] for x in calibration.procedures(self)]})"}}
            except ValueError as exc:
                return {"error": {"code": "bad_params", "message": str(exc)}}
            holder = self._gate_holder()
            if holder not in (None, self.client, self.client + "-probe"):
                return {"error": {"code": "held", "message": f"driven by {holder}", "holder": holder}}
            run = Calibration(self, procedure, params)
            try:
                run.start()
            except LeaseLost as exc:
                return {"error": {"code": exc.code, "message": str(exc), "holder": exc.holder}}
            except Exception as exc:                                # noqa: BLE001
                return {"error": {"code": "start_failed", "message": f"{type(exc).__name__}: {exc}"}}
            self.calibration = run
            return {"ok": True, "procedure": procedure, "params": params}


class UnknownMethod(KeyError):
    """The one KeyError that means "no such method"; any other KeyError in a handler is a bug and an internal error."""


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        for line in self.rfile:
            try:
                req = json.loads(line)
                result = self.server.nav.call(req["method"], req.get("params") or {})
                reply = {"jsonrpc": "2.0", "id": req.get("id"), "result": result}
            except UnknownMethod as exc:
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32601, "message": f"no method {exc}"}}
            except Exception as exc:                                # noqa: BLE001
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}
            try:
                self.wfile.write((json.dumps(reply) + "\n").encode())
                self.wfile.flush()
            except OSError:
                return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, nav: NavServer):
        super().__init__(addr, Handler)
        self.nav = nav


class UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, nav: NavServer):
        super().__init__(path, Handler)
        self.nav = nav


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for k, what in (("robot", "the robot's socket: a gate's"), ("depth", "the depth sensor's socket"), ("map", "mapd's socket")):
        ap.add_argument(f"--{k}", type=Path, required=True, help=what)
    ap.add_argument("--camera", type=Path, help="the camera's socket (the host's, RFC-0021 step 6); none: no goal that looks for objects")
    ap.add_argument("--listen", required=True, help="a unix socket's path, or host:port (loopback: the API has no login)")
    ap.add_argument("--client", default="duck-nav-server", help="the name the navigator takes the lease under")
    ap.add_argument("--data", type=Path, required=True, help="where each goal run's own run is written (its runner copies it on)")
    ap.add_argument("--out", type=Path, default=Path("state/nav"), help="the navigator's own output folders, one per goal run")
    ap.add_argument("--scene", default="apartment", help="the Observatory scene of the runs")
    ap.add_argument("--variant", default="sim", help="the robot profile's variant (sim, or real)")
    ap.add_argument("--profile", type=Path, help="the profile version to run (its runner's choice, phase 5 step 1); default the robot's own")
    ap.add_argument("--depth-impairment", type=int, metavar="SEED", help="the simulated depth sensor's impairments on, with this seed (the simulator only)")
    args = ap.parse_args()
    sockets = {"robot": args.robot, "depth": args.depth, "map": args.map, **({"camera": args.camera} if args.camera else {})}
    nav = NavServer(sockets, args.data, args.out, args.scene, args.client, None if args.variant == "real" else args.variant,
                    args.profile, args.depth_impairment)
    if "/" in args.listen:
        Path(args.listen).unlink(missing_ok=True)
        srv = UnixServer(args.listen, nav)
    else:
        listen, _, port = args.listen.rpartition(":")
        srv = Server((listen or "127.0.0.1", int(port)), nav)
    print(f"navigator API: {args.listen}, robot {sockets['robot']}, runs in {args.data}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if "/" in args.listen:
            Path(args.listen).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
