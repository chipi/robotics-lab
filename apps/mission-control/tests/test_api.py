"""The HTTP API (RFC-0014 §3.2, control/CONTRACT.md) over a real socket, as curl would use it: the robots, their
lock, drive and STOP, goals and runs, sites, areas and objects, and the server-sent event stream. The
core runs on a fake clock that the test ticks; the last section runs the real thing, with threads and
the real clock, and sets a point goal over HTTP, watches it reach and STOPs it.
Run: cd apps/mission-control && uv run python tests/test_api.py"""

import json
import threading
import time
import urllib.error
import urllib.request

from common import Clock, check, finish, make_mc, robot_file, run_for

from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.goals import TERMINAL
from mission_control.robots import RobotConfig

clock = Clock()
blind = robot_file("blind", factsheet={"physicalParameters": {"maximumSpeed": 0.3, "maximumAngularSpeed": 1.0}}, capabilities={"guardrails": ["contact"]})
mc = make_mc(clock, robot_file(), blind)
run_for(mc, clock, 0.2)
server = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{server.server_address[1]}/api/v1"
threading.Thread(target=server.serve_forever, daemon=True).start()


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def ticks(seconds, until=None):
    return run_for(mc, clock, seconds, until=until)


def wait_run(run_id, seconds=200):
    ticks(seconds, until=lambda: call("GET", f"/goal-runs/{run_id}")[1]["run"]["state"] in TERMINAL)
    return call("GET", f"/goal-runs/{run_id}")[1]["run"]


# --- errors, routes ---------------------------------------------------------------------------------
st, b = call("GET", "/health")
check("health", st == 200 and b == {"ok": True, "service": "mission-control", "robots": 2}, b)
st, b = call("GET", "/nowhere")
check("an unknown path is {ok: false, error: {code, message}} with a 404", st == 404 and b["ok"] is False and b["error"]["code"] == "no_route")
st, b = call("DELETE", "/robots")
check("a known path with the wrong method is a 405 listing the methods", st == 405 and "GET" in b["error"]["message"], b)
req = urllib.request.Request(BASE + "/goals", data=b"{not json", method="POST")
try:
    urllib.request.urlopen(req, timeout=5)
    check("a body that is not JSON is a 400", False)
except urllib.error.HTTPError as exc:
    check("a body that is not JSON is a 400", exc.code == 400 and json.loads(exc.read())["error"]["code"] == "bad_json")
st, b = call("GET", "/robots/nope")
check("an unknown robot is a 404 with its id", st == 404 and b["error"]["code"] == "not_found" and b["error"]["id"] == "nope", b)

# --- robots -------------------------------------------------------------------------------------------
st, b = call("GET", "/robots")
check("GET /robots: id, label, kind, online, lock, last-seen age", st == 200 and [r["id"] for r in b["robots"]] == ["fake-1", "blind"]
      and b["robots"][0]["online"] and b["robots"][0]["lock"]["holder"] is None and "last_seen_age_s" in b["robots"][0], b)
st, b = call("GET", "/robots/fake-1")
check("GET /robots/{id}: capabilities and status with the frame named", b["robot"]["capabilities"]["navigator"]["goal_kinds"]
      and b["robot"]["status"]["pose"]["frame"] == "site" and b["robot"]["rates"]["state_hz"] == 2.0)
check("a robot that raised no alarm carries an empty `alarms` with the window", b["robot"]["alarms"] == {"window_s": 60, "worst": None, "joints": {}}, b["robot"]["alarms"])


def alarm(robot, sev, name, joint=None, n=1):
    a = {"n": n, "t": 1.0, "anomaly": name, "source": "robot", "module": "body", "severity": sev, "detector": "d", "summary": name}
    if joint:
        a["values"] = {"joint": joint}
    return mc.bus.emit("anomaly", robot=robot, goal_run=1, watch=None, anomaly=a)


