"""Put the simulated duck back at its dock with an empty map: duck-sim down and up, mapd fresh (moved from the navigator's
nav/simreset.py, RFC-0021 §5 step 1: the reset is the host's, not the payload's).

The body server places the duck at (0, 0) facing +x on every start (it takes no position), so a restart is how a test
gets the same start for every goal. Takes ~40 s. `scene` is a scene name duck-sim knows (apartment_backlash) or the path
of a scene file (a challenge's, under the host's scenarios folder)."""

import os
import socket
import subprocess
import time

from simhost.host import Host

DEFAULT_SCENE = "apartment_backlash"
# duck-sim is written for a person at a terminal. Unpatched, every `down` asks sudo sixteen times whether a container
# unit runs; from a script there is no terminal to ask on, each ask is a failed login, and ten lock the user's sudo
# (2026-11-16: locked all day by the challenge runs). docs/wip/DUCK-SIM-FOR-AGENTS.md has the patch and the check.
SUDO_ASK = 'if sudo systemctl is-active --quiet "$name"'
PATCH = "robots/duck/sim/patches/duck-sim-sudo-free-down.patch"


def duck_sim(host: Host) -> str:
    script = host.microduck / "scripts" / "duck-sim"
    if SUDO_ASK in script.read_text():
        raise RuntimeError(f"{script} still asks sudo on every down, which locks the user's sudo when run from a script: "
                           f"apply {PATCH} (docs/wip/DUCK-SIM-FOR-AGENTS.md)")
    return str(script)


def _env(host: Host, scene: str) -> dict:
    env = dict(os.environ)
    env.update(PATH=f"{host.cargo_bin}:{env.get('PATH', '')}", DUCK_SIM_RL=str(host.microduck_rl),
               DUCK_SIM_VIEWER="0", DUCK_SIM_SCENE=scene)
    env.pop("DUCK_SIM_KEYFRAME", None)
    return env


def stop_mapd(host: Host) -> None:
    pid_file = host.state / "mapd.pid"
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


def down(host: Host, scene: str = DEFAULT_SCENE) -> None:
    """mapd and the simulator stopped (duck-sim down stops what its pidfiles name, after checking each is what it says)."""
    stop_mapd(host)
    subprocess.run([duck_sim(host), "down"], env=_env(host, scene), capture_output=True, timeout=120)


def reset(host: Host, scene: str = DEFAULT_SCENE) -> None:
    """Down, up, fresh mapd. Raises if the duck does not stand or mapd does not answer."""
    env = _env(host, scene)
    script = duck_sim(host)
    stop_mapd(host)
    subprocess.run([script, "down"], env=env, capture_output=True, timeout=120)
    up = subprocess.run([script, "up"], env=env, capture_output=True, text=True, timeout=300)
    if "standing" not in up.stdout:
        raise RuntimeError(f"duck-sim up did not stand the duck:\n{up.stdout[-800:]}{up.stderr[-400:]}")
    st, robot, sockets = host.state, host.robot, host.sockets
    cfg = st / f"robotd-{robot}-map.toml"
    base = (st / f"robotd-{robot}.toml").read_text()
    cfg.write_text(base + "\n[map]\nenabled = true\n")
    (st / f"{robot}-map.json").unlink(missing_ok=True)
    # A stopped mapd leaves its socket file behind; an old file must not pass for a listening mapd.
    sockets["map"].unlink(missing_ok=True)
    log = open(st / "mapd.log", "w")
    proc = subprocess.Popen([str(host.microduck / "target" / "debug" / "mapd"), "--config", str(cfg),
                             "--robot-socket", str(sockets["robot"]), "--tof-socket", str(sockets["depth"]),
                             "--socket", str(sockets["map"]), "--map", str(st / f"{robot}-map.json")],
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (st / "mapd.pid").write_text(str(proc.pid))
    for _ in range(50):
        probe = socket.socket(socket.AF_UNIX)
        try:
            probe.connect(str(sockets["map"]))
            return
        except OSError:
            time.sleep(0.2)
        finally:
            probe.close()
    raise RuntimeError("mapd did not start listening")
