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
  goal.start {kind, params, budget, conditions {done_when, guardrails}, seed {objects, areas}, goal_run {id, name, kind}, scene?}
      -> {run_key}, or {error} when another client holds the robot (the gate's own refusal), or a goal is running here
  goal.status {decisions_since, objects_since} -> {state, reason, progress, result, broken, run_key, decisions: [...],
      decisions_n, objects: [...] | null, objects_v}
  goal.cancel {reason?} -> {ok}
  goal.break {name, detail} -> {ok}: a guardrail its runner checks (by the truth) broke; the run stops stopped_by_guardrail
  state -> the robot's latest state (while a goal runs)       objects -> the semantic map now (ADR-0019 shape)
  inventory -> RFC-0016's inventory                           map -> mapd's grid
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

from duck_lab.nav import contract
from duck_lab.nav.client import LeaseLost, Rpc
from duck_lab.nav.explore_run import Explorer
from duck_lab.nav.guardrails import Guard
from duck_lab.nav.camera import CameraClient
from duck_lab.nav.run import Navigator, decision
from duck_lab.nav.runlog import RunLog
from runfile.navcontract import ENDS
from worldmodel.objects import load_kinds
from worldmodel.semantic_map import CONFIRM_N, SemanticMap
from worldmodel.site import Area, inside

NAME, VERSION = "duck-nav-server", "0.2.0"
GOAL_KINDS = ("point", "go_to_object", "go_to_area", "explore", "inventory")


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
        self.goal_run = spec.get("goal_run") or {}
        self.state, self.reason, self.result, self.broken = "starting", None, None, None
        self.progress: dict = {}
        self.decisions: list = []
        self.objects_v = 0
        self.nav = None
        self.runlog = None
        self.run_key = None
        self.explorer = None
        self.cancelled: str | None = None
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
                                 client=srv.client, calibration=srv.variant, profile_path=srv.profile)
        except BaseException:
            self.runlog.finish()
            raise
        self.nav.on_decision = self._on_decision
        self.out = out
        self._prepare()
        self.state = "running"
        threading.Thread(target=self._work, name=f"goal-{label}", daemon=True).start()
        return self.run_key

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
        self.guard = Guard(self.nav, self.guardrails, self._break, self.t0)
        self.guard.arm()

    def _break(self, name: str, detail: str) -> None:
        """A guardrail broke: the run stops, with which one, and the decision says why (it is in the Observatory run too)."""
        with self._lock:
            if self.broken is not None:
                return
            self.broken = {"name": name, "detail": detail}
        self.nav.record(event="guardrail", name=name, decision=decision("guardrail", f"guardrail broken: {detail}", guardrail=name))
        self.nav.stop_goal("stopped_by_guardrail", f"guardrail {name}: {detail}")

    # --- what a poll sees ---------------------------------------------------------------------------

    def _on_decision(self, row: dict) -> None:
        d = row["decision"]
        with self._lock:
            self.decisions.append({"n": len(self.decisions) + 1, "t": row.get("t"), "text": d.get("reason", ""),
                                   "rule": d.get("rule"), "values": d.get("values") or {}})
        if d.get("rule") == "stuck" and any(g["name"] == "stuck" for g in self.guardrails):
            self._break("stuck", d.get("reason", "walking without getting anywhere"))

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

    def snapshot(self, decisions_since: int = 0, objects_since: int = -1) -> dict:
        objs = self._objects()
        version = hash(json.dumps([(o["id"], o["n"], o["confirmed"], round(o["x"], 1), round(o["y"], 1)) for o in objs])) & 0xFFFFFFF
        with self._lock:
            decisions = self.decisions[decisions_since:]
            n = len(self.decisions)
        return {"state": self.state, "reason": self.reason, "progress": self._progress(), "result": self.result, "broken": self.broken,
                "run_key": self.run_key, "decisions": decisions, "decisions_n": n,
                "objects": objs if version != objects_since else None, "objects_v": version}

    def _progress(self) -> dict:
        nav = self.nav
        if nav is None:
            return {}
        pose = nav.loc.pose()
        p = {"elapsed_s": round(time.monotonic() - self.t0, 1), "area": nav.area,
             "guardrails_ok": [g["name"] for g in self.guardrails if not self.broken]}
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
                 variant: str | None = "sim", profile: Path | None = None):
        # sockets: the navigator's ("robot": a gate's, "depth", "map", and "camera" when it has one), handed in by its runner
        self.sockets, self.data, self.out, self.scene, self.client = sockets, data, out, scene, client
        self.variant, self.profile = variant, profile       # the profile version every goal's navigator runs (phase 5 step 1)
        self.robot_sock = sockets["robot"]
        self.run: GoalRun | None = None
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

    METHODS = ("hello", "goal.start", "goal.status", "goal.cancel", "goal.break", "map", "state", "objects", "inventory")

    def call(self, method: str, p: dict):
        if method not in self.METHODS:
            raise KeyError(method)
        if method == "hello":
            return contract.hello(NAME, VERSION, GOAL_KINDS, bool(self.sockets.get("camera")))
        if method == "goal.start":
            return self.start(p)
        run = self.run
        if method == "goal.status":
            if run is None:
                return {"state": "idle", "reason": None, "result": None, "broken": None}
            return run.snapshot(int(p.get("decisions_since", 0)), int(p.get("objects_since", -1)))
        if method == "goal.break":
            if run is not None and run.state not in ENDS:
                run._break(str(p.get("name") or "guardrail"), str(p.get("detail") or "broken, says the runner"))
            return {"ok": True}
        if method == "goal.cancel":
            if run is not None and run.state not in ENDS:
                run.cancel(p.get("reason"))
            return {"ok": True}
        if method == "map":
            return self._map()                  # the robot's map, between goals too: its clients never open mapd themselves
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

    def start(self, spec: dict) -> dict:
        with self._lock:
            if self.run is not None and self.run.state not in ENDS:
                return {"error": {"code": "busy", "message": "a goal is running here"}}
            if spec.get("kind") in ("go_to_object", "inventory") and not self.sockets.get("camera"):
                return {"error": {"code": "no_camera", "message": f"a {spec['kind']} goal looks for objects: this navigator has no camera"}}
            if spec.get("kind") not in GOAL_KINDS:
                return {"error": {"code": "unknown_kind", "message": f"no goal kind {spec.get('kind')!r}"}}
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
            meta = getattr(run.nav.profile, "meta", None) or {}
            # the profile this goal runs, as its run records it: a client scaling the robot's poses checks it reads the same one
            return {"run_key": key, "profile": {k: meta.get(k) for k in ("checksum", "version", "source")}}


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        for line in self.rfile:
            try:
                req = json.loads(line)
                result = self.server.nav.call(req["method"], req.get("params") or {})
                reply = {"jsonrpc": "2.0", "id": req.get("id"), "result": result}
            except KeyError as exc:
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
    args = ap.parse_args()
    sockets = {"robot": args.robot, "depth": args.depth, "map": args.map, **({"camera": args.camera} if args.camera else {})}
    nav = NavServer(sockets, args.data, args.out, args.scene, args.client, None if args.variant == "real" else args.variant,
                    args.profile)
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
