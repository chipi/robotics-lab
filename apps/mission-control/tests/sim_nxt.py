"""Mission Control on the NXT simulator, end to end (phase 5 item 4d, unit D7): the NXT's `sim_duck`.

    cd apps/mission-control && uv run python tests/sim_nxt.py [--only drive,wall,...]      # make sim-nxt

NOT in `make test-control`: it starts the kinematic simulator (nxt-web --sim, in the apartment) through simhost, the host kind
`nxt-kinematic-sim`, and the Observatory's server, and drives for about a minute. It needs no Pollen, no brick and no other simulator, and moves
nothing real. Everything it writes goes to a folder of its own in the system temp dir: nxt-web's data and config, the run recordings (a data
folder with the Observatory's index), the test installation file, the host file, Mission Control's state.

The processes: nxt-web --sim (a subprocess simhost starts and stops, so it is the robot's gate), Mission Control (this process, its HTTP API
on a free port), the Observatory (a subprocess, its own environment, for the replay). The driver is a client of Mission Control's API alone:
the lock, the drive, STOP, takeover. Judged by the simulator's truth (`/api/sim/truth`, through simhost's reader), as the duck's test is;
nxt-web's own status says what the brick would have done, the truth says where the robot is.

The takeover list is the host file's `takeover_names`, which simhost passes to nxt-web, so the takeover scenario runs on the same nxt-web as
the others."""

import argparse
import atexit
import json
import math
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import check, finish

import simhost
from simhost import nxt as simnxt
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig

REPO = Path(__file__).resolve().parents[3]
CONTROL = REPO / "apps" / "mission-control"
OBSERVATORY = REPO / "apps" / "observatory" / ".venv" / "bin" / "observatory"
SCENE = REPO / "scenes" / "apartment" / "scene.json"
START = (0.0, 2.0, math.pi / 2)           # facing north, down the corridor to the north wall
SCENARIOS = ("drive", "wall", "stop", "takeover", "deadman", "replay")

ap = argparse.ArgumentParser()
ap.add_argument("--only", help="comma separated: " + ", ".join(SCENARIOS) + " (replay needs a run, so it drives once itself when no scenario before it did)")
ap.add_argument("--keep", action="store_true", help="keep the working folder (nxt-web's log, the runs, Mission Control's state) to read after a failure")
ARGS = ap.parse_args()
only = set(ARGS.only.split(",")) if ARGS.only else None
if only is not None and only - set(SCENARIOS):
    raise SystemExit(f"--only takes {', '.join(SCENARIOS)}; not {sorted(only - set(SCENARIOS))}")


def wanted(name):
    return only is None or name in only


