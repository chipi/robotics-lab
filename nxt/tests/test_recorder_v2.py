"""nxt-web writes its recordings as miniview runs, live (ADR-0013), against the simulated brick only (--fake): the run is in a
catalog while it is being recorded, its ticks grow, the pose comes from the fake brick's tachos when the wheel geometry is
set and is absent with the reason when it is not, the file is compacted when the recording stops, a second recording in the
same second gets its own name, the CSV is always written, and a miniview data folder that cannot be written costs the run,
never the recording. It never opens a real brick: every server here is started with --fake.
Run: make test-unit (or python nxt/tests/test_recorder_v2.py)."""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from runfile import keys, mcapio
from runfile.catalog import Catalog
from nxt_lab import config as cfgmod
from nxt_lab.config import Config

NXT_DIR = Path(__file__).resolve().parents[1]
NXT_WEB = os.environ.get("NXT_WEB", str(NXT_DIR / ".venv" / "bin" / "nxt-web"))
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:200]}]" if detail else ""))
    if not cond:
        failures.append(name)


def wait_until(cond, timeout=15.0, every=0.05, what="condition"):
    """The value of cond() once it is truthy; the failure names what it waited for."""
    end = time.monotonic() + timeout
    while True:
        v = cond()
        if v:
            return v
        if time.monotonic() > end:
            raise TimeoutError(f"timed out after {timeout} s waiting for {what}")
        time.sleep(every)


