"""HARDWARE CHECK — moves the robot: starts both tracks at power 25, then disconnects, the way a
crashed server or a lost link leaves them. Lift the robot. Stop any running nxt-web first.

Then starts nxt-web and checks it stopped them on connect (RFC-0001 §3.3, review 2 MAJ-3):
the command log shows "stop on connect" with the running ports, and every motor reads idle.
Pass = motors idle and the log names them."""

import json
import subprocess
import time
import urllib.request
from pathlib import Path

import nxt.error
import nxt.locator
import nxt.motor

PORT = 8764
NXT_WEB = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "nxt-web"

with nxt.locator.find(backends=["usb", "devfile"]) as brick:
    try:
        brick.stop_program()  # a running robotd-lite would stop the tracks itself, hiding the check
    except nxt.error.NoActiveProgramError:
        pass
    for port in (nxt.motor.Port.B, nxt.motor.Port.C):
        brick.get_motor(port).run(25)
    print("tracks started at 25 and the connection dropped")

p = subprocess.Popen([str(NXT_WEB), "--port", str(PORT)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    print("server:", p.stdout.readline().strip())
    time.sleep(1.0)
    events = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/events?since=0", timeout=10).read())["events"]
    stop = [e for e in events if e["kind"] == "stop on connect"]
    print("log:", stop)
finally:
    p.terminate()
    p.communicate(timeout=15)

with nxt.locator.find(backends=["usb", "devfile"]) as brick:
    powers = {port.name: brick.get_output_state(port)[1] for port in nxt.motor.Port}
print("motor powers after:", powers)
ok = all(v == 0 for v in powers.values()) and stop and sorted(stop[0]["were_running"]) == ["B", "C"]
print("STOP-ON-CONNECT", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