e1 = alarm("fake-1", "minor", "joint_tracking", "hip", 1)
ticks(1.0)
e2 = alarm("fake-1", "major", "joint_overload", "hip", 2)
e3 = alarm("fake-1", "critical", "pose_jump", None, 3)
e4 = alarm("fake-1", "minor", "motor_hot", "knee", 4)
alarm("blind", "major", "joint_overload", "hip", 5)
al = call("GET", "/robots/fake-1")[1]["robot"]["alarms"]
check("the robot's view lists the alarms of the last minute: the worst overall with its time", al["worst"]["anomaly"]["n"] == 3 and al["worst"]["at"] == e3["t"]
      and al["worst"]["goal_run"] == 1 and "watch" in al["worst"], al["worst"])
check("and the worst per joint (a major beats an earlier minor; one that names no joint is in none), another robot's alarm not among them",
      sorted(al["joints"]) == ["hip", "knee"] and al["joints"]["hip"]["anomaly"]["n"] == 2 and al["joints"]["hip"]["at"] == e2["t"]
      and al["joints"]["knee"]["anomaly"]["severity"] == "minor", al["joints"])
check("the same through GET /robots, which carries no alarms (the brief)", "alarms" not in call("GET", "/robots")[1]["robots"][0])
ticks(59.5)
al = call("GET", "/robots/fake-1")[1]["robot"]["alarms"]
check("an alarm older than the window is dropped: the minor one from 60.5 s ago is gone, the others stay", e1["t"] < clock() - 60 < e2["t"] and al["joints"]["hip"]["anomaly"]["n"] == 2
      and al["worst"]["anomaly"]["n"] == 3, (al, clock()))
ticks(1.0)
check("and when all are older, the view is empty again", call("GET", "/robots/fake-1")[1]["robot"]["alarms"] == {"window_s": 60, "worst": None, "joints": {}})
st, b = call("GET", "/robots/fake-1/map")
check("GET /robots/{id}/map: a robot that has one", st == 200 and b["map"]["kind"] == "occupancy_grid" and b["map"]["frame"] == "site")
st, b = call("GET", "/robots/blind/map")
check("a robot with no map answers 404 no_map", st == 404 and b["error"]["code"] == "no_map")
st, b = call("GET", "/robots/fake-1/sighting")
check("GET /robots/{id}/sighting: a robot with a recogniser", st == 200 and "hfov_deg" in b["sighting"])
check("a robot with none answers 404 no_recogniser", call("GET", "/robots/blind/sighting")[1]["error"]["code"] == "no_recogniser")

# lock, drive, STOP
st, b = call("POST", "/robots/fake-1/lock", {"client": "curl"})
sess = b["lock"]["session"]
check("POST lock: a session and a lease", st == 200 and len(sess) == 16 and b["lock"]["lease_id"] == 1, b)
st, b = call("POST", "/robots/fake-1/lock", {"client": "other"})
check("a second client: 409 held, who and since in the error", st == 409 and b["error"]["code"] == "held" and b["error"]["holder"] == "curl" and "since" in b["error"], b)
st, b = call("GET", "/robots/fake-1")
check("the robot's lock field says who holds it", b["robot"]["lock"]["holder"] == "curl")
st, b = call("POST", "/robots/fake-1/drive", {"vx": 0.3, "vyaw": 0.0, "session": sess})
check("drive with the session", st == 200 and b["drive"]["ok"])
ticks(0.6)
check("and the robot moved", call("GET", "/robots/fake-1")[1]["robot"]["status"]["pose"]["x"] > 0.02)
st, b = call("POST", "/robots/fake-1/drive", {"vx": 0.3})
check("drive with no session is refused: no lease, no motion", st == 409 and b["error"]["code"] == "no_lease")
st, b = call("POST", "/robots/fake-1/drive", {"vx": "fast", "session": sess})
check("a drive that is not a number is a 422", st == 422)
check("renew", call("POST", "/robots/fake-1/lock/renew", {"session": sess})[0] == 200)
st, b = call("POST", "/robots/fake-1/lock/takeover", {"client": "curl2"})
check("takeover needs a name on the robot's list: 403", st == 403 and b["error"]["code"] == "not_allowed")
st, b = call("POST", "/robots/fake-1/stop", {"client": "page"}, {"X-Client": "ignored"})
check("POST stop: accepted with no lock, confirmed", st == 200 and b["stop"] == {"robot": "fake-1", "confirmed": True, "online": True}, b)
st, b = call("POST", "/robots/fake-1/drive", {"vx": 0.3, "session": sess})
check("a STOP latches: the holder's next drive is 409 lease_ended, naming the stopper", st == 409 and b["error"]["code"] == "lease_ended"
      and "stopped_by page" in b["error"]["message"], b)
