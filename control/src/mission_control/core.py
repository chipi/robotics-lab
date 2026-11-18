"""Mission Control's core (RFC-0014 §3): the robots behind their gates, the goal library, goal runs, the
sites. No HTTP in here: `api.py` is one client of this, a test is another.

Time is injected (`clock` for durations, `wall` for stamps), and `tick()` is what moves things on: in
service each robot has its own thread calling `tick_robot`, so a robot that stops answering holds up
only itself (§3.3.1); a test calls `tick()` by hand with a fake clock."""

import threading
import time
from pathlib import Path

from . import goals, guardrails
from .errors import ApiError, conflict, invalid, not_found
from .events import EventBus
from .robots import RobotRuntime, make_adapter
from .sites import Sites
from .store import Store, dumps, loads

TICK_S = 0.1
PROGRESS_EVERY_S = 1.0
STOP_ALL_WAIT_S = 3.0


class ActiveRun:
    """The goal run on a robot now."""

    def __init__(self, run_id: int, goal: dict, site_id: str | None):
        self.id, self.goal, self.site_id = run_id, goal, site_id
        self.assoc: dict = {}  # navigator object ids -> the site's (sites.merge_run_objects)
        self.decisions = 0
        self.last_progress = None


def _map_ids(value, ids: dict):
    """Rewrite the navigator's object ids in a run's result to the site's stable ones."""
    if isinstance(value, dict):
        return {k: (ids.get(v, v) if k == "id" and isinstance(v, str) else _map_ids(v, ids)) for k, v in value.items()}
    if isinstance(value, list):
        return [_map_ids(v, ids) for v in value]
    return value


