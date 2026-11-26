"""The NXT adapter (RFC-0014 step 4): Mission Control against nxt-web --fake, the real process with its simulated brick.
Never a real brick: nxt-web runs with --fake, in a scratch data folder, on a free loopback port, and this test never names a
device (no /dev/rfcomm*, no USB). The lock is nxt-web's, so the checks read it from both sides.
Run: make test-control (needs apps/nxt-web/.venv: make nxt-sync)"""

import json
import os
import signal
import socket
import subprocess
import sys
import shutil
import atexit
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import check, finish

from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig

ROOT = Path(__file__).resolve().parents[3]
NXT_WEB = os.environ.get("NXT_WEB", str(ROOT / "apps" / "nxt-web" / ".venv" / "bin" / "nxt-web"))
if not Path(NXT_WEB).exists():
    print(f"FAIL test_nxt_adapter: {NXT_WEB} is missing (make nxt-sync)")
    sys.exit(1)

tmp = Path(tempfile.mkdtemp(prefix="mc-nxt-"))
atexit.register(shutil.rmtree, tmp, True)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
NXT = f"http://127.0.0.1:{PORT}"
(tmp / "takeover.txt").write_text("operator-laptop  # may take the lock back\n")
proc = subprocess.Popen([NXT_WEB, "--fake", "--host", "127.0.0.1", "--port", str(PORT), "--config", str(tmp / "config.json"),
                         "--takeover-names", str(tmp / "takeover.txt")],
                        env=dict(os.environ, NXT_LAB_DATA=str(tmp), MINIVIEW_DATA=str(tmp / "miniview")), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def raw(method, url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def nxt(method, path, body=None):
    return raw(method, NXT + path, body)


def wait(cond, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _try(fn):
    try:
        return fn()
    except OSError:
        return False


check("nxt-web --fake is up", wait(lambda: _try(lambda: nxt("GET", "/api/status")[1].get("connected")), 20) and nxt("GET", "/api/status")[1]["fake"] is True)

FILE = json.loads((ROOT / "apps" / "mission-control" / "robots.nxt" / "nxt-1.json").read_text())
FILE["adapter"]["url"] = NXT
FILE["adapter"]["allow_real_runs"] = True        # a file that holds the NXT itself is a real robot: a hand drive asks for the key (nxt-web here is --fake)
mc = MissionControl([RobotConfig(FILE)], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()


def call(method, path, body=None):
    return raw(method, BASE + path, body)


def robot():
    return call("GET", "/robots/nxt-1")[1]["robot"]


# --- the alarms, on invented statuses and a clock of our own (the rules; the end to end follows below and in test_nxt_page) ---------------------
from mission_control.nxt import NxtWatcher

w = NxtWatcher()
ok = {"battery_pct": 80, "flags": {"deadman_stop": False, "obstacle_stop": False}, "sensors": {"ultrasonic": {"range_m": 0.3}}}
names = lambda out: [(a["anomaly"], a["severity"]) for a in out]
check("a healthy NXT raises nothing", w.update(ok, True, 100.0) == [])
check("an obstacle stop raises one minor alarm, with the range", names(w.update({**ok, "flags": {"deadman_stop": False, "obstacle_stop": True}}, True, 101.0)) == [("obstacle_stop", "minor")])
check("held, it raises no second", w.update({**ok, "flags": {"deadman_stop": False, "obstacle_stop": True}}, True, 102.0) == [])
w.update(ok, True, 103.0)
check("flapping inside the cooldown (a held drive re-meets the wall) raises no second", w.update({**ok, "flags": {"deadman_stop": False, "obstacle_stop": True}}, True, 104.0) == [])
w.update(ok, True, 150.0)
again = w.update({**ok, "flags": {"deadman_stop": False, "obstacle_stop": True}}, True, 160.0)
check("a new stop after the cooldown raises one again", names(again) == [("obstacle_stop", "minor")] and again[0]["values"]["range_m"] == 0.3, again)
check("a deadman stop is major", names(w.update({**ok, "flags": {"deadman_stop": True, "obstacle_stop": False}}, True, 161.0)) == [("deadman_stop", "major")])
low = {**ok, "battery_pct": 12, "battery_mv": 6290}
check("a low battery is major, once", names(w.update(low, True, 200.0)) == [("low_battery", "major")] and w.update(low, True, 210.0) == [])
check("and again every 30 s while it stays low, so the fit verdict keeps it (a major alarm counts for 60 s)", names(w.update(low, True, 231.0)) == [("low_battery", "major")])
check("recovered it says nothing; a dip again inside the 30 s (a sag under load) raises no second, one after them does",
      w.update(ok, True, 232.0) == [] and w.update(low, True, 233.0) == [] and names(w.update(low, True, 262.0)) == [("low_battery", "major")])
w.update({**ok, "battery_pct": 22}, True, 263.0)
check("hysteresis: 22 % is still low once low (the threshold is 20, it clears above 25)", names(w.update({**ok, "battery_pct": 22}, True, 300.0)) == [("low_battery", "major")])
check("an unknown battery raises nothing", w.update({**ok, "battery_pct": None}, True, 400.0) == [])
bw = NxtWatcher()
check("the battery the robot view carries: no reading, no state", bw.battery_rule.view(None) is None and bw.battery_rule.view({"battery_pct": None}) is None)
bw.update({**ok, "battery_pct": 80}, True, 1.0)
check("healthy: not low, with the rule's two numbers beside it (the page holds no threshold)", bw.battery_rule.view({"battery_pct": 80}) == {"pct": 80, "low": False, "low_pct": 20, "clear_pct": 25}, bw.battery_rule.view({"battery_pct": 80}))
bw.update({**ok, "battery_pct": 19}, True, 2.0)
check("under 20 % it is low", bw.battery_rule.view({"battery_pct": 19}) == {"pct": 19, "low": True, "low_pct": 20, "clear_pct": 25})
bw.update({**ok, "battery_pct": 24}, True, 3.0)
check("hysteresis: 24 % stays low (the watcher's own state, not a threshold re-read)", bw.battery_rule.view({"battery_pct": 24})["low"] is True)
bw.update({**ok, "battery_pct": 26}, True, 4.0)
check("over 25 % it clears", bw.battery_rule.view({"battery_pct": 26})["low"] is False)
check("no answer while it was never online raises no link alarm", NxtWatcher().update(None, False, 1.0) == [])
w2 = NxtWatcher()
w2.update(ok, True, 1.0)
check("going offline after being online raises link_lost, major, once", names(w2.update(None, False, 2.0)) == [("link_lost", "major")] and w2.update(None, False, 3.0) == [])
w2.update(ok, True, 4.0)
check("a link lost again after the cooldown raises it again", names(w2.update(None, False, 40.0)) == [("link_lost", "major")])
check("every alarm has the record's fields: source, module, summary, t", all({"anomaly", "severity", "source", "module", "summary", "t", "values"} <= set(a) for a in again), again)

try:
    check("the NXT is online through nxt-web, free", wait(lambda: robot()["online"]) and robot()["lock"]["holder"] is None, robot())
    r = robot()
    check("its status is the brick's: idle tracks, the battery, the link, and no pose", wait(lambda: (robot()["status"] or {}).get("mode") == "idle")
          and robot()["status"]["tracks"] == {"left": 0, "right": 0} and robot()["status"]["battery_mv"] == 7800 and robot()["status"]["link"] == "fake"
          and "pose" not in robot()["status"], robot()["status"])
    # D5: what the page's fit verdict reads. nxt-web's `program` (robotd.rxe, running) was a truthy flag, so an online idle NXT was "Not fit"
    check("an idle robot sets no status flag: the running program is not a flag", all(v is False for v in robot()["status"]["flags"].values()) and robot()["status"]["flags"], robot()["status"]["flags"])
    check("the running program is named beside the flags", robot()["status"]["program"] == "robotd.rxe", robot()["status"])
    check("the battery is a percent: 7800 mV is 75 % of the assumed 6.0-8.4 V", robot()["status"]["battery_pct"] == 75, robot()["status"]["battery_pct"])
    check("GET /robots/{id} carries the server's battery rule: the state, and the two numbers of its hysteresis", robot()["battery"] == {"pct": 75, "low": False, "low_pct": 20, "clear_pct": 25}, robot().get("battery"))
    check("capabilities.sensors names the ultrasonic (a range, port 4) and the colour sensor (port 3)",
          [(s["id"], s["kind"], s["port"]) for s in r["capabilities"]["sensors"]] == [("ultrasonic", "range", "4"), ("colour", "colour", "3")], r["capabilities"]["sensors"])
    check("the state carries the ultrasonic in metres and the colour's name, under the ids capabilities.sensors gives",
          wait(lambda: 0.1 < ((robot()["status"].get("sensors") or {}).get("ultrasonic") or {}).get("range_m", 0) < 1.1
               and isinstance(((robot()["status"].get("sensors") or {}).get("colour") or {}).get("label"), str)), robot()["status"].get("sensors"))
    check("no obstacle and no deadman stop yet", robot()["status"]["flags"] == {"deadman_stop": False, "obstacle_stop": False}, robot()["status"]["flags"])
    check("the robot file says what it is: no navigator, no map, drive only", "physicalParameters" not in r["factsheet"] and r["factsheet"]["typeSpecification"]["mobileRobotKinematics"] == "DIFFERENTIAL" and "navigator" not in r["capabilities"])

    check("must fail: the lock says the gate protocol it speaks, as the duck's gate does (nxt-web's own lock has none)",
          robot()["lock"].get("protocol") == 1, robot()["lock"])

    # the lock is nxt-web's
    st, b = call("POST", "/robots/nxt-1/lock", {"client": "page"})
    sess = b["lock"]["session"]
    check("acquire takes nxt-web's lock for the client", st == 200 and nxt("GET", "/api/lock")[1]["holder"] == "page", (st, b))
    check("and Mission Control shows who holds it", wait(lambda: robot()["lock"]["holder"] == "page"), robot()["lock"])
    # D6: a drive session leaves a run
    rec = lambda: nxt("GET", "/api/status")[1]["recording"]
    check("the session started nxt-web's recorder: a recording, and the robot's state names its run and says it is ours",
          rec() is not None and wait(lambda: (robot()["status"].get("recording") or {}).get("ours") is True)
          and robot()["status"]["recording"]["run"] == rec()["miniview"]["key"] and robot()["status"]["recording_error"] is None, (rec(), robot()["status"].get("recording")))
    st, b = call("POST", "/robots/nxt-1/lock", {"client": "phone"})
    check("a second client is refused, naming the holder", st == 409 and b["error"]["code"] == "held" and b["error"]["holder"] == "page", b)
    st, b = nxt("POST", "/api/drive", {"left": 50, "right": 50})
    check("nxt-web refuses a drive with no session while Mission Control holds it", st == 409 and b["lock"] == "held", b)

    # drive
    st, b = call("POST", "/robots/nxt-1/drive", {"session": sess, "vx": 0.15, "vyaw": 0.0})
    status = nxt("GET", "/api/status")[1]
    check("drive: a half-speed forward is both tracks at 50", st == 200 and (status["left"], status["right"]) == (50, 50), (st, b, status["left"], status["right"]))
    check("the state follows: moving, velocity from the tracks", wait(lambda: robot()["status"]["mode"] == "moving" and abs(robot()["status"]["velocity"]["vx"] - 0.15) < 0.01), robot()["status"])
    call("POST", "/robots/nxt-1/drive", {"session": sess, "vx": 0.0, "vyaw": 1.5})
    status = nxt("GET", "/api/status")[1]
    check("a full counter-clockwise turn is the right track 50 ahead and the left 50 back", (status["left"], status["right"]) == (-50, 50), (status["left"], status["right"]))
    call("POST", "/robots/nxt-1/drive", {"session": sess, "vx": 9.0, "vyaw": 0.0})
    check("more than the robot's limit is clamped to a full command", (nxt("GET", "/api/status")[1]["left"], nxt("GET", "/api/status")[1]["right"]) == (100, 100))
    st, b = call("POST", "/robots/nxt-1/lock/renew", {"session": sess})
    check("renew", st == 200 and b["lock"]["expires_in_s"] > 0, b)
    st, b = call("POST", "/robots/nxt-1/drive", {"session": "made-up", "vx": 0.1})
    check("a session that is not Mission Control's is refused", st == 409 and b["error"]["code"] == "no_lease", b)

    # the brick stops itself when the drives stop (its deadman 0.5 s, nxt-web's watchdog 0.6 s, whose stop clears the brick's own flag):
    # nxt-web keeps the reason until the next motion command, so a poll at 2 Hz sees it, and Mission Control raises it as an alarm
    check("with no drive for a moment the deadman stop is held at nxt-web", wait(lambda: nxt("GET", "/api/status")[1]["stops"]["deadman_stop"], 5), nxt("GET", "/api/status")[1].get("stops"))
    check("Mission Control shows it as a status flag", wait(lambda: robot()["status"]["flags"]["deadman_stop"], 5), robot()["status"]["flags"])
    def alarms(name):
        return [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "anomaly" and e["anomaly"]["anomaly"] == name]
    check("and as a major alarm on the stream and on the robot's view, which the page's fit verdict reads",
          wait(lambda: alarms("deadman_stop")) and alarms("deadman_stop")[0]["anomaly"]["severity"] == "major"
          and robot()["alarms"]["worst"]["anomaly"]["anomaly"] == "deadman_stop", robot()["alarms"])
    call("POST", "/robots/nxt-1/drive", {"session": sess, "vx": 0.15, "vyaw": 0.0})
    check("a motion command clears the held reason at nxt-web (the watchdog sets it again 0.6 s after the last one)", nxt("GET", "/api/status")[1]["stops"]["deadman_stop"] is False)

    # STOP: anyone, no lease, ends the lease and stops the tracks
    st, b = call("POST", "/robots/nxt-1/stop", {"client": "bystander"})
    check("STOP from anyone is confirmed and stops the tracks", st == 200 and b["stop"]["confirmed"] is True
          and (nxt("GET", "/api/status")[1]["left"], nxt("GET", "/api/status")[1]["right"]) == (0, 0), b)
    check("STOP ended the lease at nxt-web", nxt("GET", "/api/lock")[1]["holder"] is None)
    st, b = call("POST", "/robots/nxt-1/drive", {"session": sess, "vx": 0.1})
    check("the holder's next drive is refused with the reason", st == 409 and b["error"]["code"] == "lease_ended" and "stopped_by bystander" in b["error"]["reason"], b)
    check("nothing moved", (nxt("GET", "/api/status")[1]["left"], nxt("GET", "/api/status")[1]["right"]) == (0, 0))
    check("and the lock shows free", wait(lambda: robot()["lock"]["holder"] is None))
    check("the lease ended, so the recording ended: a finished run, not a live one", wait(lambda: rec() is None)
          and list((tmp / "miniview" / "runs" / "nxt" / "unmapped").glob("run-*/run.mcap")) != [], rec())
    first_run = sorted(p.name for p in (tmp / "miniview" / "runs" / "nxt" / "unmapped").iterdir())

    # a lease that ends at nxt-web (its own page STOP) is noticed by Mission Control
    st, b = call("POST", "/robots/nxt-1/lock", {"client": "page"})
    sess = b["lock"]["session"]
    call("POST", "/robots/nxt-1/drive", {"session": sess, "vx": 0.1})
    nxt("POST", "/api/stop", {"client": "nxt-page"})
    check("a STOP at nxt-web's own page is seen: the session ends, with its reason", wait(lambda: call("POST", "/robots/nxt-1/drive", {"session": sess, "vx": 0.1})[1].get("error", {}).get("reason", "").startswith("stopped_by nxt-page")), None)
    check("and no track moves after it", (nxt("GET", "/api/status")[1]["left"], nxt("GET", "/api/status")[1]["right"]) == (0, 0))

    # takeover is nxt-web's list, not the robot file's
    call("POST", "/robots/nxt-1/lock", {"client": "phone"})
    st, b = call("POST", "/robots/nxt-1/lock/takeover", {"client": "script"})
    check("takeover by a name that is not on nxt-web's list is refused", st == 403 and b["error"]["code"] == "not_allowed", b)
    st, b = call("POST", "/robots/nxt-1/lock/takeover", {"client": "operator-laptop"})
    check("by one that is: the robot is stopped and the laptop holds it", st == 200 and nxt("GET", "/api/lock")[1]["holder"] == "operator-laptop", b)
    check("a takeover is one session after another: the recording goes on (the lease the old one lost does not end it)", rec() is not None and wait(lambda: robot()["lock"]["holder"] == "operator-laptop")
          and rec() is not None, rec())
    call("DELETE", "/robots/nxt-1/lock", {"session": b["lock"]["session"]})
    check("release frees it", nxt("GET", "/api/lock")[1]["holder"] is None and wait(lambda: robot()["lock"]["holder"] is None))
    check("and ends the recording; every session so far left a run of its own, none live", wait(lambda: rec() is None)
          and len(list((tmp / "miniview" / "runs" / "nxt" / "unmapped").iterdir())) > len(first_run)
          and not list((tmp / "miniview" / "runs" / "nxt" / "unmapped").glob("*/run.live.mcap")), rec())
    # a recording someone started on nxt-web's page is theirs: a session beside it neither starts a second nor stops it
    nxt("POST", "/api/record/start", {})
    st, b2 = call("POST", "/robots/nxt-1/lock", {"client": "page"})
    check("with Record already pressed a session does not own the recording",
          rec() is not None and wait(lambda: (robot()["status"].get("recording") or {}).get("ours") is False), robot()["status"].get("recording"))
    call("DELETE", "/robots/nxt-1/lock", {"session": b2["lock"]["session"]})
    time.sleep(1.0)
    check("and releasing leaves it running", rec() is not None, rec())
    nxt("POST", "/api/record/stop", {})
    st, b = call("DELETE", "/robots/nxt-1/lock", {"session": b["lock"]["session"]})
    check("releasing twice is refused", st == 409, b)

    # goals: none
    st, b = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 1.0, "y": 0.0}}, "robots": ["nxt-1"]})
    check("a goal is refused for lack of a navigator, as a run", st == 201 and b["run"]["state"] == "refused" and "no navigator" in b["run"]["reason"], b)

    # STOP ALL, and the events
    st, b = call("POST", "/stop", {"client": "page"})
    check("STOP ALL reaches it", st == 200 and b["stop"]["all_confirmed"] is True, b)

    def holders():
        return [e["holder"] for e in mc.bus.since(0, 100000)[0] if e["kind"] == "lock" and e.get("event") == "holder"]
    check("the holder changes are on the event stream, as the polls see them", wait(lambda: holders()[:1] == ["page"] and holders()[-1:] == [None]), holders())

    # nxt-web goes away: offline, and STOP is accepted and cannot be confirmed
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=20)
    check("with nxt-web gone the robot goes offline", wait(lambda: not robot()["online"], 20))
    st, b = call("POST", "/robots/nxt-1/stop", {"client": "page"})
    check("and STOP is accepted but not confirmed", st == 200 and b["stop"]["confirmed"] is False, b)
    st, b = call("POST", "/robots/nxt-1/drive", {"session": "x", "vx": 0.1})
    check("a drive to it is refused offline, nothing queued", st == 503 and b["error"]["code"] == "robot_offline", b)
finally:
    srv.shutdown()
    srv.server_close()
    mc.close()
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
finish("test_nxt_adapter")