def wait_for(cond, timeout, every=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(every)
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def raw(method, url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


tmp = Path(tempfile.mkdtemp(prefix="mc-sim-nxt-"))
if not ARGS.keep:
    atexit.register(shutil.rmtree, tmp, True)
print("working in", tmp, flush=True)
data = tmp / "data"                       # the Observatory's data folder: nxt-web writes its runs here, the Observatory serves them
(data / "runs").mkdir(parents=True)
(tmp / "nxt-data").mkdir()
NXT_PORT, OBS_PORT = free_port(), free_port()
NXT = f"http://127.0.0.1:{NXT_PORT}"
(tmp / "takeover.txt").write_text("operator-laptop  # may take the lock back\n")

# the test's own installation (the NXT registered by its file, in the sim variant, nxt-web's address its connection) and host file: this
# machine's are never read
os.environ["ROBOTICS_LAB_INSTALLATION"] = str(tmp / "installation.json")
(tmp / "installation.json").write_text(json.dumps({"installation": 1, "robots": {"nxt-shooterbot": {
    "registration": str(REPO / "robots" / "nxt-shooterbot" / "registration.json"), "variant": "sim", "placement": "workstation",
    "connections": {"nxt-web": NXT}}}}))
(tmp / "host.json").write_text(json.dumps({"host": 1, "kind": "nxt-kinematic-sim", "robot": "nxt-1", "state": str(tmp / "sim-state"),
                                           "nxt_web": {"url": NXT, "project": str(REPO / "apps" / "nxt-web")}, "scene": str(SCENE),
                                           "start": list(START), "params": None, "takeover_names": str(tmp / "takeover.txt")}))
# nxt-web, started by simhost, inherits these: its config and data in the scratch folder, its recordings where the Observatory reads them
os.environ["NXT_LAB_DATA"] = str(tmp / "nxt-data")
os.environ["OBSERVATORY_DATA"] = str(data)
HOST = simhost.load(tmp / "host.json")
own: list = []                            # the processes this test started itself (the Observatory)

mc = MissionControl([RobotConfig(json.loads((CONTROL / "robots.nxt-registered" / "nxt-1.json").read_text()))], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()


def call(method, path, body=None):
    return raw(method, BASE + path, body)


def robot():
    return call("GET", "/robots/nxt-1")[1]["robot"]


def status():
    return robot()["status"] or {}


def truth():
    return simnxt.read_truth(HOST)[1]


def nxt_status():
    return raw("GET", NXT + "/api/status")[1]


def _try(fn):
    try:
        return fn()
    except OSError:
        return False


def nxt_up():
    return _try(lambda: nxt_status().get("connected") is True)


def alarms(name):
    return [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "anomaly" and e["anomaly"]["anomaly"] == name]


def fresh_sim():
    """The simulator back at the start pose through simhost (nxt-web restarted), and Mission Control reconnected to it: nobody holds the
    robot and nothing of the last session's recording is left."""
    simhost.reset(HOST)
    if not wait_for(lambda: robot()["online"] and robot()["lock"]["holder"] is None and not status().get("recording") and "sensors" in status(), 30):
        raise SystemExit(f"Mission Control does not see the restarted simulator: {robot()}")


def hold(session, vx, vyaw, seconds, until=None):
    """Drive as a client does: the command again every 200 ms (a command lasts the deadman's 0.6 s), for `seconds` or until `until()`."""
    end, code = time.monotonic() + seconds, 200
    while time.monotonic() < end and not (until and until()):
        code = call("POST", "/robots/nxt-1/drive", {"session": session, "vx": vx, "vyaw": vyaw})[0]
        time.sleep(0.2)
    return code


def acquire(client):
    st, b = call("POST", "/robots/nxt-1/lock", {"client": client})
    return b["lock"]["session"] if st == 200 else None


def release(session):
    call("DELETE", "/robots/nxt-1/lock", {"session": session})


def recording_key():
    return (status().get("recording") or {}).get("run")


def stands_still(seconds=0.6):
    a = truth()
    time.sleep(seconds)
    return math.dist(a[:2], truth()[:2]) < 1e-3 and abs(a[2] - truth()[2]) < 1e-3


def north_wall_face(x, y):
    """Where the scene's wall is, straight ahead of (x, y) going north: the nearest box face above y whose span holds x (the scene file's
    own numbers, not the simulator's ultrasonic)."""
    boxes = json.loads(SCENE.read_text())["boxes"]
    return min(b["cy"] - b["hy"] for b in boxes if abs(x - b["cx"]) <= b["hx"] and b["cy"] - b["hy"] > y)


runs: dict = {}                           # scenario -> the key of the run its session left, for the replay
wall_stop_y = None                        # where the live truth stood at the wall, which the replayed truth must reach
try:
    fresh_sim()
    print("\n--- the simulator, started by simhost", flush=True)
    st = nxt_status()
    check("simhost started nxt-web in the simulator, in the apartment's scene, and it answers connected", st.get("connected") is True and st.get("fake") is True, {k: st.get(k) for k in ("connected", "fake")})
    pose = truth()
    check("the truth reads the start pose (0, 2, facing north) within 1 mm and 1 mrad",
          abs(pose[0] - START[0]) < 1e-3 and abs(pose[1] - START[1]) < 1e-3 and abs(pose[2] - START[2]) < 1e-3, pose)
    r = robot()
    check("Mission Control has the NXT online through its registration: the shooterbot, the sim variant, only the ultrasonic declared (colour is not simulated)",
          r["online"] and r["profile"]["robot"] == "nxt-shooterbot" and r["profile"]["variant"] == "sim" and [s["id"] for s in r["capabilities"]["sensors"]] == ["ultrasonic"],
          (r["online"], (r.get("profile") or {}).get("robot"), (r.get("profile") or {}).get("variant")))
    check("free, and the facts line has a real range: the north wall is about 0.84 m ahead of the sensor",
          wait_for(lambda: 0.5 < ((status().get("sensors") or {}).get("ultrasonic") or {}).get("range_m", 0) < 1.1, 5) and robot()["lock"]["holder"] is None,
          status().get("sensors"))

    # --- drive by hand: the lock, the drive, the truth ---------------------------------------------------------------------------
    if wanted("drive"):
        print("\n--- drive by hand through Mission Control's API", flush=True)
        fresh_sim()
        sess = acquire("sim-nxt")
        check("a client takes the lock through Mission Control, and nxt-web's lock names it", sess is not None and wait_for(lambda: robot()["lock"]["holder"] == "sim-nxt", 5)
              and raw("GET", NXT + "/api/lock")[1]["holder"] == "sim-nxt", robot()["lock"])
        check("the session started the recording, and the robot's state says it is Mission Control's", wait_for(lambda: (status().get("recording") or {}).get("ours") is True, 5)
              and status().get("recording_error") is None, status().get("recording"))
        key = recording_key()
        a = truth()
        hold(sess, 0.15, 0.0, 1.0)
        check("Mission Control's state follows while it drives: moving, a velocity of 0.15 m/s from the tracks", status().get("mode") == "moving"
              and abs(status()["velocity"]["vx"] - 0.15) < 0.02, (status().get("mode"), status().get("velocity")))
        hold(sess, 0.15, 0.0, 1.0)
        b = truth()
        went = b[1] - a[1]
        check("forward at half speed for 2 s: the truth moved north about 0.3 m (0.15 m/s) and not sideways, heading held",
              0.2 < went < 0.4 and abs(b[0] - a[0]) < 0.01 and abs(b[2] - a[2]) < 0.01, (a, b))
        hold(sess, 0.0, 1.0, 1.0)
        c = truth()
        turned = math.remainder(c[2] - b[2], math.tau)
        # not "about 1 rad": the adapter turns ±50 % tracks for its 1.5 rad/s, the world reads 1.5 rad/s as ±100 % (and slips 0.9), so 1 rad/s turns
        # the sim about 0.45 rad. Which is right is the brick's to say (D1, K16); this checks the direction and that it turns on the spot
        check("a turn in place to the left for 1 s at 1 rad/s: the heading grew counter-clockwise (0.3 to 1.2 rad, printed) and the robot stayed within 3 cm",
              0.3 < turned < 1.2 and math.dist(c[:2], b[:2]) < 0.03, (b, c, f"turned {turned:.2f} rad"))
        check("a client that is not the holder is refused with the holder named", call("POST", "/robots/nxt-1/lock", {"client": "phone"})[1]["error"]["holder"] == "sim-nxt")
        release(sess)
        check("releasing frees the robot and ends the recording: a finished run", wait_for(lambda: robot()["lock"]["holder"] is None and not status().get("recording"), 5), robot()["lock"])
        runs["drive"] = key
        check("and the robot stands still once released (nxt-web stopped the tracks)", stands_still())

    # --- the wall: the 15 cm obstacle stop, on a real distance -------------------------------------------------------------
    if wanted("wall"):
        print("\n--- hit a wall: the obstacle stop", flush=True)
        fresh_sim()
        sess = acquire("sim-nxt")
        wait_for(lambda: (status().get("recording") or {}).get("ours") is True, 5)
        key = recording_key()
        face = north_wall_face(START[0], START[1])
        r0 = status()["sensors"]["ultrasonic"]["range_m"]
        hold(sess, 0.3, 0.0, 12.0, until=lambda: status().get("flags", {}).get("obstacle_stop"))
        hit = wait_for(lambda: status().get("flags", {}).get("obstacle_stop"), 3)
        stopped = truth()
        gap = face - (stopped[1] + 0.10)         # the wall's face to the sensor, which sits 10 cm ahead of the centre
        check("full speed at the north wall: Mission Control shows the obstacle stop, and the range on its facts line is 15 cm or under",
              bool(hit) and status()["sensors"]["ultrasonic"]["range_m"] <= 0.15, (status().get("flags"), status().get("sensors")))
        check(f"judged by the truth against the scene file's wall (face at y={face:.2f}): the sensor stopped 10 to 15 cm from it, the robot did not touch it, and it came from about {r0:.2f} m away",
              0.10 <= gap <= 0.155 and stopped[1] < face - 0.1 and 0.7 < r0 < 1.0, (stopped, gap, r0))
        check("it raised one minor obstacle_stop alarm, which the robot's view carries", wait_for(lambda: len(alarms("obstacle_stop")) == 1, 5)
              and alarms("obstacle_stop")[0]["anomaly"]["severity"] == "minor" and robot()["alarms"]["worst"]["anomaly"]["anomaly"] == "obstacle_stop",
              (len(alarms("obstacle_stop")), robot()["alarms"]))
        hold(sess, 0.3, 0.0, 1.5)
        check("a held forward drive against the wall goes nowhere: the truth stays within 1 cm, and the stop is still set", math.dist(truth()[:2], stopped[:2]) < 0.01
              and status()["flags"]["obstacle_stop"] is True, (truth(), stopped))
        hold(sess, -0.15, 0.0, 1.5)
        away = truth()
        check("backing away works, and the stop clears with the motion command", away[1] < stopped[1] - 0.12 and not status()["flags"]["obstacle_stop"], (stopped, away, status()["flags"]))
        wall_stop_y = stopped[1]
        release(sess)
        wait_for(lambda: not status().get("recording"), 5)
        runs["wall"] = key

    # --- STOP: anyone, at once, no lease -----------------------------------------------------------------------------------------
    if wanted("stop"):
        print("\n--- STOP", flush=True)
        fresh_sim()
        sess = acquire("sim-nxt")
        wait_for(lambda: (status().get("recording") or {}).get("ours") is True, 5)
        key = recording_key()
        hold(sess, 0.15, 0.0, 1.0)
        moving = not stands_still(0.4)
        st, b = call("POST", "/robots/nxt-1/stop", {"client": "bystander"})
        halt = truth()
        refused = call("POST", "/robots/nxt-1/drive", {"session": sess, "vx": 0.15, "vyaw": 0})
        check("the robot was moving; STOP from a client that holds nothing is confirmed", moving and st == 200 and b["stop"]["confirmed"] is True, (moving, st, b))
        # "lease_ended" with nxt-web's reason when the drive beats Mission Control's next poll, "no_lease" when the poll has already told the client it lost the lease
        check("the holder's lease ended with it: its next drive is refused, and nothing moves",
              refused[0] == 409 and refused[1]["error"]["code"] in ("lease_ended", "no_lease")
              and (refused[1]["error"]["code"] == "no_lease" or "stopped_by bystander" in refused[1]["error"]["reason"]) and math.dist(truth()[:2], halt[:2]) < 0.05, refused)
        check("the tracks are idle, the truth stands still, and the lock shows free", wait_for(lambda: (nxt_status()["left"], nxt_status()["right"]) == (0, 0), 3)
              and stands_still() and wait_for(lambda: robot()["lock"]["holder"] is None, 5), (nxt_status().get("left"), robot()["lock"]))
        check("the session ended, so the recording did: a finished run", wait_for(lambda: not status().get("recording"), 5), status().get("recording"))
        runs["stop"] = key
        st, b = call("POST", "/stop", {"client": "bystander"})
        check("STOP ALL reaches it too", st == 200 and b["stop"]["all_confirmed"] is True, b)

    # --- takeover: the list is nxt-web's ------------------------------------------------------------------------------------------
    if wanted("takeover"):
        print("\n--- takeover", flush=True)
        fresh_sim()
        phone = acquire("phone")
        wait_for(lambda: (status().get("recording") or {}).get("ours") is True, 5)
        key = recording_key()
        hold(phone, 0.15, 0.0, 1.0)
        st, b = call("POST", "/robots/nxt-1/lock/takeover", {"client": "script"})
        check("a name that is not on the list is refused, and the phone's drive still works", st == 403 and b["error"]["code"] == "not_allowed"
              and hold(phone, 0.15, 0.0, 0.4) == 200, (st, b))
        st, b = call("POST", "/robots/nxt-1/lock/takeover", {"client": "operator-laptop"})
        at_takeover = truth()
        check("operator-laptop is on it: the robot is stopped and the laptop holds the lock", st == 200 and wait_for(lambda: robot()["lock"]["holder"] == "operator-laptop", 5)
              and stands_still(), (st, b))
        laptop = b["lock"]["session"]
        st, b = call("POST", "/robots/nxt-1/drive", {"session": phone, "vx": 0.15, "vyaw": 0})
        check("the phone's next drive is refused and the robot has not moved", st == 409 and math.dist(truth()[:2], at_takeover[:2]) < 0.01, (st, b))
        hold(laptop, 0.15, 0.0, 1.0)
        check("the laptop drives it: the truth moved north", truth()[1] > at_takeover[1] + 0.1, (at_takeover, truth()))
        check("the takeover was one session after another: the recording went on, the same run", recording_key() == key and key is not None, (recording_key(), key))
        release(laptop)
        check("released, the recording ended", wait_for(lambda: not status().get("recording"), 5))
        runs["takeover"] = key

    # --- the deadman: no command, no motion ---------------------------------------------------------------------------------------
    if wanted("deadman"):
        print("\n--- the deadman", flush=True)
        fresh_sim()
        sess = acquire("sim-nxt")
        wait_for(lambda: (status().get("recording") or {}).get("ours") is True, 5)
        key = recording_key()
        hold(sess, 0.15, 0.0, 1.0)
        # the client goes quiet while still holding the lock: nxt-web's watchdog stops the tracks 0.6 s after the last command
        check("with the client silent the deadman stop is held at nxt-web and shown on Mission Control's flags", wait_for(lambda: nxt_status()["stops"]["deadman_stop"], 5)
              and wait_for(lambda: status()["flags"]["deadman_stop"], 5), (nxt_status().get("stops"), status().get("flags")))
        check("the robot stands still (the truth) and the tracks are idle", stands_still(1.0) and (nxt_status()["left"], nxt_status()["right"]) == (0, 0), truth())
        check("it is a major alarm on the stream and on the robot's view", wait_for(lambda: alarms("deadman_stop"), 5) and alarms("deadman_stop")[0]["anomaly"]["severity"] == "major"
              and robot()["alarms"]["worst"]["anomaly"]["anomaly"] == "deadman_stop", robot()["alarms"])
        before = truth()
        check("the lease is still the client's, and the next command drives again: the truth moves", robot()["lock"]["holder"] == "sim-nxt"
              and hold(sess, 0.15, 0.0, 1.0) == 200 and truth()[1] > before[1] + 0.08, (before, truth()))
        release(sess)
        wait_for(lambda: not status().get("recording"), 5)
        runs["deadman"] = key

    # --- replay: the run the session left opens in the Observatory, with the truth -------------------------------------------------
    if wanted("replay"):
        print("\n--- replay: the recorded run in the Observatory's API", flush=True)
        if not runs:
            fresh_sim()
            sess = acquire("sim-nxt")
            wait_for(lambda: (status().get("recording") or {}).get("ours") is True, 5)
            runs["drive"] = recording_key()
            hold(sess, 0.15, 0.0, 2.0)
            release(sess)
            wait_for(lambda: not status().get("recording"), 5)
        key = runs.get("wall") or next(iter(runs.values()))
        obs = subprocess.Popen([str(OBSERVATORY), "--data", str(data), "serve", "--host", "127.0.0.1", "--port", str(OBS_PORT)], stdout=open(tmp / "observatory.log", "w"),
                               stderr=subprocess.STDOUT, start_new_session=True, env=dict(os.environ, OBSERVATORY_INDEX=str(tmp / "index.json")))
        own.append(obs)
        OBS = f"http://127.0.0.1:{OBS_PORT}/api/v1"
        up = wait_for(lambda: _try(lambda: raw("GET", OBS + "/health")[0] == 200), 30)
        check("the Observatory serves the data folder this test's nxt-web recorded into", bool(up), (tmp / "observatory.log").read_text()[-300:] if not up else None)
        listed = raw("GET", OBS + "/runs?robot=nxt")[1]
        names = [r["key"] if "key" in r else f"{r.get('robot')}/{r.get('scene')}/{r.get('name') or r.get('run')}" for r in (listed.get("runs") if isinstance(listed, dict) else listed)]
        check("every session left a run of the apartment, listed by the Observatory", bool(runs) and all(k in names for k in runs.values()), (names, runs))
        st, run = raw("GET", f"{OBS}/runs/{key}")
        check("the run opens: nxt, the apartment, ended (not live, not broken)", st == 200 and run.get("status") == "ended" and run.get("scene") == "apartment",
              (st, {k: run.get(k) for k in ("status", "scene", "scene_changed")}))
        st, fr = raw("GET", f"{OBS}/runs/{key}/frames")
        truths, beliefs = (fr.get("truth") or []), (fr.get("belief") or [])
        print("   frames:", sorted(fr), "ticks:", fr.get("ticks"), flush=True)
        check("it holds ticks, and the simulator's truth is on every one of them, beside the belief", st == 200 and len(truths) > 20 and len(truths) == len(beliefs)
              and all(truths) and all(beliefs), (st, len(truths), sum(1 for x in truths if x), len(beliefs)))
        ys = [x[1] for x in truths if x]
        if wall_stop_y is not None:
            check("the replayed truth ends where the live truth did at the wall: its farthest point north is the stop (within 2 cm)", abs(max(ys) - wall_stop_y) < 0.02, (max(ys), wall_stop_y))
        else:
            check("the replayed truth went north from the start pose", abs(truths[0][0]) < 0.05 and ys[-1] > ys[0] + 0.1, (truths[0], truths[-1]))
        st, state = raw("GET", f"{OBS}/runs/{key}/state?t={fr['t'][len(fr['t']) // 2]}")
        check("and the moment opens: the truth and the belief at a time in the middle of the run", st == 200 and state.get("truth") and state.get("belief_world"),
              (st, {k: state.get(k) for k in ("tick", "truth", "belief_world")} if isinstance(state, dict) else state))
finally:
    srv.shutdown()
    srv.server_close()
    mc.close()
    for p in own:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
    simhost.down(HOST)
    log = tmp / "sim-state" / "nxt-web.log"
    print("nxt-web log tail:\n" + (log.read_text()[-600:] if log.exists() else "(none)"), flush=True)

finish("sim_nxt")