def call(base, path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class Server:
    """nxt-web --fake on a free port with its data in a folder of its own; stopped (SIGTERM, the path that finalizes a recording) on exit."""

    def __init__(self, root: Path, config: Config, miniview_data: Path, port: int):
        self.root, self.port = root, port
        root.mkdir(parents=True, exist_ok=True)
        cfgmod.save(config, root / "config.json")
        env = dict(os.environ, NXT_LAB_DATA=str(root), MINIVIEW_DATA=str(miniview_data))
        self.p = subprocess.Popen([NXT_WEB, "--fake", "--port", str(port), "--config", str(root / "config.json")], stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, env=env)
        self.p.stdout.readline()
        self.base = f"http://127.0.0.1:{port}"
        self.session = None

    def drive_for(self, seconds, left=50, right=50):
        """The page's keepalive: the drive command again every 0.2 s (the watchdog stops the tracks after 0.6 s of silence)."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.session is None:
                self.session = call(self.base, "/api/lock", {"action": "acquire", "client": "test"})[1]["session"]
            call(self.base, "/api/drive", {"left": left, "right": right, "session": self.session})
            time.sleep(0.2)

    def close(self):
        self.p.terminate()
        self.p.wait(10)


tmp = Path(tempfile.mkdtemp(prefix="nxt-v2-"))
try:
    # ---- with the wheel geometry: a pose from the fake brick's tachos, live while recording ------------------------------
    mv = tmp / "mv"
    cfg = Config(sample_hz=10.0, odom_sprocket_diameter_m=0.043, odom_track_width_m=0.12)
    s = Server(tmp / "a", cfg, mv, 8771)
    try:
        code, r = call(s.base, "/api/record/start", {})
        name = r["recording"][:-4]
        key = f"nxt/unmapped/{name}"
        st = call(s.base, "/api/status")[1]
        check("record start names the run: the status says the miniview run's key, and no error", code == 200 and st["recording"]["miniview"] == {"key": key, "error": None}, st["recording"])
        cat = Catalog(mv, index=tmp / "idx-a.sqlite")
        cat.scan()
        ld = cat.get(key)
        check("the run is live in a catalog before it has a sample: its live file and lock are there, the writer is alive",
              cat.status(ld) == "live" and (keys.run_dir(mv, key) / "run.live.mcap").exists() and mcapio.writer_alive(keys.run_dir(mv, key)))
        s.drive_for(1.0)
        wait_until(lambda: cat.follow_once() is not None and ld.data.run["ticks"] >= 5, 15, what="5 ticks of the live run")
        first = ld.data.run["samples"]
        s.drive_for(0.8)
        wait_until(lambda: cat.follow_once() is not None and ld.data.run["samples"] > first + 3, 15, what="the live run to grow")
        check("while recording the run grows: ticks and samples go up, the file is still live", cat.status(ld) == "live" and ld.data.run["samples"] > first)
        fr = ld.data.frames
        check("the fake brick drove forward: the pose moves along +x, no sideways drift, heading 0", fr["belief"][-1][0] > 0.1 and abs(fr["belief"][-1][1]) < 1e-3
              and abs(fr["belief"][-1][2]) < 1e-6, fr["belief"][-1])
        d = ld.data.run["odometry"]
        check("the run record carries the geometry and where it came from (the config)", d["sprocket_diameter_m"] == 0.043 and d["track_width_m"] == 0.12 and d["source"] == "config"
              and d["left"] == "C" and d["right"] == "B")
        s.drive_for(0.6, left=-40, right=40)                                    # a spin: left back, right ahead (the fake brick's tachos follow)
        code, r = call(s.base, "/api/record/stop", {})
        done = call(s.base, "/api/runs")[1]["runs"][0]
        run_dir = keys.run_dir(mv, key)
        check("stop compacts: run.mcap only, no live file or lock", sorted(p.name for p in run_dir.iterdir()) == ["run.mcap"], sorted(p.name for p in run_dir.iterdir()))
        cat.follow_once()
        wait_until(lambda: (cat.follow_once() or True) and ld.follower.done, 10, what="the compacted file to be read")
        rows = (s.root / "runs" / f"{name}.csv").read_text().splitlines()[1:]
        run = ld.data.run
        check("the CSV is still written, one row per sample, and the run has the same samples, a pose for each, and ended 'recorded'",
              len(rows) == run["samples"] == run["ticks"] > 8 and run["status"] == "ended" and run["verdict"] == "recorded", (len(rows), run["samples"], run["ticks"], run["verdict"]))
        check("the spin turned the pose: the heading at the end is counter-clockwise of where it was (right track ahead of the left)",
              ld.data.frames["belief"][-1][2] > 0.05 and ld.data.frames["belief"][-1][2] > ld.data.frames["belief"][-8][2] - 1e-9, ld.data.frames["belief"][-1])
        kinds = [(e["kind"]) for e in run["events"]]
        check("the command log is in the run: record start, the drives, and the stop", kinds[0] == "record start" and "drive" in kinds, kinds[:6])
        check("the run's end record carries the CSV's SHA-256 and the .mcap link lists it", mcapio.read(run_dir, keep_raw=True)[-1][2].get("source_sha256") and done["mcap"] == f"{name}.mcap", done)
        times = [t for t, _k, _p in mcapio.read(run_dir)]
        check("run time only grows, from about 0 to the length of the recording", times == sorted(times) and times[1] >= 0.0 and 1.5 < times[-1] < 15, (times[1], times[-1]))
        check("started_at is the writer's clock (the recording began now)", abs(run["started_at_ns"] / 1e9 - time.time()) < 60 and run["started_at_source"] == "writer", run["started_at_source"])

        # ---- recordings in quick succession: each its own CSV and run, nothing overwritten ------------------------------
        a = call(s.base, "/api/record/start", {})[1]["recording"]
        call(s.base, "/api/record/stop", {})
        b = call(s.base, "/api/record/start", {})[1]["recording"]
        call(s.base, "/api/record/stop", {})
        check("two recordings one after the other are two CSVs and two finished runs",
              a != b and all((s.root / "runs" / x).exists() and (mv / "runs" / "nxt" / "unmapped" / x[:-4] / "run.mcap").exists() for x in (a, b)), (a, b))
    finally:
        s.close()

    # ---- a name taken (by a CSV or by a miniview run) is never reused: -2, -3 ---------------------------------------------------
    import nxt_lab.recorder as rmod

    class Fixed(rmod.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 16, 10, 0, 0)

    real_datetime, rmod.datetime = rmod.datetime, Fixed
    try:
        rec = rmod.Recorder(None, runs_dir=tmp / "names" / "runs", miniview_data=tmp / "names" / "mv")
        (tmp / "names" / "runs").mkdir(parents=True)
        first = rec._free_name()
        (tmp / "names" / "runs" / f"{first}.csv").write_text("t\n")
        second = rec._free_name()
        keys.run_dir(tmp / "names" / "mv", f"nxt/unmapped/{second}").mkdir(parents=True)
        third = rec._free_name()
        check("a name taken by a CSV gives -2, one taken by a miniview run too gives -3, the first is the plain time",
              (first, second, third) == ("run-20261116-100000", "run-20261116-100000-2", "run-20261116-100000-3"), (first, second, third))
    finally:
        rmod.datetime = real_datetime

    # ---- without the wheel geometry: signals only, and the reason ------------------------------------------------------------
    mv2 = tmp / "mv2"
    s = Server(tmp / "b", Config(sample_hz=10.0), mv2, 8772)
    try:
        r = call(s.base, "/api/record/start", {})[1]
        key = f"nxt/unmapped/{r['recording'][:-4]}"
        s.drive_for(1.0)
        call(s.base, "/api/record/stop", {})
        cat = Catalog(mv2, index=tmp / "idx-b.sqlite")
        cat.scan()
        run = cat.get(key).data.run
        check("with no geometry in the config the run has signals and no pose, and says why",
              run["ticks"] == 0 and run["samples"] >= 5 and run.get("no_pose", "").startswith("no wheel geometry (set odom_sprocket_diameter_m and odom_track_width_m)")
              and run.get("odometry") is None and next(x for x in run["streams"] if x["id"] == "belief.pose")["missing"], (run["ticks"], run["samples"], run.get("no_pose")))
        status, resp = call(s.base, "/api/config", {"odom_sprocket_diameter_m": 0.043, "odom_track_width_m": None})
        check("one of the two values is not geometry: set only the diameter and the next recording has no pose either", status == 200)
        r = call(s.base, "/api/record/start", {})[1]
        key2 = f"nxt/unmapped/{r['recording'][:-4]}"
        time.sleep(0.5)
        call(s.base, "/api/record/stop", {})
        cat.scan()
        check("with only one of the two values set there is still no pose", cat.get(key2).data.run["ticks"] == 0 and cat.get(key2).data.run.get("no_pose"))
    finally:
        s.close()

    # ---- a data folder that cannot be written costs the miniview run, never the recording ---------------------------------------
    blocker = tmp / "not-a-folder"
    blocker.write_text("a file where the folder should be")
    s = Server(tmp / "c", Config(sample_hz=10.0), blocker / "mv", 8773)
    try:
        code, r = call(s.base, "/api/record/start", {})
        st = call(s.base, "/api/status")[1]
        time.sleep(0.6)
        call(s.base, "/api/record/stop", {})
        rows = (s.root / "runs" / r["recording"]).read_text().splitlines()
        check("the recording starts anyway, the status says why there is no miniview run, and the CSV gets its rows",
              code == 200 and st["recording"]["miniview"]["key"] is None and st["recording"]["miniview"]["error"] and len(rows) > 3, (st["recording"], len(rows)))
    finally:
        s.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# The image runs as root: what it writes into a host bind mount goes to $NXT_DATA_OWNER (ADR-0013). Recorded, not done:
# this test does not run as root.
from nxt_lab import recorder as rmod  # noqa: E402

own = Path(tempfile.mkdtemp())
calls, real_chown = [], os.chown
os.chown = lambda p, uid, gid, follow_symlinks=True: calls.append((Path(p).relative_to(own).as_posix(), uid, gid))
try:
    run_dir = own / "runs" / "nxt" / "unmapped" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "run.mcap").write_bytes(b"x")
    rmod.hand_over(own, run_dir, (4242, 4343))
    check("hand_over gives the owner the run, its files and the folders it created, not the data folder itself",
          sorted(c[0] for c in calls) == ["runs", "runs/nxt", "runs/nxt/unmapped", "runs/nxt/unmapped/run-1",
                                          "runs/nxt/unmapped/run-1/run.mcap"] and all(c[1:] == (4242, 4343) for c in calls), calls)
    calls.clear()
    rmod.hand_over(own, run_dir, None)
    st = run_dir.stat()
    rmod.hand_over(own, run_dir / "run.mcap", (st.st_uid, st.st_gid))
    check("without NXT_DATA_OWNER, or when the owner is already right, nothing is changed", calls == [], calls)
    os.environ["NXT_DATA_OWNER"] = "1000:1001"
    a = rmod.data_owner()
    os.environ["NXT_DATA_OWNER"] = "1000"
    b = rmod.data_owner()
    del os.environ["NXT_DATA_OWNER"]
    check("NXT_DATA_OWNER is uid:gid (or uid alone, gid the same)", (a, b, rmod.data_owner()) == ((1000, 1001), (1000, 1000), None), (a, b))
finally:
    os.chown = real_chown
    shutil.rmtree(own, ignore_errors=True)

print("test_recorder_v2", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
