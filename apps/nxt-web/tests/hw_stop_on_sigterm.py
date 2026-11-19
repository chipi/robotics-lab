"""HARDWARE CHECK — moves the robot: drives both tracks at power 30 for about 0.2 s. Lift the robot.
Stop any running nxt-web first (one connection to the brick at a time).

Starts nxt-web, drives, SIGTERMs it within 0.2 s (before the 0.6 s watchdog could act), then reads
every motor. Pass = all motors idle. Guards RFC-0001 §3.3 (stopping the server stops the motors)."""

import json
import subprocess
import time
import urllib.request
from pathlib import Path

import nxt.locator
import nxt.motor

PORT = 8763
NXT_WEB = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "nxt-web"
p = subprocess.Popen([str(NXT_WEB), "--port", str(PORT)],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
print("server:", p.stdout.readline().strip())
try:
    def post(path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=5).read().decode()

    # no lease, no motion (RFC-0017): the control lock first, then the drive with its session
    session = json.loads(post("/api/lock", {"action": "acquire", "client": "hw-stop-on-sigterm"}))["session"]
    print("drive:", post("/api/drive", {"left": 30, "right": 30, "session": session}))
    time.sleep(0.2)
finally:
    p.terminate()
    out = p.communicate(timeout=15)[0]
print("server exit:", p.returncode, "| said 'stopped: motors idled':", "stopped: motors idled" in out)

with nxt.locator.find(backends=["usb", "devfile"]) as brick:
    states = {port.name: brick.get_output_state(port) for port in nxt.motor.Port}
for name, s in states.items():
    print(f"{name}: power {s[1]} run_state {s[5]}")
ok = all(s[1] == 0 for s in states.values())
print("SIGTERM-REAL", "PASS" if ok else "FAIL")