st, b = call("POST", "/robots/fake-1/lock/takeover", {"client": "operator-laptop"})
check("takeover from a listed name", st == 200 and b["lock"]["session"])
check("DELETE lock releases it", call("DELETE", "/robots/fake-1/lock", {"session": b["lock"]["session"]})[0] == 200
      and call("GET", "/robots/fake-1")[1]["robot"]["lock"]["holder"] is None)
st, b = call("POST", "/stop", None, {"X-Client": "big-red-button"})
check("POST /stop: every robot, each reported", st == 200 and [r["robot"] for r in b["stop"]["robots"]] == ["fake-1", "blind"]
      and b["stop"]["all_confirmed"] is True, b)
mc.robots["blind"].adapter.robot.set_offline(True)
ticks(3.0)
st, b = call("GET", "/robots")
check("an offline robot says so", [r["online"] for r in b["robots"]] == [True, False])
st, b = call("POST", "/robots/blind/drive", {"vx": 0.1, "session": "x"})
check("a drive to an offline robot is a 503, never queued", st == 503 and b["error"]["code"] == "robot_offline")
st, b = call("POST", "/stop")
check("STOP-all still goes: the offline robot's STOP is accepted but not confirmed", st == 200 and b["stop"]["all_confirmed"] is False
      and {r["robot"]: r["confirmed"] for r in b["stop"]["robots"]} == {"fake-1": True, "blind": False}, b)
mc.robots["blind"].adapter.robot.set_offline(False)
ticks(1.0)

# --- goals and runs ---------------------------------------------------------------------------------
st, b = call("POST", "/goals", {"name": "to the door", "folder": "tests", "kind": "point", "params": {"x": 1.0, "y": 0.0}})
gid = b["goal"]["id"]
check("POST /goals: 201 and the goal with its defaults", st == 201 and b["goal"]["done_when"] == {"within_m": 0.25, "within_s": 60.0} and b["goal"]["folder"] == "tests", b)
check("a goal of an unknown kind is a 422 unknown_kind", call("POST", "/goals", {"name": "x", "kind": "fetch"})[1]["error"]["code"] == "unknown_kind")
check("GET /goals?folder=", [g["id"] for g in call("GET", "/goals?folder=tests")[1]["goals"]] == [gid] and call("GET", "/goals?folder=nothing")[1]["goals"] == [])
st, b = call("GET", f"/goals/{gid}")
got = b["goal"]
st, b = call("PUT", f"/goals/{gid}", {**got, "must_not": ["contact"]})
check("a goal as GET returns it can go back in a PUT", st == 200 and b["goal"]["must_not"] == [{"name": "contact"}], b)
check("a goal id that is not a number is a 404", call("GET", "/goals/abc")[0] == 404)
st, b = call("POST", f"/goals/{gid}/runs", {"robots": ["fake-1"]})
rid = b["run"]["id"]
check("POST /goals/{id}/runs: 201, a running goal run linked to the goal", st == 201 and b["run"]["state"] == "running" and b["run"]["goal_id"] == gid)
check("a second run on the busy robot is 409 robot_busy", call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 0, "y": 0}}, "robots": ["fake-1"]})[1]["error"]["code"] == "robot_busy")
check("a running goal cannot be retired: 409", call("DELETE", f"/goals/{gid}")[0] == 409)
run = wait_run(rid)
check("GET /goal-runs/{id}: reached, with the merged guardrails and decisions", run["state"] == "reached" and run["as_expected"] is True
      and run["guardrails"] == [{"name": "contact", "from": ["goal"]}] and run["decisions"], run["state"])
