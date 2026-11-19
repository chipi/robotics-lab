"""The NXT adapter (RFC-0014 step 4): Mission Control against nxt-web --fake, the real process with its simulated brick.
Never a real brick: nxt-web runs with --fake, in a scratch data folder, on a free loopback port, and this test never names a
device (no /dev/rfcomm*, no USB). The lock is nxt-web's, so the checks read it from both sides.
Run: make test-control (needs nxt/.venv: make nxt-sync)"""

import json
import os
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

from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig

ROOT = Path(__file__).resolve().parents[3]
NXT_WEB = os.environ.get("NXT_WEB", str(ROOT / "apps" / "nxt-web" / ".venv" / "bin" / "nxt-web"))
if not Path(NXT_WEB).exists():
    print(f"FAIL test_nxt_adapter: {NXT_WEB} is missing (make nxt-sync)")
    sys.exit(1)

tmp = Path(tempfile.mkdtemp(prefix="mc-nxt-"))
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
mc = MissionControl([RobotConfig(FILE)], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()


def call(method, path, body=None):
    return raw(method, BASE + path, body)


def robot():
    return call("GET", "/robots/nxt-1")[1]["robot"]


try:
    check("the NXT is online through nxt-web, free", wait(lambda: robot()["online"]) and robot()["lock"]["holder"] is None, robot())
    r = robot()
    check("its status is the brick's: idle tracks, the battery, the link, and no pose", wait(lambda: (robot()["status"] or {}).get("mode") == "idle")
          and robot()["status"]["tracks"] == {"left": 0, "right": 0} and robot()["status"]["battery_mv"] == 7800 and robot()["status"]["link"] == "fake"
          and "pose" not in robot()["status"], robot()["status"])
    check("the robot file says what it is: no navigator, no map, drive only", "physicalParameters" not in r["factsheet"] and r["factsheet"]["typeSpecification"]["mobileRobotKinematics"] == "DIFFERENTIAL" and "navigator" not in r["capabilities"])

    # the lock is nxt-web's
    st, b = call("POST", "/robots/nxt-1/lock", {"client": "page"})
    sess = b["lock"]["session"]
    check("acquire takes nxt-web's lock for the client", st == 200 and nxt("GET", "/api/lock")[1]["holder"] == "page", (st, b))
    check("and Mission Control shows who holds it", wait(lambda: robot()["lock"]["holder"] == "page"), robot()["lock"])
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

    # STOP: anyone, no lease, ends the lease and stops the tracks
    st, b = call("POST", "/robots/nxt-1/stop", {"client": "bystander"})
    check("STOP from anyone is confirmed and stops the tracks", st == 200 and b["stop"]["confirmed"] is True
          and (nxt("GET", "/api/status")[1]["left"], nxt("GET", "/api/status")[1]["right"]) == (0, 0), b)
    check("STOP ended the lease at nxt-web", nxt("GET", "/api/lock")[1]["holder"] is None)
    st, b = call("POST", "/robots/nxt-1/drive", {"session": sess, "vx": 0.1})
    check("the holder's next drive is refused with the reason", st == 409 and b["error"]["code"] == "lease_ended" and "stopped_by bystander" in b["error"]["reason"], b)
    check("nothing moved", (nxt("GET", "/api/status")[1]["left"], nxt("GET", "/api/status")[1]["right"]) == (0, 0))
    check("and the lock shows free", wait(lambda: robot()["lock"]["holder"] is None))

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
    call("DELETE", "/robots/nxt-1/lock", {"session": b["lock"]["session"]})
    check("release frees it", nxt("GET", "/api/lock")[1]["holder"] is None and wait(lambda: robot()["lock"]["holder"] is None))
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
