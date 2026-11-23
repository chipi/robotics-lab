"""RFC-0014 step 2 on the real simulator: Mission Control's API, the gate, the navigator server and the real navigator, end to end.

    cd apps/mission-control && uv run python tests/sim_duck.py [--only point,cancel,...]      # make sim-duck

NOT in `make test-control`: it resets the simulator (via robots/duck/sim/reset_sim.py, ~45 s each time), moves the duck for minutes and
needs nobody else using it. Everything it writes goes to a folder of its own in the system temp dir: the Observatory's runs
(a data folder with a copy of the apartment scene), the navigator's output, Mission Control's state.

The processes: the gate (in this process, a thread, as the scenario test), lab-nav-server (the runner, a subprocess of its own, which
starts the navigator API as its own: RFC-0021 step 6), Mission Control (this process). Judged by the simulator's truth (the body
server), as the challenge judge is; the navigator API has no route to it (the last section)."""

import argparse
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import atexit
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import check, finish, installation_file

from labrunner.gate import Proxy
import simhost
from simhost.truth import Body
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig

REPO = Path(__file__).resolve().parents[3]
REAL_DATA = Path("/work/robotics-lab/data")
NAV_PORT = 18061

ap = argparse.ArgumentParser()
ap.add_argument("--only", help="comma separated: point, profile, cancel, stop, takeover, explore, inventory, object, area, speed, nogo, timelimit, drop")
ap.add_argument("--keep", action="store_true", help="keep the working folder (the gate's log, the navigator's runs) to read after a failure")
ap.add_argument("--profile", type=Path, help="seed the version store with this profile instead of the duck's own: a test profile whose body "
                "limits fire on a walk proves the alarm feed live (the point scenario then checks it)")
ap.add_argument("--no-truth", action="store_true", help="the runner is given this host's file with truth_port null, as a real robot's: "
                "only the notruth scenario runs (phase 5 item 4); this test still reads the simulator's truth itself, to judge")
ARGS = ap.parse_args()
only = set(ARGS.only.split(",")) if ARGS.only else None
if ARGS.no_truth:
    only = {"notruth"}
elif only is not None and "notruth" in only:
    raise SystemExit("the notruth scenario runs with --no-truth")


def wanted(name):
    return only is None or name in only