st, b = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 9.0, "y": 0.0}, "expect": "refuse"}, "robots": ["fake-1"]})
check("POST /goal-runs, a goal not in the library: refused, as expected, and saves nothing",
      st == 201 and b["run"]["state"] == "refused" and b["run"]["as_expected"] is True and len(call("GET", "/goals")[1]["goals"]) == 1)
adhoc = b["run"]["id"]
st, b = call("POST", f"/goal-runs/{adhoc}/save", {"name": "off the map", "folder": "tests"})
check("POST /goal-runs/{id}/save puts its goal in the library", st == 201 and b["goal"]["name"] == "off the map" and len(call("GET", "/goals")[1]["goals"]) == 2)
check("GET /goal-runs lists, filtered", [r["id"] for r in call("GET", "/goal-runs?robot=fake-1")[1]["runs"]] == [adhoc, rid]
      and [r["id"] for r in call("GET", "/goal-runs?state=reached")[1]["runs"]] == [rid]
      and [r["id"] for r in call("GET", f"/goal-runs?goal={gid}")[1]["runs"]] == [rid])
st, b = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 3.5, "y": -2.0}}, "robots": ["fake-1"]})
long_run = b["run"]["id"]
ticks(1.0)
st, b = call("POST", f"/goal-runs/{long_run}/cancel")
check("POST /goal-runs/{id}/cancel: cancelled, robot stopped", st == 200 and b["run"]["state"] == "cancelled")
check("cancelling an ended run is 409", call("POST", f"/goal-runs/{long_run}/cancel")[0] == 409)
check("a team that does not exist is a 404; share: split is 501 not_built (RFC-0014 step 10)",
      call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 0, "y": 0}}, "team": "all"})[0] == 404
      and call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 0, "y": 0}}, "robots": ["fake-1", "blind"], "share": "split"})[1]["error"]["code"] == "not_built")
st, b = call("POST", "/plan", {"text": "make me a sandwich"})
check("POST /plan with nothing to propose and no LLM configured: 200, no goals, saying why (the phrase matcher is always there)", st == 200 and b["plan"]["goals"] == [] and "no LLM planner" in b["plan"]["message"], b)

# --- sites, areas, objects --------------------------------------------------------------------------
st, b = call("POST", "/sites", {"name": "Home", "kind": "apartment"})
check("POST /sites: 201, the site frame named", st == 201 and b["site"]["id"] == "home" and b["site"]["frame"] == "site")
check("POST a second site of any kind", call("POST", "/sites", {"name": "Garden", "kind": "garden"})[0] == 201 and len(call("GET", "/sites")[1]["sites"]) == 2)
check("PUT a site's name", call("PUT", "/sites/garden", {"name": "Back garden"})[1]["site"]["name"] == "Back garden")
check("DELETE retires it", call("DELETE", "/sites/garden")[0] == 200 and [s["id"] for s in call("GET", "/sites")[1]["sites"]] == ["home"])
check("a retired site is a 404", call("GET", "/sites/garden")[0] == 404)
check("PUT /robots/{id}/site", call("PUT", "/robots/fake-1/site", {"site": "home"})[1]["robot"]["site"] == "home")
st, b = call("POST", "/sites/home/areas", {"name": "Kitchen", "type": "kitchen", "outline": [[2.0, 0.5], [3.9, 0.5], [3.9, 2.9], [2.0, 2.9]]})
check("POST areas: the operator draws one", st == 201 and b["area"]["id"] == "kitchen" and b["area"]["frame"] == "site")
st, b = call("POST", "/sites/home/areas", {"name": "Bad", "outline": [[0, 0], [1, 1]]})
check("a bad outline is a 422 bad_outline", st == 422 and b["error"]["code"] == "bad_outline")
check("an area called 'At' does not shadow the point query", call("POST", "/sites/home/areas", {"name": "At", "outline": [[-1, -1], [-2, -1], [-2, -2]]})[1]["area"]["id"] == "at-2")
call("DELETE", "/sites/home/areas/at-2")
st, b = call("GET", "/sites/home/areas/at?x=3&y=1")
check("GET areas/at: which area holds a point of the site frame", st == 200 and b["area"]["id"] == "kitchen" and b["frame"] == "site")
st, b = call("GET", "/sites/home/areas/at?x=-3&y=-1")
check("none defined where there is none", b["area"] is None and b["message"] == "none defined")
check("x and y are needed", call("GET", "/sites/home/areas/at?x=3")[0] == 422)
check("PUT an area: rename and retype", call("PUT", "/sites/home/areas/kitchen", {"name": "Kitchen", "type": "galley"})[1]["area"]["type"] == "galley")
check("GET an area", call("GET", "/sites/home/areas/kitchen")[1]["area"]["name"] == "Kitchen")
st, b = call("POST", "/sites/home/areas/kitchen/split", {"line": [[3.0, 0.0], [3.0, 4.0]], "name": "Pantry"})
check("POST split: the area keeps the left, the new area the right", st == 200 and [a["id"] for a in b["areas"]] == ["kitchen", "pantry"], b)
st, b = call("POST", "/sites/home/areas/kitchen/merge", {"other": "pantry", "name": "Kitchen"})
check("POST merge folds one into the other", st == 200 and b["area"]["id"] == "kitchen" and call("GET", "/sites/home/areas/pantry")[0] == 404)
check("PUT guardrails: a no-go area by name, stored by id", call("PUT", "/sites/home/guardrails", {"guardrails": [{"name": "no_go_area", "area": "Kitchen"}]})[1]["guardrails"]
      == [{"name": "no_go_area", "area": "kitchen"}] and call("GET", "/sites/home/guardrails")[1]["guardrails"][0]["area"] == "kitchen")
