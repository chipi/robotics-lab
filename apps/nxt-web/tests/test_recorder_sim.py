"""A recording made in the simulator (--sim --world) is a run of that scene with the simulator's truth beside the belief (D6,
ADR-0013): the run's scene is the world's, it records which scene file it was in (id, checksum, sha256), every pose tick holds the
truth read with it, the map <- world epoch puts the odometry on the start pose, and the sim's turn slip shows as the difference
between the two. It never opens a real brick: nxt-web runs with --sim on a free port, data in a scratch folder.
Run: make test-unit (or python apps/nxt-web/tests/test_recorder_sim.py)."""

import atexit
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from runfile import keys, mcapio, scenefile
from runfile.se2 import compose
from nxt_lab import config as cfgmod
from nxt_lab.config import Config

REPO = Path(__file__).resolve().parents[3]
NXT_DIR = Path(__file__).resolve().parents[1]
NXT_WEB = os.environ.get("NXT_WEB", str(NXT_DIR / ".venv" / "bin" / "nxt-web"))
APARTMENT = REPO / "scenes" / "apartment" / "scene.json"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:240]}]" if detail else ""))
    if not cond:
        failures.append(name)


def call(base, path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def drive_for(base, session, seconds, left, right):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        call(base, "/api/drive", {"left": left, "right": right, "session": session})
        time.sleep(0.2)


tmp = Path(tempfile.mkdtemp(prefix="nxt-sim-rec-"))
atexit.register(shutil.rmtree, tmp, True)
mv, port = tmp / "mv", 8774
cfgmod.save(Config(sample_hz=10.0), tmp / "config.json")        # no wheel geometry: the sim's own is used
env = dict(os.environ, NXT_LAB_DATA=str(tmp), OBSERVATORY_DATA=str(mv))
proc = subprocess.Popen([NXT_WEB, "--sim", "--world", str(APARTMENT), "--start", "0", "2", "90", "--port", str(port), "--config", str(tmp / "config.json")],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
try:
    proc.stdout.readline()
    base = f"http://127.0.0.1:{port}"
    code, r = call(base, "/api/record/start", {})
    name = r["recording"][:-4]
    key = f"nxt/apartment/{name}"
    check("record start says it started the recording, and the status names a run of the apartment",
          code == 200 and r["already"] is False and call(base, "/api/status")[1]["recording"]["miniview"] == {"key": key, "error": None}, r)
    again = call(base, "/api/record/start", {})[1]
    check("a second start says it was already recording (Mission Control then does not own it)", again["already"] is True and again["recording"] == r["recording"], again)
    session = call(base, "/api/lock", {"action": "acquire", "client": "sim-rec"})[1]["session"]
    drive_for(base, session, 1.2, 60, 60)
    drive_for(base, session, 1.6, -50, 50)                       # a spin to the left: the sim turns at 0.9 of what the tachos count
    call(base, "/api/record/stop", {})
    run_dir = keys.run_dir(mv, key)
    records = mcapio.read(run_dir, keep_raw=True)
    run = records[0][2]
    check("the run is of the apartment, in the scene's folder, and finished", run["scene"] == "apartment" and run_dir.parts[-3:-1] == ("nxt", "apartment")
          and sorted(p.name for p in run_dir.iterdir()) == ["run.mcap"], run["scene"])
    raw = APARTMENT.read_bytes()
    js = run.get("judge_scene") or {}
    check("it records which scene file it was in: the id, the file's sha256 (D2's), and runfile's checksum and path",
          js.get("id") == "apartment" and js.get("sha256") == hashlib.sha256(raw).hexdigest() and js.get("checksum") == scenefile.describe(APARTMENT)["checksum"]
          and js.get("path") == str(APARTMENT.resolve()), js)
    check("with no geometry in the config the run still has a belief, from the sim's own numbers, and says so",
          run["odometry"]["source"] == "sim world" and not run.get("no_pose"), run.get("odometry"))
    ticks = [(t, p) for t, k, p in records if k == "tick"]
    epochs = [(t, p) for t, k, p in records if k == "epoch"]
    check("ticks, one epoch, and it comes before the first tick", len(ticks) > 15 and len(epochs) == 1 and epochs[0][0] <= ticks[0][0], (len(ticks), len(epochs)))
    paired = [p for _, p in ticks if p.get("truth") is not None]
    check("every tick holds the truth read with it, and its wall time in the raw", len(paired) == len(ticks) and all(isinstance((p.get("raw") or {}).get("wall_ns"), int) for _, p in ticks))
    m2w = tuple(epochs[0][1]["map_to_world"])
    first, last = ticks[0][1], ticks[-1][1]
    check("the epoch puts the first belief (the origin) on the first truth, which is by then a little past the start pose (0, 2, 90 deg): driving began before the first sample",
          all(abs(a - b) < 1e-3 for a, b in zip(compose(m2w, tuple(first["belief"])), first["truth"])) and abs(first["truth"][0]) < 0.02
          and 1.99 < first["truth"][1] < 2.1 and abs(first["truth"][2] - math.pi / 2) < 0.02, (m2w, first["belief"], first["truth"]))
    check("the robot drove north along the corridor: the truth went up in y while the belief went along its own x",
          last["truth"][1] > first["truth"][1] + 0.15 and last["belief"][0] > 0.15, (first["truth"], last["truth"], last["belief"]))
    seen = compose(m2w, tuple(last["belief"]))
    spin = abs(math.remainder(seen[2] - last["truth"][2], math.tau))
    check("the sim's turn slip is in the run: the belief, put in the world, is not where the truth is (heading apart, about a tenth of the turn)",
          spin > 0.05, (seen, last["truth"]))
    check("the CSV is still there", (tmp / "runs" / f"{name}.csv").exists())
    listed = call(base, "/api/runs")[1]["runs"][0]
    check("the run list links the finished run's mcap, in its scene", listed["mcap"] == f"{name}.mcap", listed)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(tmp, ignore_errors=True)

# A record start that lands between a sample's truth read and its write: that sample was written without its truth, so its tick
# came before the epoch (seen under load, 2026-11-24). In process, with the start made at exactly that moment.
from nxt_lab.robot import SimRobot
from nxt_lab.web import Controller
from nxt_lab.world import World

tmp2 = Path(tempfile.mkdtemp(prefix="nxt-rec-race-", dir=os.environ.get("TMPDIR")))
try:
    cfg = Config.from_dict({})
    world = World.from_scene(APARTMENT, None, (0.0, 2.0, math.pi / 2))
    ctl = Controller(cfg, fake=True, config_path=tmp2 / "config.json", miniview_data=tmp2 / "mv", world=world)
    ctl.recorder.runs_dir = tmp2 / "runs"
    ctl.robot = SimRobot(cfg, world=world)
    class StartFirst:
        """The recorder's lock, but the first sample to wait for it finds a record start has taken it just before."""
        def __init__(self):
            self.real, self.armed = threading.Lock(), True

        def __enter__(self):
            if self.armed:
                self.armed = False
                ctl.recorder.start()
            self.real.acquire()

        def __exit__(self, *exc):
            self.real.release()
    ctl.recorder._lock = StartFirst()
    for _ in range(4):
        ctl.recorder.sample_once()
    key = ctl.recorder.recording["run"]
    ctl.recorder.stop()
    records = mcapio.read(keys.run_dir(tmp2 / "mv", key), keep_raw=True)
    ticks = [(t, p) for t, k, p in records if k == "tick"]
    epochs = [t for t, k, p in records if k == "epoch"]
    check("a recording started between a sample's truth read and its write: every tick has a truth and the epoch is first",
          bool(ticks and epochs) and epochs[0] <= ticks[0][0] and all(p.get("truth") is not None for _, p in ticks),
          (len(ticks), epochs[:1], ticks[:1]))
finally:
    shutil.rmtree(tmp2, ignore_errors=True)

print("test_recorder_sim", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
