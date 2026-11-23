"""Mission Control's core (RFC-0014 §3): the robots behind their gates, the goal library, goal runs, the
sites. No HTTP in here: `api.py` is one client of this, a test is another.

Time is injected (`clock` for durations, `wall` for stamps), and `tick()` is what moves things on: in
service each robot has its own thread calling `tick_robot`, so a robot that stops answering holds up
only itself (§3.3.1); a test calls `tick()` by hand with a fake clock."""

import threading
import time
from pathlib import Path

from . import goals, guardrails, planner
from .errors import ApiError, conflict, invalid, not_found
from .alarms import RecentAlarms
from .auth import Tokens
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
    def __init__(self, robot_configs: list, *, state_dir=None, clock=time.monotonic, wall=time.time, planner=None):
        self.clock, self.wall = clock, wall
        self.planner = planner         # an LLM planner (planner.LlmPlanner) or None: off
        self.state_dir = Path(state_dir) if state_dir else None
        self.store = Store(self.state_dir / "mission-control.sqlite" if self.state_dir else None)
        self.bus = EventBus(wall)
        self.alarms = RecentAlarms(wall)
        self.bus.listen(self.alarms.on_event)
        self.sites = Sites(self.store, wall)
        self.tokens = Tokens(self.store, wall)
        self.robots: dict = {}
        for cfg in robot_configs:
            rt = RobotRuntime(cfg, make_adapter(cfg, clock), clock=clock, wall=wall, bus=self.bus,
                              log_dir=self.state_dir)
            if rt.navigator is not None:
                rt.navigator.bind(lambda text, rt=rt, **data: self._decision(rt, text, data),
                                  lambda objs, rt=rt: self._objects(rt, objs))
                if hasattr(rt.navigator, "on_anomaly"):
                    rt.navigator.on_anomaly = lambda a, rt=rt: self._anomaly(rt, a)
            self.robots[cfg.id] = rt
        self._threads: list = []
        self._stopping = threading.Event()
        self._group_lock = threading.RLock()
        self._cancelling: set = set()

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

    @staticmethod
    def _profile_brief(cfg) -> dict | None:
        """The profile a robot runs, for its page: the registered robot, the environment, the version this machine runs and its
        parts. None for a robot file that holds the robot itself."""
        if cfg.profile is None:
            return None
        meta = cfg.profile.meta or {}
        return {"robot": cfg.robot, "variant": cfg.variant, "version": meta.get("version"), "checksum": meta.get("checksum"),
                "subsystems": cfg.profile.data.get("subsystems", [])}

    def robot_view(self, rt: RobotRuntime) -> dict:
        return {**self.robot_brief(rt), "factsheet": rt.cfg.factsheet, "control": rt.cfg.control,
                "capabilities": rt.cfg.capabilities, "status": rt.status,
                "guardrails": rt.cfg.guardrails, "rates": rt.cfg.rates, "site": self.sites.robot_site(rt.cfg.id),
                "goal_run": rt.active.id if rt.active else None, "profile": self._profile_brief(rt.cfg),
                "alarms": self.alarms.view(rt.cfg.id)}

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

    def run_goal(self, gid: int, body, client: str | None = None) -> dict:
        row = self._goal_row(gid)
        return self._start_run(loads(row["spec"]), body, gid, client)

    def run_adhoc(self, body, client: str | None = None) -> dict:
        if not isinstance(body, dict) or "goal" not in body:
            raise invalid("body is {goal, robots, target}")
        return self._start_run(body["goal"], body, None, client)

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

    def _start_run(self, goal_spec, body, goal_id, client: str | None = None) -> dict:
        if not isinstance(body, dict):
            raise invalid("body is {robots, target, site?}")
        if body.get("team") is not None or (isinstance(body.get("robots"), list) and len(body["robots"]) > 1):
            return self._start_group(goal_spec, body, goal_id, client)
        robots = body.get("robots")
        if not isinstance(robots, list) or not robots or not all(isinstance(r, str) for r in robots):
            raise invalid("robots is a list with the ids of the robots to run on, or team names a team")
        if body.get("share") is not None:
            raise invalid("share says how several robots share a goal: name several robots or a team")
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
            return self._create_and_start(rt, goal, goal_id, site_id, target, None, client)

    # --- one goal on several robots (RFC-0014 §3.4.4) ----------------------------------------------------------

    def _group_ids(self, body: dict) -> list:
        if body.get("team") is not None:
            if body.get("robots") is not None:
                raise invalid("name robots or a team, not both")
            name = body["team"]
            ids = sorted(rid for rid, rt in self.robots.items() if name in rt.cfg.teams)
            if not ids:
                raise not_found("team", name)
            return ids
        robots = body.get("robots")
        if not all(isinstance(r, str) for r in robots) or len(set(robots)) != len(robots):
            raise invalid("robots is a list of different robot ids")
        for rid in robots:
            self.robot(rid)
        return sorted(robots)

    def _start_group(self, goal_spec, body: dict, goal_id, client: str | None = None) -> dict:
        """A goal run for several robots: a parent run and one child run per robot. `each`: every robot does the whole goal,
        independently, and the parent holds one result per robot. `any`: the first robot to reach it ends the goal and the
        others are cancelled. A robot that cannot take part is left out with its reason (a child run in the state refused); if none
        can, the group is refused. The leases are taken in the order of the robot ids and, if a robot is held by another client,
        the ones already taken are released and the group fails naming it (RFC-0017 §3.5.3)."""
        ids = self._group_ids(body)
        share = body.get("share", "each")
        if share == "split":
            raise ApiError(501, "not_built", "share: split (dividing the goal's area between robots) is RFC-0014 step 10")
        if share not in ("each", "any"):
            raise invalid("share is 'each' or 'any'")
        target = body.get("target", "sim")
        if target not in ("sim", "real"):
            raise invalid("target is 'sim' or 'real'")
        rts = [self.robot(i) for i in ids]
        if target == "real" and any(rt.cfg.kind == "fake" for rt in rts):
            raise invalid("the fake robot is not a real robot")
        goal = goals.validate(goal_spec, require_name=False)
        sites = {self._site_of(body, rt) for rt in rts}
        now = self.wall()
        parent_id = self.store.execute(
            "INSERT INTO goal_runs (goal_id, goal, robot, site_id, target, state, guardrails, conditions, created_at, started_at, share, client)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (goal_id, dumps(goal), ",".join(ids), sites.pop() if len(sites) == 1 else None, target, "running", "[]",
             dumps({"done_when": goal["done_when"], "not_checkable": []}), now, now, share, client))
        self.bus.emit("goal-run", goal_run=parent_id, state="running", share=share, robots=ids, client=client)
        held = None
        for rt in rts:
            site_id = self._site_of(body, rt)
            if not rt.online():
                self._refuse_child(rt, goal, goal_id, parent_id, site_id, target, f"{rt.cfg.id} is offline: left out", client)
                continue
            with rt.mutex:
                if rt.active:
                    self._refuse_child(rt, goal, goal_id, parent_id, site_id, target, f"goal run {rt.active.id} holds {rt.cfg.id}: left out", client)
                    continue
                child = self._create_and_start(rt, goal, goal_id, site_id, target, parent_id, client)
            if child["state"] == "refused" and str(child["reason"]).startswith("driven by"):
                held = (rt.cfg.id, child["reason"])
                break
        if held is not None:
            for k in self.store.all("SELECT id, state FROM goal_runs WHERE parent_id = ?", (parent_id,)):
                if k["state"] in goals.ACTIVE:
                    self.cancel_run(k["id"])
            self._finish_group(parent_id, "refused", f"{held[0]} is held ({held[1]}): the robots already taken were released", None)
        else:
            self._refresh_group(parent_id)
        return self.get_run(parent_id)

    def _refuse_child(self, rt: RobotRuntime, goal: dict, goal_id, parent_id: int, site_id, target, reason: str, client=None) -> int:
        now = self.wall()
        run_id = self.store.execute(
            "INSERT INTO goal_runs (goal_id, goal, robot, site_id, target, state, reason, guardrails, conditions, as_expected, created_at,"
            " ended_at, parent_id, client) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (goal_id, dumps(goal), rt.cfg.id, site_id, target, "refused", reason, "[]", dumps({"done_when": goal["done_when"], "not_checkable": []}),
             int(goal["expect"] == "refuse"), now, now, parent_id, client))
        self.bus.emit("goal-run", robot=rt.cfg.id, goal_run=run_id, state="refused", reason=reason, client=client)
        return run_id

    def _refresh_group(self, parent_id: int) -> None:
        """Called whenever a child run changes: end the group when its children have ended, and for `any` send the others home as
        soon as one has reached the goal."""
        with self._group_lock:
            parent = self.store.one("SELECT * FROM goal_runs WHERE id = ?", (parent_id,))
            if parent is None or parent["state"] in goals.TERMINAL:
                return
            kids = self.store.all("SELECT * FROM goal_runs WHERE parent_id = ? ORDER BY id", (parent_id,))
            active = [k for k in kids if k["state"] in goals.ACTIVE]
            winner = min((k for k in kids if k["state"] in goals.SUCCESS), key=lambda k: k["ended_at"], default=None)
            if parent["share"] == "any" and winner is not None and active:
                if parent_id not in self._cancelling:
                    self._cancelling.add(parent_id)
                    threading.Thread(target=lambda: [self._cancel_quietly(k["id"]) for k in active], daemon=True).start()
                return
            if active:
                return
            self._cancelling.discard(parent_id)
            took_part = [k for k in kids if k["state"] != "refused"]
            if not took_part:
                reasons = "; ".join(f"{k['robot']}: {k['reason']}" for k in kids)
                self._finish_group(parent_id, "refused", f"no robot could take the goal: {reasons}", None)
                return
            results = {k["robot"]: {"state": k["state"], "reason": k["reason"], "result": loads(k["result"]), "run": k["id"]} for k in kids}
            if parent["share"] == "any" and winner is not None:
                self._finish_group(parent_id, winner["state"], None, {"winner": winner["robot"], "result": loads(winner["result"]), "robots": results})
                return
            states = {k["state"] for k in took_part}
            if all(k["state"] in goals.SUCCESS for k in took_part):
                state, reason = ("done" if states == {"done"} else "reached"), None
            elif len(states) == 1:
                state, reason = states.pop(), "; ".join(f"{k['robot']}: {k['reason']}" for k in took_part if k["reason"])
            else:
                state = "failed"
                reason = "; ".join(f"{k['robot']}: {k['state']}" + (f" ({k['reason']})" if k["reason"] else "") for k in took_part
                                   if k["state"] not in goals.SUCCESS)
            self._finish_group(parent_id, state, reason or None, results)

    def _finish_group(self, parent_id: int, state: str, reason, result) -> None:
        goal = loads(self.store.one("SELECT goal FROM goal_runs WHERE id = ?", (parent_id,))["goal"])
        as_expected = state in goals.SUCCESS if goal["expect"] == "reach" else state == "refused"
        self.store.execute("UPDATE goal_runs SET state = ?, reason = ?, result = ?, as_expected = ?, ended_at = ? WHERE id = ?",
                           (state, reason, dumps(result), int(as_expected), self.wall(), parent_id))
        self.bus.emit("goal-run", goal_run=parent_id, state=state, reason=reason, result=result, as_expected=as_expected)

    def _cancel_quietly(self, run_id: int) -> None:
        try:
            self.cancel_run(run_id)
        except ApiError:
            pass                                   # it ended by itself in the meantime

    def _create_and_start(self, rt: RobotRuntime, goal: dict, goal_id, site_id, target, parent_id=None, client=None) -> dict:
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
            "INSERT INTO goal_runs (goal_id, goal, robot, site_id, target, state, guardrails, conditions, created_at, parent_id, client)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (goal_id, dumps(goal), rt.cfg.id, site_id, target, "queued", dumps(merged), dumps(conditions), now, parent_id, client))
        self.bus.emit("goal-run", robot=rt.cfg.id, goal_run=run_id, state="queued", client=client)
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
        parent = self.store.one("SELECT parent_id FROM goal_runs WHERE id = ?", (run_id,))["parent_id"]
        if parent is not None:
            self._refresh_group(parent)

    def _decision(self, rt: RobotRuntime, text: str, data: dict) -> None:
        act = rt.active
        if act is None:
            return
        act.decisions += 1
        self.store.execute("INSERT INTO decisions (run_id, n, at, text, data) VALUES (?,?,?,?,?)",
                           (act.id, act.decisions, self.wall(), text, dumps(data)))
        self.bus.emit("decision", robot=rt.cfg.id, goal_run=act.id, text=text, **data)

    def _anomaly(self, rt: RobotRuntime, a: dict) -> None:
        """One anomaly the navigator raised (RFC-0019's record, contract 1.1): kept with the goal run, and on the bus with the
        Observatory's page for the run at its moment (`#t=`, the run's own clock)."""
        act = rt.active
        if act is None:
            return
        n = int(a.get("n") or 0)
        self.store.execute("INSERT OR IGNORE INTO anomalies (run_id, n, at, data) VALUES (?,?,?,?)", (act.id, n, self.wall(), dumps(a)))
        row = self.store.one("SELECT robot, run_key FROM goal_runs WHERE id = ?", (act.id,))
        watch = self._watch(row) if row else None
        if watch and a.get("t") is not None:
            watch = f"{watch}#t={a['t']}"
        self.bus.emit("anomaly", robot=rt.cfg.id, goal_run=act.id, anomaly=a, watch=watch)

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
            "parent_id": row["parent_id"], "share": row["share"], "client": row["client"],
        }
        if row["share"]:
            view["robots"] = row["robot"].split(",")
            view["children"] = [self._run_view(k) for k in self.store.all("SELECT * FROM goal_runs WHERE parent_id = ? ORDER BY id", (row["id"],))]
        if with_decisions:
            view["decisions"] = [{"n": d["n"], "at": d["at"], "text": d["text"], **loads(d["data"])}
                                 for d in self.store.all("SELECT * FROM decisions WHERE run_id = ? ORDER BY n", (row["id"],))]
            view["anomalies"] = [{"n": d["n"], "at": d["at"], **loads(d["data"])}
                                 for d in self.store.all("SELECT * FROM anomalies WHERE run_id = ? ORDER BY n", (row["id"],))]
        return view

    def get_run(self, run_id: int) -> dict:
        row = self.store.one("SELECT * FROM goal_runs WHERE id = ?", (run_id,)) if isinstance(run_id, int) else None
        if row is None:
            raise not_found("goal run", run_id)
        return self._run_view(row, with_decisions=True)

    def list_runs(self, robot=None, state=None, goal_id=None, parent=None, limit: int = 100) -> list:
        """Newest first. Without a robot or a parent, the children of a group are not listed on their own: the group is."""
        where, args = [], []
        for col, val in (("robot", robot), ("state", state), ("goal_id", goal_id), ("parent_id", parent)):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        if robot is None and parent is None:
            where.append("parent_id IS NULL")
        sql = "SELECT * FROM goal_runs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
        return [self._run_view(r) for r in self.store.all(sql, (*args, limit))]

    def cancel_run(self, run_id: int) -> dict:
        row = self.get_run(run_id)
        if row["state"] in goals.TERMINAL:
            raise conflict("run_ended", f"goal run {run_id} already ended {row['state']}")
        if row["share"]:
            for kid in row["children"]:
                if kid["state"] in goals.ACTIVE:
                    self._cancel_quietly(kid["id"])
            self._refresh_group(run_id)
            return self.get_run(run_id)
        rt = self.robot(row["robot"])
        with rt.mutex:
            if rt.active and rt.active.id == run_id and rt.navigator is not None:
                rt.navigator.goal_cancel()
                self._sync(rt, rt.active)
        return self.get_run(run_id)

    def plan(self, text, robot: str | None = None, site: str | None = None) -> dict:
        """Words in, goals out (§3.4.5): proposals read back for the operator to confirm. Nothing runs, and no robot is touched."""
        rt = self.robot(robot) if robot else None
        site = site or (self.sites.robot_site(rt.cfg.id) if rt else None)
        if site is None and len(self.sites.list()) == 1:
            site = self.sites.list()[0]["id"]
        areas = self.sites.areas(site) if site else []
        objects = self.sites.objects(site) if site else []
        kinds = {k for r in ([rt] if rt else self.robots.values()) for rec in r.cfg.capabilities.get("recognisers", []) for k in rec.get("kinds", [])}
        out = planner.plan(text, planner.Context(areas, objects, kinds, site), self.planner)
        out["site"] = site
        return out

    def save_run(self, run_id: int, body) -> dict:
        """Put the goal of a run in the library (§3.4.2); the run keeps the link."""
        if not isinstance(body, dict) or "name" not in body:
            raise invalid("body is {name, folder?}")
        run = self.get_run(run_id)
        spec = {**run["goal"], "name": body["name"], "folder": body.get("folder", run["goal"]["folder"])}
        saved = self.create_goal(spec)
        self.store.execute("UPDATE goal_runs SET goal_id = ? WHERE id = ?", (saved["id"], run_id))
        return saved