check("an area in a guardrail cannot be deleted: 409", call("DELETE", "/sites/home/areas/kitchen")[1]["error"]["code"] == "area_in_use")
call("PUT", "/sites/home/guardrails", {"guardrails": []})

st, b = call("POST", "/goal-runs", {"goal": {"kind": "inventory", "params": {"areas": []}}, "robots": ["fake-1"]})
inv_run = wait_run(b["run"]["id"], 400)
check("an inventory goal over HTTP: done, the objects of the site by area", inv_run["state"] == "done" and [o["kind"] for o in inv_run["result"]["areas"][0]["objects"]] == ["fridge"], inv_run["result"])
st, b = call("GET", "/sites/home/objects")
fridge = next(o for o in b["objects"] if o["kind"] == "fridge")
check("GET /sites/{s}/objects: stable id, kind, area, parts, confidence, frame", fridge["id"] == "obj-1" and fridge["area"] == "kitchen"
      and fridge["parts"] and "confidence" in fridge and b["frame"] == "site", fridge)
st, b = call("POST", f"/sites/home/objects/{fridge['id']}/label", {"label": "the cold box"})
check("POST label names an object", st == 200 and b["object"]["label"] == "the cold box")
check("a second object cannot take the label: 409", call("POST", "/sites/home/objects/obj-2/label", {"label": "THE COLD BOX"})[0] == 409)
st, b = call("GET", "/sites/home/inventory")
check("GET inventory: confirmed objects by area, sightings and confidence", st == 200 and b["inventory"]["areas"][0]["objects"][0]["label"] == "the cold box"
      and len(b["inventory"]["none_defined"]) == 3, b)
check("the named object is an event", any(e["kind"] == "object-named" and e["label"] == "the cold box" for e in mc.bus.since(0, 100000)[0]))
check("no area was created by the run: still one", len(call("GET", "/sites/home/areas")[1]["areas"]) == 1)

# export and import
st, b = call("POST", "/sites/home/export")
bundle = b["bundle"]
check("POST /sites/{s}/export: the site, its areas and its labelled objects as one document", st == 200 and bundle["format"] == "mission-control-site"
      and [a["name"] for a in bundle["areas"]] == ["Kitchen"] and [o["label"] for o in bundle["objects"]] == ["the cold box"], bundle)
