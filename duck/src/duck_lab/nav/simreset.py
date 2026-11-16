"""Put the simulated duck back at its dock with an empty map: duck-sim down and up, mapd fresh.

The body server places the duck at (0, 0) facing +x on every start (it takes no position), so a
restart is how a test gets the same start for every goal. Takes ~40 s.
"""

import os
import socket
import subprocess
import time
from pathlib import Path

REPO = Path(os.environ.get("DUCK_SIM_REPO", "/work/pollen/microduck"))
RL = os.environ.get("DUCK_SIM_RL", "/work/pollen/microduck_rl")
STATE = Path(os.path.expanduser("~/.cache/duck-sim"))


def _env(scene: str) -> dict:
    env = dict(os.environ)
    env.update(PATH=f"{os.path.expanduser('~/.cargo/bin')}:{env.get('PATH', '')}", DUCK_SIM_RL=RL,
               DUCK_SIM_VIEWER="0", DUCK_SIM_SCENE=scene)
    env.pop("DUCK_SIM_KEYFRAME", None)
    return env


def stop_mapd() -> None:
    pid_file = STATE / "mapd.pid"
    if not pid_file.exists():
        return
    pid = int(pid_file.read_text().strip() or 0)
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            mine = b"mapd" in f.read()
    except OSError:
        mine = False
    if mine:
        os.kill(pid, 15)
        time.sleep(1)
    pid_file.unlink(missing_ok=True)


def down(scene: str = "apartment_backlash") -> None:
    """mapd and the simulator stopped (duck-sim down stops what its pidfiles name, after checking each is what it says)."""
    stop_mapd()
    subprocess.run([str(REPO / "scripts" / "duck-sim"), "down"], env=_env(scene), capture_output=True, timeout=120)


def reset(scene: str = "apartment_backlash") -> None:
    """Down, up, fresh mapd. Raises if the duck does not stand or mapd does not answer."""
    env = _env(scene)
    stop_mapd()
    subprocess.run([str(REPO / "scripts" / "duck-sim"), "down"], env=env, capture_output=True, timeout=120)
    up = subprocess.run([str(REPO / "scripts" / "duck-sim"), "up"], env=env, capture_output=True, text=True,
                        timeout=300)
    if "standing" not in up.stdout:
        raise RuntimeError(f"duck-sim up did not stand the duck:\n{up.stdout[-800:]}{up.stderr[-400:]}")
    cfg = STATE / "robotd-duck-a-map.toml"
    base = (STATE / "robotd-duck-a.toml").read_text()
    cfg.write_text(base + "\n[map]\nenabled = true\n")
    (STATE / "duck-a-map.json").unlink(missing_ok=True)
    # A stopped mapd leaves its socket file behind; an old file must not pass for a listening mapd.
    (STATE / "duck-a-map.sock").unlink(missing_ok=True)
    log = open(STATE / "mapd.log", "w")
    proc = subprocess.Popen([str(REPO / "target" / "debug" / "mapd"), "--config", str(cfg),
                             "--robot-socket", str(STATE / "duck-a.sock"), "--tof-socket", str(STATE / "duck-a-tof.sock"),
                             "--socket", str(STATE / "duck-a-map.sock"), "--map", str(STATE / "duck-a-map.json")],
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (STATE / "mapd.pid").write_text(str(proc.pid))
    for _ in range(50):
        probe = socket.socket(socket.AF_UNIX)
        try:
            probe.connect(str(STATE / "duck-a-map.sock"))
            return
        except OSError:
            time.sleep(0.2)
        finally:
            probe.close()
    raise RuntimeError("mapd did not start listening")
