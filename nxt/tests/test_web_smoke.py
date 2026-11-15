"""Smoke test for nxt-web against the simulated brick (--fake), plus the no-brick checks when no
real brick can be reached. Run: make test-unit (or python nxt/tests/test_web_smoke.py from the repo).

It never drives a real robot: the real-mode checks are skipped whenever an NXT is on USB or any
/dev/rfcomm* exists (two incidents on 2026-11-14, see docs/rfc/RFC-0001-nxt-web-ui.md §6)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

NXT_DIR = Path(__file__).resolve().parents[1]
NXT_WEB = os.environ.get("NXT_WEB", str(NXT_DIR / ".venv" / "bin" / "nxt-web"))
RUNS = NXT_DIR / "runs"
runs_before = set(RUNS.glob("*")) if RUNS.exists() else set()


def call(base, path, body=None, raw=False):
    data = None if body is None else (body if raw else json.dumps(body).encode())
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                 headers={} if raw else {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            payload = r.read()
            ctype = r.headers.get("Content-Type", "")
            return r.status, (json.loads(payload) if ctype.startswith("application/json") else payload)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def start(port, *extra):
    p = subprocess.Popen([NXT_WEB, "--port", str(port), *extra], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print("server:", p.stdout.readline().strip())
    return p


failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:160]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp())
cfg = tmp / "config.json"
p = start(8761, "--fake", "--config", str(cfg))
base = "http://127.0.0.1:8761"
try:
    code, html = call(base, "/")
    check("GET / serves page", code == 200 and b"NXT Lab" in html, code)
    s = call(base, "/api/status")[1]
    check("fake status connected", s["connected"] and s["fake"] and s["battery_mv"] == 7800, s)
    check("deadman mode by default, robotd started on connect",
          s["deadman"]["mode"] == "deadman" and s["deadman"]["running"] and s["program"] == "robotd.rxe", s)

    # drive + watchdog
    call(base, "/api/drive", {"left": 50, "right": -50})
    s = call(base, "/api/status")[1]
    check("drive sets motors", (s["left"], s["right"]) == (50, -50), s)
    time.sleep(1.0)
    s = call(base, "/api/status")[1]
    check("watchdog stops after no keepalive", (s["left"], s["right"]) == (0, 0), s)
    call(base, "/api/drive", {"left": 500, "right": -500})
    s = call(base, "/api/status")[1]
    check("power clamped", (s["left"], s["right"]) == (100, -100), s)
    call(base, "/api/stop", {})

    # config
    code, c = call(base, "/api/config")
    check("config defaults", code == 200 and c["config"]["left"] == "C" and c["config"]["sensors"]["1"] == "none", c)
    code, r = call(base, "/api/config", {"left": "C", "right": "C"})
    check("config rejects duplicate motor ports", code == 409 and "different" in r["error"], r)
    code, r = call(base, "/api/config", {"sensors": {"1": "touch", "2": "none", "3": "color", "4": "ultrasonic"}, "sample_hz": 10})
    check("config save", code == 200 and r["config"]["sensors"]["4"] == "ultrasonic", r)
    check("config written to file", json.loads(cfg.read_text())["sensors"]["3"] == "color", cfg.read_text())

    # live samples
    time.sleep(0.6)
    live = call(base, "/api/live?since=0")[1]["samples"]
    last = live[-1] if live else {}
    check("live samples arrive", len(live) >= 3, len(live))
    check("live sample has tachos + configured sensors", set(last.get("tacho", {})) == {"A", "B", "C"} and set(last.get("sensors", {})) == {"1", "3", "4"}, last)
    check("color sensor has label", "label" in last.get("sensors", {}).get("3", {}), last)
    newer = call(base, f"/api/live?since={last['seq']}")[1]["samples"]
    check("live since= returns only newer", all(x["seq"] > last["seq"] for x in newer), [x["seq"] for x in newer])

    # tacho integrates while driving
    t_before = last["tacho"]["C"]
    for _ in range(5):
        call(base, "/api/drive", {"left": 50, "right": 50}); time.sleep(0.2)
    call(base, "/api/stop", {})
    time.sleep(0.3)
    t_after = call(base, "/api/live?since=0")[1]["samples"][-1]["tacho"]["C"]
    check("left tacho (C) advances while driving", t_after > t_before + 100, (t_before, t_after))

    # recording
    code, r = call(base, "/api/record/start", {})
    check("record start", code == 200 and r["recording"].startswith("run-"), r)
    run_name = r["recording"]
    time.sleep(1.2)
    s = call(base, "/api/status")[1]
    check("status shows recording rows", s["recording"] and s["recording"]["rows"] >= 5, s["recording"])
    call(base, "/api/record/stop", {})
    runs = call(base, "/api/runs")[1]["runs"]
    check("run listed", any(x["name"] == run_name for x in runs), runs)
    code, csv_bytes = call(base, f"/api/runs/download?name={run_name}")
    lines = csv_bytes.decode().splitlines()
    check("run CSV header", lines[0] == "t,power_left,power_right,tacho_A,tacho_B,tacho_C,s1_touch,s3_color,s3_color_name,s4_ultrasonic,program", lines[0])
    check("run CSV rows", len(lines) >= 6, len(lines))
    mcap_name = run_name.replace(".csv", ".mcap")
    check("run lists its MCAP file", any(x["name"] == run_name and x["mcap"] == mcap_name for x in runs), runs)
    code, mcap_bytes = call(base, f"/api/runs/download?name={mcap_name}")
    check("MCAP download", code == 200 and mcap_bytes[:8] == b"\x89MCAP0\r\n", mcap_bytes[:8])
    from mcap.reader import make_reader
    import io
    reader = make_reader(io.BytesIO(mcap_bytes))
    topics = {}
    for _schema, channel, message in reader.iter_messages():
        topics.setdefault(channel.topic, []).append(json.loads(message.data))
    states = topics.get("/nxt/state", [])
    check("MCAP has one state per CSV row", len(states) == len(lines) - 1, (len(states), len(lines) - 1))
    check("MCAP state carries tachos, sensors and robotd's answer",
          states and set(states[-1]["tacho"]) == {"A", "B", "C"} and "4" in states[-1]["sensors"]
          and "deadman" in states[-1], states[-1] if states else None)
    # "record start" is logged once the file is open; "record stop" after it is closed.
    check("MCAP has the command log while recording",
          [e["kind"] for e in topics.get("/nxt/events", [])] == ["record start"], topics.get("/nxt/events"))
    meta = {m.name: m.metadata for m in reader.iter_metadata()}
    check("MCAP metadata names the robot and drive mode",
          meta.get("nxt_lab.run", {}).get("robot") == "nxt" and meta["nxt_lab.run"].get("drive_mode") == "deadman", meta)
    code, r = call(base, "/api/runs/download?name=../config.json")
    check("run download refuses path traversal", code == 404, (code, r))

    # files + programs
    files = call(base, "/api/files")[1]["files"]
    check("fake files listed", {f["name"] for f in files} >= {"demo.rxe", "runlog.txt"}, files)
    code, r = call(base, "/api/files/upload?name=mine.rxe", b"\x01\x02\x03", raw=True)
    check("upload", code == 200, r)
    code, r = call(base, "/api/files/upload?name=this_name_is_far_too_long.rxe", b"x", raw=True)
    check("upload rejects bad NXT name", code == 409 and "valid NXT file name" in r["error"], r)
    code, data = call(base, "/api/files/download?name=mine.rxe")
    check("download returns uploaded bytes", data == b"\x01\x02\x03", data)
    code, v = call(base, "/api/files/view?name=runlog.txt")
    check("view text file", code == 200 and v["text"].startswith("t,light,dist"), v)
    code, r = call(base, "/api/program/start", {"name": "mine.rxe"})
    check("program start", code == 200, r)
    time.sleep(1.3)
    s = call(base, "/api/status")[1]
    check("status shows running program", s["program"] == "mine.rxe", s)
    code, r = call(base, "/api/drive", {"left": 30, "right": 30})
    check("drive refused while program runs", code == 409 and "running" in r["error"], r)
    time.sleep(0.5)
    last = call(base, "/api/live?since=0")[1]["samples"][-1]
    check("sensor reads paused while program runs", last["sensors"] == {} and last["program"] == "mine.rxe", last)
    code, r = call(base, "/api/program/stop", {})
    s = call(base, "/api/status")[1]
    check("program stop, then robotd starts again (deadman mode)", code == 200 and s["program"] == "robotd.rxe", s)

    # deadman: driving goes through robotd, which also reports the ultrasonic distance
    code, r = call(base, "/api/drive", {"left": 35, "right": 35})
    s = call(base, "/api/status")[1]
    st = s["deadman"]["state"] or {}
    check("drive goes through robotd", code == 200 and (st.get("left"), st.get("right")) == (35, 35), s["deadman"])
    call(base, "/api/stop", {})
    time.sleep(0.5)
    last = call(base, "/api/live?since=0")[1]["samples"][-1]
    check("sensors read under robotd; ultrasonic from robotd", "4" in last["sensors"] and "3" in last["sensors"]
          and isinstance(last["sensors"]["4"].get("value"), int), last["sensors"])
    # direct drive: robotd stops and is not restarted
    call(base, "/api/config", {"drive_mode": "direct"})
    call(base, "/api/program/stop", {})
    s = call(base, "/api/status")[1]
    check("direct mode: robotd not restarted", s["program"] is None and not s["deadman"]["running"], s)
    code, r = call(base, "/api/drive", {"left": 30, "right": 30})
    check("direct mode drives without robotd", code == 200, (code, r))
    call(base, "/api/stop", {})
    # deadman mode without robotd on the brick refuses to drive
    call(base, "/api/files/delete", {"name": "robotd.rxe"})
    call(base, "/api/config", {"drive_mode": "deadman"})
    code, r = call(base, "/api/drive", {"left": 30, "right": 30})
    check("deadman mode refuses to drive without robotd", code == 409 and "deadman program" in r["error"], r)
    ev = call(base, "/api/events?since=0")[1]["events"]
    check("missing robotd is logged", any(e["kind"] == "deadman start" and not e["ok"] for e in ev), ev[-3:])
    call(base, "/api/files/upload?name=robotd.rxe", b"\x00" * 10, raw=True)
    call(base, "/api/program/start", {"name": "robotd.rxe"})
    code, r = call(base, "/api/drive", {"left": 30, "right": 30})
    check("robotd started from Programs: drive works again", code == 200, (code, r))
    call(base, "/api/stop", {})
    code, r = call(base, "/api/files/delete", {"name": "mine.rxe"})
    files = call(base, "/api/files")[1]["files"]
    check("delete", code == 200 and "mine.rxe" not in {f["name"] for f in files}, files)
    code, r = call(base, "/api/program/start", {"name": "nothere.rxe"})
    check("start missing program -> 404", code == 404, (code, r))
    # status link, diagnostics, link test, command log
    s = call(base, "/api/status")[1]
    check("status shows the link", s.get("link") == "fake" and "link_ms" in s, s)
    code, d = call(base, "/api/diagnostics")
    check("diagnostics", code == 200 and d["link"] == "fake" and d["firmware"] and "bluetooth" in d["host"]
          and d["calls"]["n"] > 0 and d["samples_per_s"]["configured"] == 10, json.dumps(d)[:200])
    code, r = call(base, "/api/linktest", {})
    check("link test", code == 200 and r["linktest"]["n"] == 20, r)
    code, r = call(base, "/api/connect", {"link": "bogus"})
    check("connect refuses an unknown link", code == 409, (code, r))
    code, r = call(base, "/api/fire", {})
    check("fire refused while the shooter is switched off (default)", code == 409 and "switched off" in r["error"], r)
    call(base, "/api/config", {"shooter_enabled": True})
    code, r = call(base, "/api/fire", {})
    check("fire works once the shooter is enabled", code == 200, (code, r))
    call(base, "/api/config", {"shooter_enabled": False})
    code, r = call(base, "/api/live?since=abc")
    check("bad since= is a 400, not a crash", code == 400, (code, r))
    code, r = call(base, "/api/events?since=-1")
    check("negative since= is a 400", code == 400, (code, r))
    for _ in range(3):
        call(base, "/api/drive", {"left": 20, "right": 20}); time.sleep(0.2)
    call(base, "/api/stop", {})
    time.sleep(1.2)
    ev = call(base, "/api/events?since=0")[1]["events"]
    kinds = [e["kind"] for e in ev]
    drives = [e for e in ev if e["kind"] == "drive" and e.get("left") == 20]
    check("log: connect, upload, program, fire, config are logged",
          {"connect", "files upload", "program start", "program stop", "fire", "config", "linktest"} <= set(kinds), sorted(set(kinds)))
    check("log: a held drive is logged once, not per keepalive", len(drives) == 1, len(drives))
    check("log: watchdog stop is logged", "watchdog stop" in kinds, kinds[-8:])
    check("log: failed commands are logged as not ok", any(not e["ok"] for e in ev), [e for e in ev if not e["ok"]][:2])
    soc = [e for e in ev if e["kind"] == "stop on connect"]
    check("log: stop on connect is logged", len(soc) == 1 and soc[0]["were_running"] == [], soc)
    newer = call(base, f"/api/events?since={ev[-1]['seq']}")[1]["events"]
    check("log: since= returns only newer", all(e["seq"] > ev[-1]["seq"] for e in newer), len(newer))
    code, raw = call(base, "/api/events/download")
    check("log: download is JSONL", code == 200 and raw.strip().splitlines()[-1].startswith(b"{"), raw[-80:])
    call(base, "/api/drive", {"left": 40, "right": 40})
finally:
    p.terminate()
    rest = p.communicate(timeout=10)[0]
    check("SIGTERM runs the stop-the-motors path", "stopped: motors idled" in rest, rest.strip()[-200:])

# The "no brick" checks drive a real robot if one is plugged in (2026-11-14: they did, and its
# tracks ran). Only run them when no NXT is on USB, and never send a drive with a nonzero power.
nxt_on_usb = any(p_.read_text().strip() == "0694" for p_ in Path("/sys/bus/usb/devices").glob("*/idVendor"))
# 2026-11-14 again: with USB unplugged, /dev/rfcomm0 still reached the real brick over Bluetooth and
# hung the live UI server sharing that link. Any possible link to a real brick means: skip.
rfcomm_ports = sorted(str(p_) for p_ in Path("/dev").glob("rfcomm*"))
if nxt_on_usb or rfcomm_ports:
    print(f"SKIP real-mode no-brick checks: a real NXT may be reachable (usb={nxt_on_usb}, bluetooth={rfcomm_ports})")
else:
    p = start(8762, "--config", str(cfg))
    base = "http://127.0.0.1:8762"
    try:
        s = call(base, "/api/status")[1]
        check("real mode, no brick: not connected with error", not s["connected"] and "no brick" in (s["error"] or ""), s)
        code, r = call(base, "/api/drive", {"left": 0, "right": 0})
        check("drive refused when not connected", code == 409, (code, r))
        code, r = call(base, "/api/files")
        check("files refused when not connected", code == 409, (code, r))
        code, r = call(base, "/api/connect", {})
        s = call(base, "/api/status")[1]
        # A failed connect answers 409 with the error (since 95aaf9f; the page shows it), and the
        # server keeps answering. This check expected 200 and never ran on the workstation, which
        # skips it while a brick may be reachable; CI ran it first (2026-11-15).
        check("connect retry reports error, server stays up",
              code == 409 and "no brick" in (r.get("error") or "") and not s["connected"], (code, r, s))
    finally:
        p.terminate(); p.wait(5)

# remove only the runs this test created
for f in (set(RUNS.glob("*")) if RUNS.exists() else set()) - runs_before:
    f.unlink()
if RUNS.exists() and not any(RUNS.iterdir()) and not runs_before:
    RUNS.rmdir()
shutil.rmtree(tmp)

print("SMOKE", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