call("POST", "/sites", {"name": "Copy", "kind": "flat"})
st, b = call("POST", "/sites/copy/import", {"bundle": bundle})
check("POST /sites/{s}/import: the report says what was made", st == 200 and b["imported"]["areas"]["created"] == ["kitchen"]
      and b["imported"]["objects"]["created"] == ["obj-1"], b)
check("and the copy has them", call("GET", "/sites/copy/objects")[1]["objects"][0]["label"] == "the cold box"
      and call("GET", "/sites/copy/areas/at?x=3&y=1")[1]["area"]["id"] == "kitchen")
check("the bundle itself is accepted as the body too", call("POST", "/sites/copy/import", bundle)[1]["imported"]["areas"]["updated"] == ["kitchen"])
st, b = call("POST", "/sites/copy/import", {"bundle": {"format": "other"}})
check("a file that is not a site file is a 422 bad_bundle", st == 422 and b["error"]["code"] == "bad_bundle")
check("export of a site that is not there is a 404", call("POST", "/sites/nope/export")[0] == 404)

# the page is served by the same server
req = urllib.request.urlopen(BASE.replace("/api/v1", "/"), timeout=5)
html = req.read().decode()
check("GET / is the page", req.status == 200 and req.headers["Content-Type"].startswith("text/html") and "Mission Control" in html and "stop-all" in html)
req = urllib.request.urlopen(BASE.replace("/api/v1", "/web/app.js"), timeout=5)
check("and its script, as JavaScript", req.headers["Content-Type"].startswith("text/javascript") and b"EventSource" in req.read())
check("and its style", urllib.request.urlopen(BASE.replace("/api/v1", "/web/style.css"), timeout=5).headers["Content-Type"].startswith("text/css"))
for bad_path in ("/web/../core.py", "/web/nothing.js", "/web/%2e%2e%2fcore.py", "/web/.hidden"):
    try:
        urllib.request.urlopen(BASE.replace("/api/v1", bad_path), timeout=5)
        check(f"no file outside web/: {bad_path}", False)
    except urllib.error.HTTPError as exc:
        check(f"no file outside web/: {bad_path}", exc.code == 404)


# --- the event stream -------------------------------------------------------------------------------
def read_sse(url, want, out, ready, timeout=15.0):
    """Collect `want` events (kind, data) from an event stream."""
    resp = urllib.request.urlopen(url, timeout=timeout)
    first = resp.readline()
    ready.set()
    event = {}
    for raw in resp:
        line = raw.decode().rstrip("\n")
        if line.startswith(":"):
            continue
        if line == "":
            if event:
                out.append(event)
                event = {}
            if len(out) >= want:
                break
            continue
        key, _, value = line.partition(": ")
        event[key] = value
    resp.close()
    return first


out_all, ready_all = [], threading.Event()
t_all = threading.Thread(target=read_sse, args=(BASE + "/events?since=0", 5, out_all, ready_all))
t_all.start()
t_all.join(10)
check("the stream replays from `since` with a sequence number as the id, the kind as the event",
      len(out_all) == 5 and out_all[0]["id"] == "1" and [int(e["id"]) for e in out_all] == sorted(int(e["id"]) for e in out_all)
      and all(json.loads(e["data"])["seq"] == int(e["id"]) and json.loads(e["data"])["kind"] == e["event"] for e in out_all), out_all[:2])

# live: several clients at once, each with its own filter, while a STOP is sent and a goal runs
streams = {}
for name, query in (("all", ""), ("fake", "&robots=fake-1"), ("slow", "&state_hz=0.5&robots=fake-1"), ("blind", "&robots=blind"), ("run", "&goal_run=999")):
    out, ready = [], threading.Event()
    streams[name] = (out, ready)
now_seq = mc.bus.seq
threads = []
for name, query in (("all", ""), ("fake", "&robots=fake-1"), ("slow", "&state_hz=0.5&robots=fake-1"), ("blind", "&robots=blind"), ("run", "&goal_run=999")):
    out, ready = streams[name]
    t = threading.Thread(target=read_sse, args=(BASE + f"/events?since={now_seq}{query}", 10_000, out, ready, 20.0), daemon=True)
    t.start()
    threads.append(t)
