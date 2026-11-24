"""The host kind `nxt-kinematic-sim` (RFC-0025 §3.4; docs/wip/NXT-D0.md): nxt-web run with --sim (apps/nxt-web). Its reset is
a restart of that process at the start pose; its truth is `GET /api/sim/truth` on nxt-web's own port, which carries no
command and so needs no control lock. Standard library only.

A restart answers its first status with the start pose, so this reset meets "returns only when the simulator is settled" without
exercising it (D0 §1, item 5): a simulator that keeps moving after its restart needs a post-reset sample, and this is not the
proof of that."""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.request

from simhost.host import NxtHost
from simhost.simulator import command_of

SETTLE_S = 15.0
POSE_TOL = (1e-3, 1e-3, 1e-3)       # m, m, rad: the world's reset is exact; this is for the JSON round trip


def _get(url: str, timeout: float = 2.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def read_truth(host: NxtHost) -> tuple:
    """(wall_ns, (x, y, yaw)) now, from the simulator's own clock and model (nxt_lab SimRobot.truth)."""
    r = _get(host.url + "/api/sim/truth")
    return r["wall_ns"], tuple(r["pose"])


class Truth:
    """The reader a Sampler uses (the duck's is truth.Body): the same `read()` and `close()`. The kinematic sim has no height,
    so z is 0 and the orientation is the yaw alone; it runs on the wall clock, so there is no sim_time."""

    def __init__(self, host: NxtHost):
        self._host = host

    def read(self) -> tuple:
        _, pose = read_truth(self._host)
        half = pose[2] / 2
        return tuple(pose), 0.0, (math.cos(half), 0.0, 0.0, math.sin(half)), None

    def close(self) -> None:
        pass


def _answers(host: NxtHost) -> bool:
    try:
        _get(host.url + "/api/status", timeout=1.0)
        return True
    except (OSError, ValueError):       # URLError is an OSError; ValueError is a body that is not JSON
        return False


def stop(host: NxtHost) -> None:
    """The nxt-web our reset started, stopped: the pid file's process, only if it is nxt-web (a pid can be reused). SIGTERM
    takes nxt-web's own stop-the-motors path."""
    pid_file = host.state / "nxt-web.pid"
    if not pid_file.exists():
        return
    pid = int(pid_file.read_text().strip() or 0)
    cmd = command_of(pid)
    if cmd and "nxt-web" in cmd:
        os.kill(pid, 15)
        for _ in range(100):
            if not command_of(pid):         # gone, or a zombie (our own child, not yet waited for: empty command line)
                break
            time.sleep(0.1)
    pid_file.unlink(missing_ok=True)


def _command(host: NxtHost, scene) -> list:
    exe = host.project / ".venv" / "bin" / "nxt-web"
    if not exe.exists():
        raise RuntimeError(f"{exe} does not exist: run `uv sync` in {host.project} (the host file's nxt_web.project)")
    x, y, yaw = host.start
    url = host.url.split("//", 1)[1].rsplit(":", 1)
    cmd = [str(exe), "--sim", "--world", str(scene or host.scene), "--host", url[0], "--port", str(url[1]),
           "--start", str(x), str(y), str(math.degrees(yaw))]
    return cmd + (["--sim-params", str(host.params)] if host.params else []) + \
        (["--takeover-names", str(host.takeover_names)] if host.takeover_names else [])


def _at_start(host: NxtHost) -> bool:
    try:
        _, pose = read_truth(host)
    except (OSError, ValueError, KeyError):
        return False
    return all(abs(a - b) <= t for a, b, t in zip(host.start[:2], pose[:2], POSE_TOL[:2])) and \
        abs(math.remainder(host.start[2] - pose[2], math.tau)) <= POSE_TOL[2]


def reset(host: NxtHost, scene=None) -> None:
    """nxt-web restarted at the host's start pose; `scene` (a scene.json path) replaces the host's for this start. Returns
    when it answers, is connected and its truth reads the start pose. Raises if it does not."""
    cmd = _command(host, scene)
    stop(host)
    if _answers(host):
        # Not ours (no pid file named it): a restart would fail to bind, and the old server's answers would pass for ours.
        raise RuntimeError(f"something already answers at {host.url} that this reset did not start: stop it first")
    host.state.mkdir(parents=True, exist_ok=True)
    log = open(host.state / "nxt-web.log", "w")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (host.state / "nxt-web.pid").write_text(str(proc.pid))
    deadline = time.monotonic() + SETTLE_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"nxt-web exited ({proc.returncode}) on start:\n"
                               f"{(host.state / 'nxt-web.log').read_text()[-800:]}")
        try:
            connected = _get(host.url + "/api/status", timeout=1.0).get("connected")
        except (OSError, ValueError):
            connected = False
        if connected and _at_start(host):
            return
        time.sleep(0.1)
    stop(host)
    raise RuntimeError(f"nxt-web did not settle at {host.start} within {SETTLE_S:.0f} s ({host.url})")


def down(host: NxtHost, scene=None) -> None:
    stop(host)
