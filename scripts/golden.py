"""The restructure's golden (docs/wip/PHASE2-RESTRUCTURE-PLAN.md, "Golden"): the same answers before and after every move.

    python3 scripts/golden.py          # prints one `sha256 name` line per answer; two runs must print the same lines

Two things are hashed, each in a temporary data folder that is removed afterwards:
  api     a committed fixture run (explore9) imported with the Observatory's CLI, then the server's answers for it
          (the run, its frames, its signals, its state at 5 s), byte for byte;
  replay  a run the navigator's own writer makes from fixed frames (the construction of duck/tests/test_replay.py: no
          committed fixture run has depth frames), then `duck-replay` on it: its whole report.
The folders are found where they are (viewer/ or apps/observatory, duck/ or robots/duck) and the CLI by the name its
pyproject gives (miniview or observatory). Standard library only; the work runs in each project's own environment.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import atexit
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_MTIME = 1_700_000_000


def first_dir(*names: str) -> Path:
    for n in names:
        if (ROOT / n / "pyproject.toml").exists():
            return ROOT / n
    raise SystemExit(f"none of {names} is a project here")


def cli_name(project: Path) -> str:
    scripts = tomllib.loads((project / "pyproject.toml").read_text())["project"]["scripts"]
    return "observatory" if "observatory" in scripts else "miniview"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run(cmd: list, cwd: Path, env: dict) -> str:
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"FAIL {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def api_answers(tmp: Path) -> list:
    viewer = first_dir("apps/observatory", "viewer")
    cli = cli_name(viewer)
    data, idx = tmp / "data", tmp / "index.sqlite"
    (data / "runs").mkdir(parents=True)
    (data / "scenes").mkdir()
    env = dict(os.environ, MINIVIEW_INDEX=str(idx), OBSERVATORY_INDEX=str(idx))
    fixture = tmp / "explore9"
    shutil.copytree(viewer / "tests" / "fixtures" / "explore9", fixture)
    for f in [*fixture.iterdir(), fixture]:
        os.utime(f, (FIXTURE_MTIME, FIXTURE_MTIME))    # the run's start time is the log's mtime (started_at_source file_mtime)
    run(["uv", "run", "--frozen", cli, "--data", str(data), "import", str(fixture), "--scene", "apartment"], viewer, env)
    port = 18000 + os.getpid() % 1000
    srv = subprocess.Popen(["uv", "run", "--frozen", cli, "--data", str(data), "serve", "--host", "127.0.0.1", "--port", str(port)],
                           cwd=viewer, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = []
    try:
        base = f"http://127.0.0.1:{port}/api/v1"
        for _ in range(120):
            try:
                urllib.request.urlopen(f"{base}/health", timeout=2).read()
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise SystemExit("FAIL the server did not answer")
        for name, path in (("run", "/runs/duck/apartment/explore9"), ("frames", "/runs/duck/apartment/explore9/frames?from=0&to=1000"),
                           ("signals", "/runs/duck/apartment/explore9/signals?from=0&to=1000"),
                           ("state", "/runs/duck/apartment/explore9/state?t=5")):
            body = urllib.request.urlopen(base + path, timeout=30).read()
            out.append((f"api {name} ({len(body)} bytes)", sha(body)))
    finally:
        srv.terminate()
        srv.wait(timeout=20)
    return out


def replay_answer(tmp: Path) -> list:
    duck = first_dir("robots/duck", "duck")
    data = tmp / "duckdata"
    data.mkdir()
    env = dict(os.environ)
    run(["uv", "run", "--frozen", "python", str(Path(__file__).resolve()), "make-run", str(data)], duck, env)
    rep = run(["uv", "run", "--frozen", "duck-replay", "duck/apartment/explore99", "--miniview-data", str(data)], duck, env)
    if "REPLAY PASS" not in rep:
        raise SystemExit("FAIL duck-replay did not pass:\n" + rep)
    return [(f"replay report ({len(rep.splitlines())} lines)", sha(rep.encode()))]


def make_run(data: Path) -> None:
    """Runs in the duck's environment: a run written by the navigator's own RunLog from fixed frames."""
    import collections
    import math

    from duck_lab.nav.cliff import BEAMS, rotate, sensor_pose
    from duck_lab.nav.frames import Localizer
    from duck_lab.nav.run import Navigator
    from duck_lab.nav.runlog import RunLog
    from duck_lab.nav.side_drops import SuspectMemory

    ms = 1_000_000

    def robot_state(t_ns, pitch_deg=25.0, height=0.118, trunk_pitch=0.0, x=0.0):
        p, h = math.radians(pitch_deg) / 2, math.radians(trunk_pitch) / 2
        return {"t_ns": t_ns, "odom": {"position": [x, 0.0, height], "yaw": 0.0},
                "imu": {"quat": [math.cos(h), 0.0, math.sin(h), 0.0], "gyro": [0.0, 0.5, 0.0]},
                "frames": {"tof": {"pos": [0.08, 0.0, 0.11], "quat": [math.cos(p), 0.0, math.sin(p), 0.0]}}}

    def frame_for(st, t_ns, seq, floor_until_m=None, drop_m=0.3):
        height, q = sensor_pose(st)
        dist = []
        for beam in BEAMS:
            d = rotate(q, beam)
            if d[2] >= -0.01:
                dist.append(2000)
                continue
            t = -height / d[2]
            if floor_until_m is not None and t * math.hypot(d[0], d[1]) > floor_until_m:
                t = -(height + drop_m) / d[2]
            dist.append(int(t * beam[0] * 1000))
        return {"seq": seq, "t_ns": t_ns, "rows": 8, "cols": 8, "distance_mm": dist, "status": [5] * 64}

    rl = RunLog(data, "apartment", "explore99", "exploration", None)
    nav = Navigator.__new__(Navigator)
    nav.scale, nav.loc = 1.0, Localizer()
    nav.loc.map_from_odom = (1.2345678901, 2.3456789012, 0.1234567890)
    nav._t0, nav.runlog, nav._sid = time.monotonic(), rl, rl.new_session()
    nav._states, nav._fv, nav.sense, nav._logging_failed = collections.deque(maxlen=40), None, {}, False
    nav.tof = type("Tof", (), {"nearest_mm": 380})()
    nav.floor_seen, nav.suspects, nav._low = set(), SuspectMemory(), {}
    nav.sense = {"room_m": 0.2, "turning": 1}
    for k in range(10):
        nav._on_state(robot_state(1_000_000_000 + k * 50 * ms, trunk_pitch=2.0 * k, x=0.01 * k))
    frames_in = []
    for k in range(6):
        nav._on_frame(frame_for(robot_state(0), 1_000_000_000 + (60 + 70 * k) * ms, 100 + k, floor_until_m=0.4 if k >= 2 else None))
        frames_in.append(nav._fv)
    rl.row(nav._sid, {"t": 0.05, "pose": [1.0, 2.0, 0.0], "truth": [0.0, 0.0, 0.0], "vx": 0.2, "vyaw": 0.0, "depth": frames_in[-1].points})
    rl.row(nav._sid, {"t": 0.2, "pose": [1.1, 2.0, 0.0], "truth": [0.1, 0.0, 0.0], "vx": 0.2, "vyaw": 0.0, "depth": frames_in[0].points})
    rl.finish()


def main() -> int:
    if sys.argv[1:2] == ["make-run"]:
        make_run(Path(sys.argv[2]))
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="golden-"))
    atexit.register(shutil.rmtree, tmp, True)
    try:
        for name, digest in api_answers(tmp) + replay_answer(tmp):
            print(f"{digest}  {name}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