check("five clients connect at once", all(r.wait(5) for _, r in streams.values()))
st, b = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 1.0, "y": 0.0}}, "robots": ["fake-1"]})
live_run = b["run"]["id"]
ticks(8.0, until=lambda: call("GET", f"/goal-runs/{live_run}")[1]["run"]["state"] in TERMINAL)
t0 = time.monotonic()
st, b = call("POST", "/stop", None, {"X-Client": "page"})
check("a STOP goes through while five streams are open", st == 200 and time.monotonic() - t0 < 2.0, time.monotonic() - t0)
time.sleep(0.5)
kinds = lambda name: [json.loads(e["data"]) for e in streams[name][0]]
check("a client with no filter sees every robot", {e.get("robot") for e in kinds("all")} >= {"fake-1", "blind"})
check("robots=fake-1 sees only that robot", kinds("fake") and all(e["robot"] == "fake-1" for e in kinds("fake")))
check("robots=blind sees only the other", kinds("blind") and all(e["robot"] == "blind" for e in kinds("blind")))
n_fast = sum(1 for e in kinds("fake") if e["kind"] == "state")
n_slow = sum(1 for e in kinds("slow") if e["kind"] == "state")
check("state_hz=0.5 lowers this subscription's state rate below the robot's own 2 Hz", n_fast >= 8 and 1 <= n_slow <= n_fast // 3, (n_fast, n_slow))
check("the goal run's decisions and outcome arrive as events", {"goal-run", "decision", "stop"} <= {e["kind"] for e in kinds("fake")}, {e["kind"] for e in kinds("fake")})
check("goal_run= filters to one run: nothing for run 999", kinds("run") == [])
seqs = [e["seq"] for e in kinds("all")]
check("the sequence is growing", seqs == sorted(seqs) and len(set(seqs)) == len(seqs))
check("a STOP is an event with who sent it", any(e["kind"] == "stop" and e["client"] == "page" for e in kinds("fake")))
st, b = call("GET", "/events?since=abc")
check("a bad subscription is a 422", st == 422)

server.shutdown()
server.server_close()
for t in threads:
    t.join(3)
check("shutting the server ends the streams", not any(t.is_alive() for t in threads))

# --- the real thing: threads, the real clock, curl-shaped calls --------------------------------------
live = MissionControl([RobotConfig(robot_file("real-fake", rates={"state_hz": 10.0, "map_hz": 1.0, "max_state_hz": 10.0}))], clock=time.monotonic, wall=time.time)
srv = serve(live, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()
live.start()
time.sleep(0.5)
st, b = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 0.8, "y": 0.4}}, "robots": ["real-fake"]})
rid = b["run"]["id"]
deadline = time.monotonic() + 20
state = "running"
while time.monotonic() < deadline and state not in TERMINAL:
    time.sleep(0.2)
    state = call("GET", f"/goal-runs/{rid}")[1]["run"]["state"]
check("over HTTP with the real clock and a thread per robot: the point goal reaches", state == "reached", state)
st, b = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": -3.5, "y": -2.5}}, "robots": ["real-fake"]})
rid = b["run"]["id"]
time.sleep(1.0)
t0 = time.monotonic()
st, b = call("POST", "/robots/real-fake/stop")
run = call("GET", f"/goal-runs/{rid}")[1]["run"]
check("STOP over HTTP while it drives: confirmed, and the run is cancelled at once", b["stop"]["confirmed"] is True and run["state"] == "cancelled"
      and time.monotonic() - t0 < 1.0, (run["state"], run["reason"]))
x0 = call("GET", "/robots/real-fake")[1]["robot"]["status"]["pose"]
time.sleep(1.0)
x1 = call("GET", "/robots/real-fake")[1]["robot"]["status"]["pose"]
check("and the robot stays where it stopped", abs(x1["x"] - x0["x"]) < 0.02 and abs(x1["y"] - x0["y"]) < 0.02, (x0, x1))
srv.shutdown()
srv.server_close()
live.close()

finish("test_api")
