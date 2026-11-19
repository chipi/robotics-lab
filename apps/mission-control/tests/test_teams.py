"""One goal on several robots (RFC-0014 §3.4.4, step 5): `share: each` and `any` over a team or a list of robots, robots left out
with their reason, the leases taken in the order of the robot ids and released if one is held, cancel and STOP, and the store's
migration to the schema that has groups. The fakes, a fake clock; the real gate stands in front of each.
Run: cd control && uv run python tests/test_teams.py"""

import copy
import json
import sqlite3
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from common import FAKE_FILE, Clock, check, finish, finish_run, make_mc, robot_file, run_for

from mission_control.api import serve
from mission_control.errors import ApiError
from mission_control.store import SCHEMA_VERSION, Store

POINT = {"kind": "point", "params": {"x": 2.0, "y": 0.0}}


def refusal(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except ApiError as exc:
        return exc
    return None


def slow(rid, speed, **over):
    fs = copy.deepcopy(FAKE_FILE["factsheet"])
    fs["physicalParameters"] = {"maximumSpeed": speed, "maximumAngularSpeed": 1.5}
    return robot_file(rid, factsheet=fs, teams=["pair"], **over)


def boot(*files):
    clock = Clock()
    mc = make_mc(clock, *files)
    run_for(mc, clock, 0.3)
    return mc, clock


def group(mc, goal=POINT, **body):
    return mc.run_adhoc({"goal": goal, **body})


def settle(mc, clock, rid, seconds=120):
    return finish_run(mc, clock, rid, seconds)


# --- each: every robot does the whole goal ------------------------------------------------------------------------
mc, clock = boot(robot_file("fake-1", teams=["pair"]), robot_file("fake-2", teams=["pair"]), robot_file("fake-3"))
check("a team is the robots whose files name it", sorted(mc.robots) == ["fake-1", "fake-2", "fake-3"] and mc.robots["fake-1"].cfg.teams == ["pair"])
g = group(mc, team="pair")
check("a goal for a team starts a group run: a parent and a child per robot, share each by default",
      g["share"] == "each" and g["robots"] == ["fake-1", "fake-2"] and [k["robot"] for k in g["children"]] == ["fake-1", "fake-2"]
      and all(k["parent_id"] == g["id"] and k["state"] == "running" for k in g["children"]) and g["state"] == "running", g)
check("each child holds its own robot through its own gate", mc.get_robot("fake-1")["lock"]["holder"] == "fake-navigator"
      and mc.get_robot("fake-2")["lock"]["holder"] == "fake-navigator" and mc.get_robot("fake-3")["lock"]["holder"] is None)
done = settle(mc, clock, g["id"])
check("every robot did the whole goal: the group is reached, one result per robot",
      done["state"] == "reached" and done["as_expected"] is True and set(done["result"]) == {"fake-1", "fake-2"}
      and all(v["state"] == "reached" for v in done["result"].values()), done["state"])
check("the children are runs of their own, each with its decisions", all(k["state"] == "reached" and k["decisions"] is not None for k in
                                                                     (mc.get_run(c["id"]) for c in done["children"])))
check("the list shows the group and not its children, unless asked", [r["id"] for r in mc.list_runs()] == [g["id"]]
      and [r["id"] for r in mc.list_runs(parent=g["id"])] == [c["id"] for c in reversed(done["children"])]
      and len(mc.list_runs(robot="fake-1")) == 1 and mc.list_runs(robot="fake-1")[0]["parent_id"] == g["id"])
check("both robots are free", mc.get_robot("fake-1")["lock"]["holder"] is None and mc.get_robot("fake-2")["lock"]["holder"] is None)
check("the group's end is an event", any(e["kind"] == "goal-run" and e["goal_run"] == g["id"] and e["state"] == "reached" for e in mc.bus.since(0, 100000)[0]))
g2 = group(mc, robots=["fake-2", "fake-1"], goal={"kind": "explore", "params": {"site": True}}, share="each")
check("robots named in any order start in the order of their ids; a goal about a site with no site is refused by each, so the group is",
      g2["state"] == "refused" and "no robot could take the goal" in g2["reason"] and [k["robot"] for k in g2["children"]] == ["fake-1", "fake-2"], g2)

# --- robots left out, and the ones that cannot ------------------------------------------------------------------
mc, clock = boot(robot_file("fake-1", teams=["pair"]), robot_file("fake-2", teams=["pair"]))
mc.robots["fake-2"].adapter.robot.set_offline(True)
run_for(mc, clock, 3.0)
g = group(mc, team="pair")
check("an offline robot is left out with its reason: a child run refused, the group runs on the other",
      [(k["robot"], k["state"]) for k in g["children"]] == [("fake-1", "running"), ("fake-2", "refused")] and "offline: left out" in g["children"][1]["reason"], g["children"])
done = settle(mc, clock, g["id"])
check("and ends reached for the robot that took part", done["state"] == "reached" and done["result"]["fake-2"]["state"] == "refused")
mc.robots["fake-1"].adapter.robot.set_offline(True)
run_for(mc, clock, 3.0)
g = group(mc, team="pair")
check("with no robot able to take it the group is refused, with every reason", g["state"] == "refused" and "fake-1" in g["reason"] and "fake-2" in g["reason"]
      and all(k["state"] == "refused" for k in g["children"]), g)

# --- one fails, one succeeds ------------------------------------------------------------------------------------
mc, clock = boot(slow("fake-1", 0.5), slow("fake-2", 0.05))
g = group(mc, team="pair", goal={"kind": "point", "params": {"x": 2.0, "y": 0.0}, "done_when": {"within_s": 6}})
done = settle(mc, clock, g["id"])
check("each: one reaches and one runs out of time: the group failed, and says which robot and why",
      done["state"] == "failed" and "fake-2: failed" in done["reason"] and done["result"]["fake-1"]["state"] == "reached", (done["state"], done["reason"]))
check("the group did not call the robot that did reach it a failure: its own child is reached", mc.get_run(done["children"][0]["id"])["state"] == "reached")

# --- any: the first to reach it ends it ----------------------------------------------------------------------------
mc, clock = boot(slow("fake-1", 0.5), slow("fake-2", 0.1))
g = group(mc, team="pair", share="any", goal={"kind": "point", "params": {"x": 3.0, "y": 0.0}})
run_for(mc, clock, 120, until=lambda: mc.get_run(g["id"])["state"] != "running")
done = mc.get_run(g["id"])
check("any: the first robot to reach the goal ends it: the group's state is the winner's and the winner is named",
      done["state"] == "reached" and done["result"]["winner"] == "fake-1", (done["state"], done["result"]))
check("the others are cancelled and stopped", {k["robot"]: k["state"] for k in done["children"]} == {"fake-1": "reached", "fake-2": "cancelled"}, [(k["robot"], k["state"]) for k in done["children"]])
check("every robot is free and stopped", all(mc.get_robot(r)["lock"]["holder"] is None for r in ("fake-1", "fake-2")) and mc.robots["fake-2"].adapter.robot.vx == 0.0)
check("each child's result is in the group's, the loser's too", set(done["result"]["robots"]) == {"fake-1", "fake-2"})
mc, clock = boot(slow("fake-1", 0.05), slow("fake-2", 0.05))
g = group(mc, team="pair", share="any", goal={"kind": "point", "params": {"x": 3.0, "y": 0.0}, "done_when": {"within_s": 3}})
done = settle(mc, clock, g["id"])
check("any: when none reaches it the group fails like each", done["state"] == "failed" and done["as_expected"] is False, (done["state"], done["reason"]))

# --- the leases ------------------------------------------------------------------------------------------------
mc, clock = boot(slow("fake-1", 0.5), slow("fake-2", 0.5))
held = mc.robot("fake-2").acquire("script")
g = group(mc, team="pair")
check("a robot another client holds: the group is refused, naming it, and the robots already taken were released",
      g["state"] == "refused" and "fake-2 is held" in g["reason"] and "driven by script" in g["reason"] and "released" in g["reason"], g["reason"])
check("fake-1 was started first (the order of the ids) and given back: cancelled, free", [(k["robot"], k["state"]) for k in g["children"]][0] == ("fake-1", "cancelled")
      and mc.get_robot("fake-1")["lock"]["holder"] is None and mc.robots["fake-1"].adapter.robot.vx == 0.0, g["children"])
check("the one holding fake-2 still holds it", mc.get_robot("fake-2")["lock"]["holder"] == "script")
mc.robot("fake-2").release(held["session"])

# --- cancel, STOP ---------------------------------------------------------------------------------------------
g = group(mc, team="pair", goal={"kind": "point", "params": {"x": 3.5, "y": -2.0}})
run_for(mc, clock, 1.0)
c = mc.cancel_run(g["id"])
check("cancelling the group cancels every robot's run: the group is cancelled, the robots stopped and free",
      c["state"] == "cancelled" and all(k["state"] == "cancelled" for k in c["children"]) and all(mc.get_robot(r)["lock"]["holder"] is None for r in ("fake-1", "fake-2")), c["state"])
check("cancelling a group that ended is refused", refusal(mc.cancel_run, g["id"]).code == "run_ended")
g = group(mc, team="pair", goal={"kind": "point", "params": {"x": 3.5, "y": -2.0}})
run_for(mc, clock, 1.0)
mc.stop("fake-2", "page")
run_for(mc, clock, 0.3)
check("STOP of one robot cancels its run only; the group goes on with the other", mc.get_run(g["id"])["state"] == "running"
      and {k["robot"]: k["state"] for k in mc.get_run(g["id"])["children"]} == {"fake-1": "running", "fake-2": "cancelled"})
done = settle(mc, clock, g["id"])
check("and ends failed, with the robot that was stopped named", done["state"] == "failed" and "fake-2: cancelled" in done["reason"], (done["state"], done["reason"]))

# --- what is not accepted ------------------------------------------------------------------------------------------
check("an unknown team is a 404", refusal(mc.run_adhoc, {"goal": POINT, "team": "nobody"}).status == 404)
check("share: split is not built, and says which step", refusal(mc.run_adhoc, {"goal": POINT, "team": "pair", "share": "split"}).code == "not_built")
check("an unknown share is a 422", refusal(mc.run_adhoc, {"goal": POINT, "team": "pair", "share": "all"}).status == 422)
check("robots and a team together are a 422", refusal(mc.run_adhoc, {"goal": POINT, "team": "pair", "robots": ["fake-1"]}).status == 422)
check("the same robot twice is a 422", refusal(mc.run_adhoc, {"goal": POINT, "robots": ["fake-1", "fake-1"]}).status == 422)
check("share with one robot is a 422: it says how robots share", refusal(mc.run_adhoc, {"goal": POINT, "robots": ["fake-1"], "share": "any"}).status == 422)
check("a robot that does not exist is a 404", refusal(mc.run_adhoc, {"goal": POINT, "robots": ["fake-1", "ghost"]}).status == 404)
check("the fake is not a real robot, for a group too", refusal(mc.run_adhoc, {"goal": POINT, "team": "pair", "target": "real"}).status == 422)

# --- over HTTP ------------------------------------------------------------------------------------------------------
mc, clock = boot(robot_file("fake-1", teams=["pair"]), robot_file("fake-2", teams=["pair"]))
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


st, b = call("POST", "/goal-runs", {"goal": POINT, "team": "pair", "share": "any"})
gid = b["run"]["id"]
check("POST /goal-runs with a team: 201, the group with its children", st == 201 and b["run"]["share"] == "any" and len(b["run"]["children"]) == 2, b)
run_for(mc, clock, 120, until=lambda: call("GET", f"/goal-runs/{gid}")[1]["run"]["state"] != "running")
st, b = call("GET", f"/goal-runs/{gid}")
check("GET /goal-runs/{id} is the group, with the children and the winner", b["run"]["state"] == "reached" and b["run"]["result"]["winner"] in ("fake-1", "fake-2"), b["run"]["result"])
check("GET /goal-runs?parent= lists the children", len(call("GET", f"/goal-runs?parent={gid}")[1]["runs"]) == 2 and [r["id"] for r in call("GET", "/goal-runs")[1]["runs"]] == [gid])
check("a team that does not exist is a 404 over HTTP", call("POST", "/goal-runs", {"goal": POINT, "team": "nobody"})[0] == 404)
srv.shutdown()
srv.server_close()

# --- the store's migration -----------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "old.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE goal_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id INTEGER, goal TEXT NOT NULL, robot TEXT NOT NULL,
        site_id TEXT, target TEXT NOT NULL, state TEXT NOT NULL, reason TEXT, progress TEXT, result TEXT, broken TEXT, guardrails TEXT NOT NULL,
        conditions TEXT NOT NULL, run_key TEXT, as_expected INTEGER, created_at REAL NOT NULL, started_at REAL, ended_at REAL);
        INSERT INTO goal_runs (goal, robot, target, state, guardrails, conditions, created_at) VALUES ('{}', 'fake-1', 'sim', 'reached', '[]', '{}', 1.0);
        PRAGMA user_version = 1;""")
    db.commit()
    db.close()
    store = Store(path)
    cols = {r["name"] for r in store.all("PRAGMA table_info(goal_runs)")}
    check("a store of version 1 is brought to this one: the run table gains parent_id and share, the old run is kept",
          {"parent_id", "share"} <= cols and store.one("SELECT COUNT(*) AS n FROM goal_runs")["n"] == 1 and store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION)
    store.close()
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 99")
    db.commit()
    db.close()
    try:
        Store(path)
        check("a store from a newer build is refused, not opened", False)
    except RuntimeError as exc:
        check("a store from a newer build is refused, not opened", "schema version 99" in str(exc))

finish("test_teams")