def wait_for(cond, timeout, every=0.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(every)
    return None


tmp = Path(tempfile.mkdtemp(prefix="mc-sim-duck-"))
if not ap.parse_args().keep:
    atexit.register(shutil.rmtree, tmp, True)
print("working in", tmp, flush=True)
data = tmp / "data"
(data / "scenes" / "apartment").mkdir(parents=True)
shutil.copy(REAL_DATA / "scenes" / "apartment" / "scene.json", data / "scenes" / "apartment" / "scene.json")     # a read of the real folder, a copy
(data / "runs").mkdir()

HOST = simhost.load()      # the host this test drives (RFC-0021); the nav server reads the same file
proxy = body = None


def fresh_sim():
    """The simulator back at the dock with a fresh map (robots/duck/sim/reset_sim.py, the only way this test restarts it), and a new gate in
    front of the new robotd: the old gate's upstream connection died with the old robotd."""
    global proxy, body
    if proxy is not None:
        proxy.stop()
    print("resetting the simulator (robots/duck/sim/reset_sim.py) ...", flush=True)
    subprocess.run([str(REPO / "robots" / "duck" / ".venv" / "bin" / "python"), "sim/reset_sim.py"], cwd=REPO / "robots" / "duck", check=True, timeout=400)
    body = Body(HOST.truth_port)
    proxy = Proxy(tmp / "gate.sock", HOST.sockets["robot"], log=tmp / "gate.jsonl", lease_s=20.0, takeover_names={"operator-laptop"})
    proxy.start()


# the test's own installation (phase 5 step 1): the duck registered by its file, so the runner starts the duck's navigator with the
# duck's own Python, and nothing of the duck is installed beside Mission Control; this machine's installation is not read
# The duck runs on this machine's version store (seeded with its own profile as version 1), so the profile scenario saves a version
# through Mission Control and the next goal's navigator and referee both run it
from runfile.profilestore import Store  # noqa: E402
STORE = tmp / "inst-state" / "profiles"
Store(STORE).seed("duck", ARGS.profile or REPO / "robots" / "duck" / "profile.json")
# --no-truth: the duck is still the simulated one, so the installation names its variant (sim): the runner's default without a truth
# is real, Mission Control's for the duck-sim adapter is sim, and only the installation makes them one
os.environ["ROBOTICS_LAB_INSTALLATION"] = str(installation_file(tmp / "installation.json", {"duck": {"profile": str(STORE / "duck"),
                                                                **({"variant": "sim"} if ARGS.no_truth else {})}},
                                                                state=str(tmp / "inst-state")))
HOST_ARGS = []
if ARGS.no_truth:
    raw_host = json.loads(Path(HOST.source).read_text())
    (tmp / "host-notruth.json").write_text(json.dumps({**raw_host, "truth_port": None}))
    HOST_ARGS = ["--host", str(tmp / "host-notruth.json")]
clean = [True]
fresh_sim()
navlog = open(tmp / "nav-server.log", "w")
nav_proc = subprocess.Popen([sys.executable, "-m", "labrunner.navapi", *HOST_ARGS, "--listen", f"127.0.0.1:{NAV_PORT}", "--robot-socket", str(tmp / "gate.sock"),
                             "--data", str(data), "--out", str(tmp / "nav"), "--scene", "apartment"], stdout=navlog, stderr=subprocess.STDOUT)
wait_for(lambda: "lab-nav-server" in (tmp / "nav-server.log").read_text(), 30, 0.2)

# a pointer to the duck's profile (phase 5 step 1): the addresses are this test's own
FILE = {"id": "duck-sim", "label": "Simulated duck", "robot": "duck", "variant": "sim",
        "adapter": {"type": "duck-sim", "gate_socket": str(tmp / "gate.sock"), "navigator": f"127.0.0.1:{NAV_PORT}",
                    "observatory": "http://127.0.0.1:8070"}}
mc = MissionControl([RobotConfig(FILE)], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()


def call(method, path, body_=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body_).encode() if body_ is not None else None, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def robot():
    return call("GET", "/robots/duck-sim")["robot"]


def run_of(rid):
    return call("GET", f"/goal-runs/{rid}")["run"]


def finished(rid, timeout):
    return wait_for(lambda: run_of(rid)["state"] not in ("queued", "running") and run_of(rid), timeout)


def start(goal, **extra):
    return call("POST", "/goal-runs", {"goal": goal, "robots": ["duck-sim"], **extra})["run"]


try:
    check("the duck is online through the gate", wait_for(lambda: robot()["online"], 30) is not None and robot()["status"]["pose"]["frame"] == "site", robot()["status"])
    check("the map is the navigator API's (mapd's), in the site frame", call("GET", "/robots/duck-sim/map")["map"]["kind"] == "occupancy_grid")
    call("POST", "/sites", {"name": "Home", "kind": "apartment"})
    call("PUT", "/robots/duck-sim/site", {"site": "home"})

    if wanted("point"):
        print("\n--- point goal", flush=True)
        clean[0] = False
        t0 = body.pose()
        run = start({"kind": "point", "params": {"x": 1.5, "y": 0.5}})
        check("the run starts with its Observatory run key at once and a Watch link", run["state"] == "running" and (run["run_key"] or "").startswith("duck/apartment/mc")
              and run["watch"] == "http://127.0.0.1:8070/watch/" + run["run_key"], run)
        check("the navigator holds the lease while it moves the robot", wait_for(lambda: robot()["lock"]["holder"] == "lab-nav-server", 60) is not None, robot()["lock"])
        end = finished(run["id"], 180)
        check("the real navigator reaches the point (truth within 0.5 m)", end and end["state"] == "reached" and math.dist(body.pose()[:2], (1.5, 0.5)) < 0.5,
              end and (end["state"], end["reason"], body.pose()))
        check("its decisions are relayed, with rules", end and len(end["decisions"]) > 0 and all(d.get("rule") for d in end["decisions"]), end and end["decisions"][:3])
        if ARGS.profile:
            kinds = sorted({a["anomaly"] for a in (end or {}).get("anomalies", [])})
            live = [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "anomaly" and e.get("goal_run") == run["id"]]
            check("must fail: the navigator's anomalies (the test profile's body limits) are kept with the run and were on the event stream live, "
                  "each with the Observatory's page at its moment", kinds and len(live) == len(end["anomalies"])
                  and all(e["watch"].startswith("http://127.0.0.1:8070/watch/" + run["run_key"] + "#t=") for e in live), (kinds, len(live)))
        check("the lease is given back", wait_for(lambda: robot()["lock"]["holder"] is None, 10) is not None, robot()["lock"])
        key = run["run_key"]
        run_dir = data / "runs" / key
        check("the Observatory run is written under the test's own data folder", run_dir.exists() and any(run_dir.glob("*.mcap")), list(run_dir.glob("*")) if run_dir.exists() else None)
        from runfile import mcapio
        rec = next((p for _, kind, p in mcapio.read(run_dir) if kind == "run"), None)
        check("the Observatory run carries the goal run (id and name) in its record", rec is not None and rec.get("goal_run", {}).get("id") == run["id"]
              and rec["goal_run"]["name"] == "ad-hoc point", rec)

    def runner_json(run):
        """lab-nav-server's record of a goal: the profile it judged by, and the one the navigator said it runs."""
        p = tmp / "nav" / run["run_key"].rsplit("/", 1)[-1] / "runner.json"
        wait_for(p.exists, 20)
        return json.loads(p.read_text()) if p.exists() else {}

    if wanted("profile"):
        print("\n--- profile versions, live", flush=True)
        v2 = json.loads((STORE / "duck" / "1.json").read_text())
        v2["locomotion"]["why"] = "sim_duck: a version saved while Mission Control runs"     # a note: a new identity, no new behaviour
        saved = call("POST", "/robots/duck-sim/profile", {"profile": v2}).get("saved") or {}
        check("Mission Control saves a version while it runs: version 2, from the next goal", saved.get("version") == 2, saved)
        for want_v in (2, 1):
            if want_v == 1:
                check("going back to version 1 through Mission Control", call("PUT", "/robots/duck-sim/profile/current", {"version": 1})
                      .get("profile", {}).get("current") == 1)
            # what is checked is what both sides read at goal.start; the goal itself may end refused ("no path on the map": after the
            # point scenario alone the map has no route there, seen 2026-11-22), which is the navigator's to say, not this check's
            run = start({"kind": "point", "params": {"x": 0.6, "y": 0.0}})
            end = finished(run["id"], 120)
            rj = runner_json(run)
            judge, theirs = rj.get("judge_profile") or {}, rj.get("navigator_profile") or {}
            check(f"must fail: the goal after version {want_v} is chosen: the navigator runs it and the referee judges by it, one checksum",
                  end is not None and judge.get("version") == want_v and theirs.get("version") == want_v
                  and judge.get("checksum") == theirs.get("checksum"), (end and (end["state"], end["reason"]), judge, theirs))
        clean[0] = False

    def stands_still():
        a = body.pose()
        time.sleep(1.5)
        return math.dist(a[:2], body.pose()[:2]) < 0.03

    def need_clean():
        """A scenario that must start from the dock with a fresh map: a reset unless nothing has moved since the last one."""
        if not clean[0]:
            fresh_sim()
            wait_for(lambda: robot()["online"], 60)
        clean[0] = False

    def long_goal():
        need_clean()
        run = start({"kind": "explore", "params": {"site": True}, "budget": {"minutes": 5}})
        wait_for(lambda: robot()["lock"]["holder"] == "lab-nav-server", 60)
        t0 = body.pose()
        wait_for(lambda: math.dist(body.pose()[:2], t0[:2]) > 0.2, 120)       # the survey turns first; it walks after
        return run

    if wanted("cancel"):
        print("\n--- cancel", flush=True)
        run = long_goal()
        t = time.monotonic()
        reply = call("POST", f"/goal-runs/{run['id']}/cancel")
        if "run" not in reply:
            print("cancel answered", reply, "; the run was", run_of(run["id"]), flush=True)
        end = reply["run"]
        check("cancel: the run is cancelled, the navigator stopped, the lease given back", end["state"] == "cancelled" and robot()["lock"]["holder"] is None
              and time.monotonic() - t < 12, (end["state"], end["reason"]))
        check("the robot stands (truth)", stands_still())
        check("the Observatory run was closed", any((data / "runs" / end["run_key"]).glob("run.mcap")))

    if wanted("stop"):
        print("\n--- STOP", flush=True)
        run = long_goal()
        stop = call("POST", "/robots/duck-sim/stop", {"client": "page"})["stop"]
        end = finished(run["id"], 20)
        check("STOP goes to the robot through the gate, confirmed", stop["confirmed"] is True, stop)
        check("the run ends cancelled, by the latch, with who stopped it", end and end["state"] == "cancelled" and "stopped by page" in end["reason"], end and (end["state"], end["reason"]))
        check("the robot stands (truth) and is free", stands_still() and robot()["lock"]["holder"] is None)
        check("STOP-all too", call("POST", "/stop")["stop"]["all_confirmed"] is True)

    if wanted("takeover"):
        print("\n--- takeover", flush=True)
        run = long_goal()
        tk = call("POST", "/robots/duck-sim/lock/takeover", {"client": "operator-laptop"})
        end = finished(run["id"], 20)
        check("the operator's takeover interrupts the run (not cancelled)", tk["ok"] and end and end["state"] == "interrupted" and "taken over by operator-laptop" in end["reason"],
              end and (end["state"], end["reason"]))
        check("the robot stood still when it was taken, and the operator holds it", stands_still() and robot()["lock"]["holder"] == "operator-laptop")
        call("DELETE", "/robots/duck-sim/lock", {"session": tk["lock"]["session"]})

    if wanted("explore"):
        print("\n--- explore the site", flush=True)
        need_clean()
        run = start({"kind": "explore", "params": {"site": True}, "budget": {"minutes": 1.5}})
        end = finished(run["id"], 400)
        # The duck's explorer sometimes ends "trapped" (6 refusals in a row; the explore-apartment stream's own outcome, seen in some runs here and not in others).
        # Mission Control reports it as failed with that reason, which is the honest result, so this accepts it; what it merged is checked below either way.
        trapped = bool(end) and end["state"] == "failed" and end["reason"] == "the robot was trapped"
        check("explore {site} ends done by its budget or by no frontier left, with its coverage, or failed as trapped, saying so", trapped or (end and end["state"] == "done"
              and end["result"]["cells_explored"] > 100 and end["result"]["ended_by"] in ("budget", "no_frontier_left")), end and (end["state"], end["reason"], end["result"]))
        if trapped:
            print("   (this run ended trapped)", flush=True)
        objs = call("GET", "/sites/home/objects")["objects"]
        print("   objects found:", [(o["id"], o["kind"], o["n"], o["confirmed"]) for o in objs], flush=True)
        check("what the real navigator saw is merged into the site with stable ids", len(objs) >= 1 and all(o["id"].startswith("obj-") for o in objs), objs)
        check("no area was created by it", call("GET", "/sites/home/areas")["areas"] == [])

    if wanted("inventory"):
        print("\n--- inventory", flush=True)
        call("POST", "/sites/home/areas", {"name": "Flat", "outline": [[-4.2, -3.2], [4.2, -3.2], [4.2, 3.2], [-4.2, 3.2]]})
        run = start({"kind": "inventory", "params": {"areas": []}, "budget": {"minutes": 1}})
        end = finished(run["id"], 400)
        listed = ((end or {}).get("result") or {}).get("areas", [])     # a run that did not end done has no result: reported below
        confirmed = [o for o in call("GET", "/sites/home/objects")["objects"] if o["confirmed"]]
        check("inventory: done, the confirmed objects listed by the operator's area, with the site's ids", end and end["state"] == "done" and listed
              and listed[0]["name"] == "Flat" and {o["id"] for o in listed[0]["objects"]} <= {o["id"] for o in confirmed}, end and (end["state"], end["reason"], end["result"]))
        listed_ids = sorted(o["id"] for o in listed[0]["objects"]) if listed else []
        missing = [(o["id"], o["kind"], round(o["x"], 2), round(o["y"], 2)) for o in confirmed if o["id"] not in listed_ids]
        check("the Flat holds what is confirmed", len(listed_ids) == len(confirmed) if listed else False,
              f"listed {len(listed_ids)}, confirmed {len(confirmed)}, not listed {missing}")

    if wanted("object"):
        print("\n--- go to an object", flush=True)
        clean[0] = False                          # explore and inventory leave the duck wherever they ended, maybe against a cabinet
        need_clean()
        confirmed = [o for o in call("GET", "/sites/home/objects")["objects"] if o["confirmed"]]
        if not confirmed:
            check("an object is known to go to (explore first)", False)
        else:
            target = confirmed[0]
            call("POST", f"/sites/home/objects/{target['id']}/label", {"label": "the target"})
            run = start({"kind": "go_to_object", "params": {"label": "the target"}, "budget": {"minutes": 3}})
            end = finished(run["id"], 400)
            check("go_to_object by the operator's label, from the site's map: reached, the object and the stand in the result",
                  end and end["state"] == "reached" and end["result"]["object"]["id"] == target["id"] and end["result"]["object"]["label"] == "the target"
                  and end["result"]["stand"], end and (end["state"], end["reason"], end["result"]))
            tx, ty = target["x"], target["y"]
            check("the robot stands near it (truth within 1.2 m of its position)", math.dist(body.pose()[:2], (tx, ty)) < 1.2, (body.pose(), (tx, ty)))
            check("its decisions say it went to the object", end and any("went to the" in d["text"] for d in end["decisions"]), end and [d["text"] for d in end["decisions"]][-4:])
            run = start({"kind": "go_to_object", "params": {"label": "the unicorn"}, "budget": {"minutes": 0.5}})
            end = finished(run["id"], 60)
            check("an object nobody knows is not_found, at once", end and end["state"] == "not_found", end and (end["state"], end["reason"]))

    if wanted("area"):
        print("\n--- go to an area", flush=True)
        clean[0] = False
        need_clean()
        call("POST", "/sites/home/areas", {"name": "Dock", "outline": [[-0.7, -0.7], [0.9, -0.7], [0.9, 0.7], [-0.7, 0.7]]})
        run = start({"kind": "go_to_area", "params": {"area": "dock"}})
        end = finished(run["id"], 300)
        check("go_to_area: the robot is inside the operator's outline (truth)", end and end["state"] == "reached" and -0.8 < body.pose()[0] < 1.0 and -0.8 < body.pose()[1] < 0.8,
              end and (end["state"], end["reason"], body.pose()))

    # --- guardrails, enforced in the real navigator (RFC-0014 section 3.4.8) -----------------------------------
    def watch_truth(rid, timeout, inside_of=None):
        """Follow a run by the truth until it ends: (the peak speed over 0.5 s windows, whether the trunk was ever inside a polygon, the run)."""
        from worldmodel.site import inside
        peak, entered, last, end = 0.0, False, None, time.monotonic() + timeout
        while time.monotonic() < end:
            p, now = body.pose(), time.monotonic()
            if last is not None and now - last[1] >= 0.5:
                peak = max(peak, math.dist(p[:2], last[0][:2]) / (now - last[1]))
                last = (p, now)
            elif last is None:
                last = (p, now)
            if inside_of and inside(p[:2], inside_of):
                entered = True
            run = run_of(rid)
            if run["state"] not in ("queued", "running"):
                return peak, entered, run
            time.sleep(0.1)
        return peak, entered, run_of(rid)

    if wanted("speed"):
        print("\n--- max_speed", flush=True)
        need_clean()
        r1 = start({"kind": "point", "params": {"x": 1.5, "y": 0.5}})
        peak1, _, end1 = watch_truth(r1["id"], 200)
        clean[0] = False
        need_clean()                           # the same goal from the same start: the only difference is the cap
        r2 = start({"kind": "point", "params": {"x": 1.5, "y": 0.5}, "must_not": [{"name": "max_speed", "mps": 0.2}]})
        peak2, _, end2 = watch_truth(r2["id"], 300)
        print(f"   peak truth speed: uncapped {peak1:.3f} m/s, capped at 0.2: {peak2:.3f} m/s", flush=True)
        check("both runs reach their point", end1["state"] == "reached" and end2["state"] == "reached", (end1["state"], end2["state"], end2["reason"]))
        check("the cap is in the run's merged guardrails, from the goal", end2["guardrails"] == [{"name": "max_speed", "mps": 0.2, "from": ["goal"]}], end2["guardrails"])
        check("with the cap the robot walks measurably slower (truth) and not above the cap by more than the gait's own wobble",
              peak2 < 0.9 * peak1, (peak1, peak2))

    if wanted("nogo"):
        print("\n--- a no-go area", flush=True)
        need_clean()
        block = [[0.5, -0.6], [0.9, -0.6], [0.9, 0.4], [0.5, 0.4]]
        call("POST", "/sites/home/areas", {"name": "Block", "outline": block})
        call("PUT", "/sites/home/guardrails", {"guardrails": [{"name": "no_go_area", "area": "Block"}]})
        run = start({"kind": "point", "params": {"x": 1.5, "y": 0.5}})
        start_pose = body.pose()
        _, entered, end = watch_truth(run["id"], 300, [tuple(p) for p in block])
        moved = math.dist(body.pose()[:2], start_pose[:2])
        check("the straight way crosses the site's no-go area: the planner never paths through it (it goes round, or the goal is refused or "
              "not reached in time) and the robot never enters it (truth), though it did walk", end["state"] in ("reached", "refused", "timeout", "stalled") and not entered and moved > 0.25,
              (end["state"], end["reason"], entered, moved))
        check("the guardrail did not stop the run: the planner kept the robot out, which is the point of putting it in the planner", end["broken"] is None, end["broken"])
        check("the run's guardrails say the no-go area is the site's", {"name": "no_go_area", "area": "block", "from": ["site"]} in end["guardrails"], end["guardrails"])
        print("   outcome:", end["state"], end["reason"], flush=True)
        call("PUT", "/sites/home/guardrails", {"guardrails": []})
        call("DELETE", "/sites/home/areas/block")

    if wanted("timelimit"):
        print("\n--- time_limit", flush=True)
        need_clean()
        run = start({"kind": "explore", "params": {"site": True}, "budget": {"minutes": 5}, "must_not": [{"name": "time_limit", "seconds": 12}]})
        end = finished(run["id"], 120)
        check("the time limit stops the run: stopped_by_guardrail, which guardrail broke", end and end["state"] == "stopped_by_guardrail"
              and end["broken"]["name"] == "time_limit", end and (end["state"], end["reason"], end["broken"]))
        check("it is not 'failed': the decision with its reason is in the run", end and any("guardrail broken" in d["text"] and d.get("rule") == "guardrail" for d in end["decisions"]),
              end and [d["text"] for d in end["decisions"]][-3:])
        check("the robot stands (truth) and the lease is back", stands_still() and robot()["lock"]["holder"] is None)

    if wanted("drop"):
        print("\n--- drop_clearance", flush=True)
        need_clean()
        run = start({"kind": "point", "params": {"x": 0.5, "y": 0.0}, "must_not": [{"name": "drop_clearance", "m": 3.0}]})
        end = finished(run["id"], 60)
        check("a drop within 3 m of the dock breaks drop_clearance 3.0 at once (truth)", end and end["state"] == "stopped_by_guardrail"
              and end["broken"]["name"] == "drop_clearance", end and (end["state"], end["reason"], end["broken"]))
        check("the robot stands (truth)", stands_still())
        run = start({"kind": "point", "params": {"x": 1.5, "y": 0.5}, "must_not": [{"name": "drop_clearance", "m": 0.1}, "contact", "fall", "stuck"]})
        end = finished(run["id"], 200)
        check("with 0.1 m, no contact, no fall, no stuck the same robot reaches its point: the guardrails do not stop a good run",
              end and end["state"] == "reached" and end["broken"] is None, end and (end["state"], end["reason"], end["broken"]))

    if wanted("notruth"):
        print("\n--- no truth (phase 5 item 4): the runner as on a real robot", flush=True)
        asked = [{"name": "drop_clearance", "m": 3.0}, "contact", "fall"]
        run = start({"kind": "point", "params": {"x": 0.5, "y": 0.0}, "must_not": asked})
        end = finished(run["id"], 180)
        check("must fail: with a truth, drop_clearance 3.0 breaks at once by the dock (the drop scenario); without one the goal runs, "
              "nothing is broken", end and end["state"] != "stopped_by_guardrail" and end["broken"] is None,
              end and (end["state"], end["reason"], end["broken"]))
        unenf = [a for a in (end or {}).get("anomalies", []) if a.get("anomaly") == "guardrail_unenforced"]
        live = [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "anomaly" and e.get("goal_run") == run["id"]]
        check("must fail: one guardrail_unenforced alarm per truth guardrail asked, from the harness, kept with the run and live on "
              "the event stream", sorted((a.get("values") or {}).get("guardrail") for a in unenf) == ["contact", "drop_clearance", "fall"]
              and all(a.get("source") == "harness" for a in unenf) and len(live) >= 3, (unenf, len(live)))
        rj = runner_json(run)
        check("must fail: lab-nav-server's record: not enforced, in the order asked, no truth sampled, judge_truth not available",
              rj.get("not_enforced") == ["drop_clearance", "contact", "fall"] and rj.get("truth_samples") == 0
              and (rj.get("judge_truth") or {}).get("available") is False, {k: rj.get(k) for k in ("not_enforced", "truth_samples", "judge_truth")})
        from runfile import mcapio
        rec = next((p for _, kind, p in mcapio.read(data / "runs" / run["run_key"]) if kind == "run"), None) if end else None
        check("the Observatory run's record says the truth it was judged by: none, and what was not enforced",
              rec is not None and (rec.get("judge_truth") or {}).get("unenforced") == ["drop_clearance", "contact", "fall"],
              rec and rec.get("judge_truth"))
        check("the runner served no camera", "camera none" in (tmp / "nav-server.log").read_text())

    # --- the split (RFC-0021 step 6): the navigator behind its runner, with no route to the truth ---------------------
    print("\n--- the split", flush=True)
    time.sleep(1.0)                  # the runner's watch finishes the last goal's copy within a poll

    def runner_status():
        with socket.create_connection(("127.0.0.1", NAV_PORT), timeout=10) as s:
            s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "runner.status"}) + "\n").encode())
            return json.loads(s.makefile().readline())["result"]
    st = runner_status()
    last = st["last_goal"] or {}
    route = {"checks": st["truth_connections"]["checks"] + last.get("truth_connections", {}).get("checks", 0),
             "max": max(v for v in (st["truth_connections"]["max"], last.get("truth_connections", {}).get("max"), 0) if v is not None)}
    copy = last.get("truth_copy") or {}
    if ARGS.no_truth:
        check("without a truth the runner looked for no route to it, and the official run pairs no tick",
              route["checks"] == 0 and copy.get("ticks", 0) > 0 and copy.get("paired") == 0, (route, copy))
    else:
        check("the navigator API's process held no connection to the truth's port, looked at while each goal ran",
              route["checks"] > 0 and route["max"] == 0, (st["goals"], route))
        check("the last goal's official run is the runner's copy with the truth put in: every tick paired",
              copy.get("ticks", 0) > 0 and copy.get("paired") == copy.get("ticks"), copy)
    key = last.get("key")
    check("that run is in the Observatory's data folder under the key goal.start answered with",
          bool(key) and (data / "runs" / key).is_dir(), key)

finally:
    srv.shutdown()
    srv.server_close()
    mc.close()
    proxy.stop()
    nav_proc.terminate()
    try:
        nav_proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        nav_proc.kill()
    print("nav server log tail:\n" + (tmp / "nav-server.log").read_text()[-1500:], flush=True)

finish("sim_duck")