class MissionControl:
    def __init__(self, robot_configs: list, *, state_dir=None, clock=time.monotonic, wall=time.time):
        self.clock, self.wall = clock, wall
        self.state_dir = Path(state_dir) if state_dir else None
        self.store = Store(self.state_dir / "mission-control.sqlite" if self.state_dir else None)
        self.bus = EventBus(wall)
        self.sites = Sites(self.store, wall)
        self.robots: dict = {}
        for cfg in robot_configs:
            rt = RobotRuntime(cfg, make_adapter(cfg, clock), clock=clock, wall=wall, bus=self.bus,
                              log_dir=self.state_dir)
            if rt.navigator is not None:
                rt.navigator.bind(lambda text, rt=rt, **data: self._decision(rt, text, data),
                                  lambda objs, rt=rt: self._objects(rt, objs))
            self.robots[cfg.id] = rt
        self._threads: list = []
        self._stopping = threading.Event()

    # --- running -------------------------------------------------------------------------------------

    def tick(self) -> None:
        for rt in self.robots.values():
            self.tick_robot(rt)

    def tick_robot(self, rt: RobotRuntime) -> None:
        rt.poll()
        rt.gate.tick()
        with rt.mutex:
            act, nav = rt.active, rt.navigator
            if nav is None or act is None:
                return
            nav.step()
            self._sync(rt, act)

    def start(self) -> None:
        """One thread per robot."""
        for rt in self.robots.values():
            t = threading.Thread(target=self._loop, args=(rt,), name=f"robot-{rt.cfg.id}", daemon=True)
            t.start()
            self._threads.append(t)

    def _loop(self, rt: RobotRuntime) -> None:
        while not self._stopping.is_set():
            try:
                self.tick_robot(rt)
            except Exception as exc:
                self.bus.emit("error", robot=rt.cfg.id, message=f"{type(exc).__name__}: {exc}")
            self._stopping.wait(TICK_S)

    def close(self) -> None:
        self._stopping.set()
        self.bus.wake()
        for t in self._threads:
            t.join(timeout=2.0)
        self.store.close()

    # --- robots --------------------------------------------------------------------------------------

    def robot(self, rid: str) -> RobotRuntime:
        rt = self.robots.get(rid)
        if rt is None:
            raise not_found("robot", rid)
        return rt

    def _age(self, rt: RobotRuntime):
        return None if rt.link.ok_at is None else round(self.clock() - rt.link.ok_at, 2)

    def robot_brief(self, rt: RobotRuntime) -> dict:
        return {"id": rt.cfg.id, "label": rt.cfg.label, "kind": rt.cfg.kind, "online": rt.online(),
                "lock": rt.gate.who(), "last_seen_age_s": self._age(rt)}

    def robot_view(self, rt: RobotRuntime) -> dict:
        return {**self.robot_brief(rt), "capabilities": rt.cfg.capabilities, "status": rt.status,
                "guardrails": rt.cfg.guardrails, "rates": rt.cfg.rates, "site": self.sites.robot_site(rt.cfg.id),
                "goal_run": rt.active.id if rt.active else None}

    def list_robots(self) -> list:
        return [self.robot_brief(rt) for rt in self.robots.values()]

    def get_robot(self, rid: str) -> dict:
        return self.robot_view(self.robot(rid))

    def assign_site(self, rid: str, site) -> dict:
        rt = self.robot(rid)
        if rt.active:
            raise conflict("robot_busy", f"goal run {rt.active.id} holds this robot")
        self.sites.assign_robot(rid, site)
        return self.robot_view(rt)

    def stop(self, rid: str, client: str = "api") -> dict:
        rt = self.robot(rid)
        result = rt.stop(client)
        self._after_stop(rt)
        return result

    def stop_all(self, client: str = "api") -> dict:
        """Every robot at once (§3.8): a failing or silent robot is reported and the others still stop."""
        results: dict = {}

        def one(rt):
            try:
                results[rt.cfg.id] = self.stop(rt.cfg.id, client)
            except Exception as exc:
                results[rt.cfg.id] = {"robot": rt.cfg.id, "confirmed": False, "error": f"{type(exc).__name__}: {exc}"}

        workers = [threading.Thread(target=one, args=(rt,), daemon=True) for rt in self.robots.values()]
        for w in workers:
            w.start()
        deadline = self.clock() + STOP_ALL_WAIT_S
        for w in workers:
            w.join(max(0.0, deadline - self.clock()))
        out = [results.get(rid, {"robot": rid, "confirmed": False, "error": f"no answer in {STOP_ALL_WAIT_S:g} s"})
               for rid in self.robots]
        self.bus.emit("stop-all", client=client, robots=out)
        return {"robots": out, "all_confirmed": all(r["confirmed"] for r in out)}

    def _after_stop(self, rt: RobotRuntime) -> None:
        """A STOP latches (RFC-0017 §3.4): the run's lease is gone, so it ends `cancelled` now, not at the
        next tick."""
        with rt.mutex:
            if rt.active and rt.navigator is not None:
                settle = getattr(rt.navigator, "settle", None)
                if settle is not None:
                    settle(3.0)            # a navigator in its own process sees the lost lease at its next tick
                rt.navigator.step()
                self._sync(rt, rt.active)

    # --- the goal library -----------------------------------------------------------------------------

    def _goal_view(self, row: dict) -> dict:
        return {"id": row["id"], **loads(row["spec"]), "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def _folder_clash(self, goal: dict, except_id: int | None = None) -> None:
        for r in self.store.all("SELECT id, name, folder FROM goals WHERE retired = 0"):
            if r["id"] != except_id and r["folder"] == goal["folder"] and r["name"].lower() == goal["name"].lower():
                raise conflict("name_taken", f"the folder {goal['folder'] or '/'} has a goal called {goal['name']!r}")

    def create_goal(self, spec) -> dict:
        goal = goals.validate(spec)
        with self.store.transaction():
            self._folder_clash(goal)
            now = self.wall()
            gid = self.store.execute("INSERT INTO goals (name, folder, spec, created_at, updated_at) VALUES (?,?,?,?,?)",
                                     (goal["name"], goal["folder"], dumps(goal), now, now))
        return self.get_goal(gid)

    def _goal_row(self, gid) -> dict:
        row = self.store.one("SELECT * FROM goals WHERE id = ? AND retired = 0", (gid,)) if isinstance(gid, int) else None
        if row is None:
            raise not_found("goal", gid)
        return row

    def get_goal(self, gid: int) -> dict:
        return self._goal_view(self._goal_row(gid))

    def list_goals(self, folder: str | None = None) -> list:
        rows = self.store.all("SELECT * FROM goals WHERE retired = 0 ORDER BY folder, name")
        if folder is not None:
            folder = goals.normalise_folder(folder)
            rows = [r for r in rows if folder == "" or r["folder"] == folder or r["folder"].startswith(folder + "/")]
        return [self._goal_view(r) for r in rows]

    def _running_goal(self, gid: int) -> None:
        for rt in self.robots.values():
            if rt.active and self.store.one("SELECT goal_id FROM goal_runs WHERE id = ?", (rt.active.id,))["goal_id"] == gid:
                raise conflict("goal_running", f"goal run {rt.active.id} of this goal is running")

    def update_goal(self, gid: int, spec) -> dict:
        self._goal_row(gid)
        self._running_goal(gid)
        goal = goals.validate(spec)
        with self.store.transaction():
            self._folder_clash(goal, gid)
            self.store.execute("UPDATE goals SET name = ?, folder = ?, spec = ?, updated_at = ? WHERE id = ?",
                               (goal["name"], goal["folder"], dumps(goal), self.wall(), gid))
        return self.get_goal(gid)

    def retire_goal(self, gid: int) -> None:
        self._goal_row(gid)
        self._running_goal(gid)
        self.store.execute("UPDATE goals SET retired = 1, updated_at = ? WHERE id = ?", (self.wall(), gid))

    # --- goal runs ------------------------------------------------------------------------------------

    def run_goal(self, gid: int, body) -> dict:
        row = self._goal_row(gid)
        return self._start_run(loads(row["spec"]), body, gid)

    def run_adhoc(self, body) -> dict:
        if not isinstance(body, dict) or "goal" not in body:
            raise invalid("body is {goal, robots, target}")
        return self._start_run(body["goal"], body, None)

    def _site_of(self, body: dict, rt: RobotRuntime):
        site = body.get("site") or self.sites.robot_site(rt.cfg.id)
        if site is not None:
            self.sites.get(site)
        return site

    def _area_id(self, site_id, ref: str) -> str:
        """An area of the run's site by id or name. Raises ValueError with the reason when there is none."""
        if site_id is None:
            raise ValueError("this goal names an area and the run has no site")
        try:
            return self.sites.area(site_id, ref)["id"]
        except ApiError:
            raise ValueError(f"no area {ref!r} in this site") from None

    def _canonical(self, site_id, goal: dict) -> dict:
        """The goal's params with every area by id."""
        p = dict(goal["params"])
        if "area" in p:
            p["area"] = self._area_id(site_id, p["area"])
        if "areas" in p:
            p["areas"] = [self._area_id(site_id, a) for a in p["areas"]]
        return p

    def _start_run(self, goal_spec, body, goal_id) -> dict:
        if not isinstance(body, dict):
            raise invalid("body is {robots, target, site?}")
        if body.get("team") is not None:
            raise ApiError(501, "not_built", "teams are RFC-0014 step 5; name one robot in robots")
        robots = body.get("robots")
        if not isinstance(robots, list) or not robots or not all(isinstance(r, str) for r in robots):
            raise invalid("robots is a list with the id of the robot to run on")
        if len(robots) > 1:
            raise ApiError(501, "not_built", "one goal on several robots (share: each, any) is RFC-0014 step 5")
        rt = self.robot(robots[0])
        target = body.get("target", "sim")
        if target not in ("sim", "real"):
            raise invalid("target is 'sim' or 'real'")
        if target == "real" and rt.cfg.kind == "fake":
            raise invalid("the fake robot is not a real robot")
        goal = goals.validate(goal_spec, require_name=False)
        site_id = self._site_of(body, rt)
        if not rt.online():
            raise ApiError(503, "robot_offline", f"{rt.cfg.id} is offline: nothing was queued", robot=rt.cfg.id)
        with rt.mutex:
            if rt.active:
                raise conflict("robot_busy", f"goal run {rt.active.id} holds {rt.cfg.id}", goal_run=rt.active.id)
            return self._create_and_start(rt, goal, goal_id, site_id, target)

    def _create_and_start(self, rt: RobotRuntime, goal: dict, goal_id, site_id, target) -> dict:
        reason = None
        goal_guards = []
        for g in goal["must_not"]:
            if g["name"] == "no_go_area":
                try:
                    g = {"name": "no_go_area", "area": self._area_id(site_id, g["area"])}
                except ValueError as exc:
                    reason = reason or str(exc)
                    continue
            goal_guards.append(g)
        levels = {"robot": rt.cfg.guardrails, "goal": goal_guards}
        if site_id is not None:
            levels["site"] = self.sites.guardrails(site_id)
        merged = guardrails.merge(levels)
        caps = rt.cfg.capabilities
        conditions = {"done_when": goal["done_when"], "not_checkable": goals.not_checkable(caps, goal)}
        now = self.wall()
        run_id = self.store.execute(
            "INSERT INTO goal_runs (goal_id, goal, robot, site_id, target, state, guardrails, conditions, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (goal_id, dumps(goal), rt.cfg.id, site_id, target, "queued", dumps(merged), dumps(conditions), now))
        self.bus.emit("goal-run", robot=rt.cfg.id, goal_run=run_id, state="queued")
        reason = reason or goals.capability_refusal(caps, goal, merged, has_site=site_id is not None)
        params = None
        if reason is None:
            try:
                params = self._canonical(site_id, goal)
                for g in merged:
                    if g["name"] == "no_go_area":
                        g["outline"] = self._outline(site_id, g["area"])
            except ValueError as exc:
                reason = str(exc)
        if reason is not None:
            self._end_run(run_id, rt, goal, "refused", reason, None, None, None)
            return self.get_run(run_id)
        seed = self.sites.seed(site_id) if site_id is not None else {"objects": [], "areas": []}
        if site_id is not None and (rt.status or {}).get("pose") and caps.get("localisation", {}).get("how") == "dock":
            self.sites.set_dock_if_unset(site_id, {**rt.status["pose"], "robot": rt.cfg.id})
        rt.active = ActiveRun(run_id, goal, site_id)
        spec = {"kind": goal["kind"], "params": params, "budget": goal.get("budget"),
                "conditions": {"done_when": goal["done_when"], "guardrails": merged}, "seed": seed,
                "goal_run": {"id": run_id, "name": goal["name"], "kind": goal["kind"], "robot": rt.cfg.id, "site": site_id}}
        try:
            started = rt.navigator.goal_start(spec)
        except Exception as exc:
            rt.active = None
            self._end_run(run_id, rt, goal, "failed", f"the navigator did not start the goal: {exc}", None, None, None)
            return self.get_run(run_id)
        status = rt.navigator.goal_status()
        if status["state"] == "refused":
            self._end_run(run_id, rt, goal, "refused", status.get("reason"), None, None, None)
            return self.get_run(run_id)
        self.store.execute("UPDATE goal_runs SET state = 'running', started_at = ?, run_key = ? WHERE id = ?",
                           (self.wall(), started.get("run_key"), run_id))
        self.bus.emit("goal-run", robot=rt.cfg.id, goal_run=run_id, state="running", run_key=started.get("run_key"))
        self._sync(rt, rt.active)
        return self.get_run(run_id)

    def _outline(self, site_id: str, area_id: str) -> list:
        return self.sites.area(site_id, area_id)["outline"]

    def _sync(self, rt: RobotRuntime, act: ActiveRun) -> None:
        """Bring the run's record up to what the navigator says."""
        status = rt.navigator.goal_status()
        state = status["state"]
        if state in goals.TERMINAL:
            ids = act.assoc.get("ids", {})
            self._end_run(act.id, rt, act.goal, state, status.get("reason"), _map_ids(status.get("result"), ids),
                          status.get("broken"), status.get("progress"))
            return
        now = self.clock()
        if not status.get("progress"):
            return
        if act.last_progress is None or now - act.last_progress >= PROGRESS_EVERY_S:
            act.last_progress = now
            self.store.execute("UPDATE goal_runs SET progress = ? WHERE id = ?", (dumps(status.get("progress")), act.id))
            self.bus.emit("goal-run", robot=rt.cfg.id, goal_run=act.id, state="running", progress=status.get("progress"))

    def _end_run(self, run_id, rt, goal, state, reason, result, broken, progress) -> None:
        as_expected = state in goals.SUCCESS if goal["expect"] == "reach" else state == "refused"
        self.store.execute(
            "UPDATE goal_runs SET state = ?, reason = ?, result = ?, broken = ?, progress = COALESCE(?, progress),"
            " as_expected = ?, ended_at = ? WHERE id = ?",
            (state, reason, dumps(result), dumps(broken), dumps(progress) if progress is not None else None,
             int(as_expected), self.wall(), run_id))
        if rt.active is not None and rt.active.id == run_id:
            rt.active = None
        self.bus.emit("goal-run", robot=rt.cfg.id, goal_run=run_id, state=state, reason=reason, result=result,
                      broken=broken, as_expected=as_expected)

    def _decision(self, rt: RobotRuntime, text: str, data: dict) -> None:
        act = rt.active
        if act is None:
            return
        act.decisions += 1
        self.store.execute("INSERT INTO decisions (run_id, n, at, text, data) VALUES (?,?,?,?,?)",
                           (act.id, act.decisions, self.wall(), text, dumps(data)))
        self.bus.emit("decision", robot=rt.cfg.id, goal_run=act.id, text=text, **data)

    def _objects(self, rt: RobotRuntime, objs: list) -> None:
        act = rt.active
        if act is None or act.site_id is None:
            return
        for o in objs:
            if o.get("seed"):
                # an object of the site's own that the navigator was seeded with: it is that object, not a new one
                if o["id"] not in act.assoc.setdefault("ids", {}):
                    act.assoc["ids"][o["id"]] = o["seed"]
                    # the sightings it already had are not new ones (the navigator counts from at least the confirm threshold)
                    act.assoc.setdefault("n", {})[o["id"]] = max(int(self.sites.object(act.site_id, o["seed"])["n"]), 3)
        changes = self.sites.merge_run_objects(act.site_id, objs, rt.cfg.id, act.assoc)
        if changes:
            self.bus.emit("objects", robot=rt.cfg.id, goal_run=act.id, site=act.site_id,
                          changes=[{"change": c, "id": i} for c, i in changes])

    def _watch(self, row: dict):
        """The Observatory's page for the run (RFC-0014 §3.11), when the robot's adapter has a run key and an Observatory."""
        rt = self.robots.get(row["robot"])
        url = getattr(rt.adapter, "watch_url", None) if rt is not None else None
        return url(row["run_key"]) if url else None

    def _run_view(self, row: dict, with_decisions: bool = False) -> dict:
        goal = loads(row["goal"])
        expected = goal["expect"]
        view = {
            "id": row["id"], "goal_id": row["goal_id"], "goal": goal, "robot": row["robot"], "site": row["site_id"],
            "target": row["target"], "state": row["state"], "reason": row["reason"], "progress": loads(row["progress"]),
            "result": loads(row["result"]), "broken": loads(row["broken"]), "guardrails": loads(row["guardrails"]),
            "conditions": loads(row["conditions"]), "run_key": row["run_key"], "watch": self._watch(row),
            "expect": expected, "as_expected": None if row["as_expected"] is None else bool(row["as_expected"]),
            "created_at": row["created_at"], "started_at": row["started_at"], "ended_at": row["ended_at"],
        }
        if with_decisions:
            view["decisions"] = [{"n": d["n"], "at": d["at"], "text": d["text"], **loads(d["data"])}
                                 for d in self.store.all("SELECT * FROM decisions WHERE run_id = ? ORDER BY n", (row["id"],))]
        return view

    def get_run(self, run_id: int) -> dict:
        row = self.store.one("SELECT * FROM goal_runs WHERE id = ?", (run_id,)) if isinstance(run_id, int) else None
        if row is None:
            raise not_found("goal run", run_id)
        return self._run_view(row, with_decisions=True)

    def list_runs(self, robot=None, state=None, goal_id=None, limit: int = 100) -> list:
        where, args = [], []
        for col, val in (("robot", robot), ("state", state), ("goal_id", goal_id)):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT * FROM goal_runs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
        return [self._run_view(r) for r in self.store.all(sql, (*args, limit))]

    def cancel_run(self, run_id: int) -> dict:
        row = self.get_run(run_id)
        if row["state"] in goals.TERMINAL:
            raise conflict("run_ended", f"goal run {run_id} already ended {row['state']}")
        rt = self.robot(row["robot"])
        with rt.mutex:
            if rt.active and rt.active.id == run_id and rt.navigator is not None:
                rt.navigator.goal_cancel()
                self._sync(rt, rt.active)
        return self.get_run(run_id)

    def save_run(self, run_id: int, body) -> dict:
        """Put the goal of a run in the library (§3.4.2); the run keeps the link."""
        if not isinstance(body, dict) or "name" not in body:
            raise invalid("body is {name, folder?}")
        run = self.get_run(run_id)
        spec = {**run["goal"], "name": body["name"], "folder": body.get("folder", run["goal"]["folder"])}
        saved = self.create_goal(spec)
        self.store.execute("UPDATE goal_runs SET goal_id = ? WHERE id = ?", (saved["id"], run_id))
        return saved
