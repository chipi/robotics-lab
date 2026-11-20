"""The simulator's truth, read by the runner (RFC-0021 step 2): Pollen's body server (this host kind's truth reader,
§3.1) on the host's truth_port, sampled on a thread of its own. The payload never imports this.

    sampler = Sampler(host, on_sample=lambda s: ...)    # s: Sample(wall_ns, t, pose [x, y, yaw], z, quat, sim_time)
    sampler.start(); ...; sampler.latest; sampler.stop()

`t` is seconds since the sampler started (the runner's clock); `wall_ns` the host's wall clock, the one the navigator
stamps its rows with (`wall_ns`), so a sample pairs with a row by it. `sim_time` is the simulator's own time: the real-time
factor is how fast it moves against the wall clock (`rtf`)."""

import json
import math
import socket
import threading
import time
from dataclasses import dataclass

from simhost.host import Host

HZ = 20.0


@dataclass(frozen=True)
class Sample:
    wall_ns: int
    t: float
    pose: tuple          # x, y, yaw of the trunk in the world
    z: float             # the trunk's height
    quat: tuple          # the trunk's whole orientation, w, x, y, z
    sim_time: float | None


class Body:
    """One connection to the body server (newline JSON: hello, then read)."""

    def __init__(self, port: int, host: str = "127.0.0.1", timeout: float = 5.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._f = self._sock.makefile("rw")
        self._call({"op": "hello", "protocol": 1, "joints": 15})

    def _call(self, req: dict) -> dict:
        self._f.write(json.dumps(req) + "\n")
        self._f.flush()
        line = self._f.readline()
        if not line:
            raise ConnectionError("the body server closed the connection")
        return json.loads(line)

    def read(self) -> tuple:
        """(pose, z, quat, sim_time) now."""
        r = self._call({"op": "read"})
        w, x, y, z = r["imu"]["quat"]
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        return (r["trunk"][0], r["trunk"][1], yaw), r["trunk"][2], (w, x, y, z), r.get("sim_time")

    def close(self) -> None:
        self._sock.close()


class Sampler:
    def __init__(self, host: Host, on_sample=None, hz: float = HZ):
        if host.truth_port is None:
            raise ValueError(f"{host.source}: this host has no truth (truth_port is null)")
        self.port, self.on_sample, self.period = host.truth_port, on_sample, 1.0 / hz
        self.latest: Sample | None = None
        self.samples = 0
        self.error = None
        self._first = None           # (wall_ns, sim_time) of the first sample: the real-time factor's base
        self._stop = threading.Event()
        self._thread = None
        self._t0 = None

    def start(self) -> "Sampler":
        self._body = Body(self.port)
        self._t0 = time.monotonic()
        self.sample()                # one at once: `latest` is set when start returns
        self._thread = threading.Thread(target=self._loop, name="truth-sampler", daemon=True)
        self._thread.start()
        return self

    def sample(self) -> Sample:
        pose, z, quat, sim_time = self._body.read()
        s = Sample(time.time_ns(), round(time.monotonic() - self._t0, 3), pose, z, quat, sim_time)
        if self._first is None:
            self._first = (s.wall_ns, sim_time)
        self.latest = s
        self.samples += 1
        if self.on_sample:
            self.on_sample(s)
        return s

    def _loop(self) -> None:
        nxt = time.monotonic()
        while not self._stop.is_set():
            nxt += self.period
            try:
                self.sample()
            except Exception as e:      # noqa: BLE001 - said once, and the sampler stops: a judge with no truth must know
                self.error = f"{type(e).__name__}: {e}"
                return
            self._stop.wait(max(0.0, nxt - time.monotonic()))

    def rtf(self) -> float | None:
        """The simulator's real-time factor since the first sample: simulated seconds per wall second."""
        if not self._first or self.latest is None or self._first[1] is None or self.latest.sim_time is None:
            return None
        wall = (self.latest.wall_ns - self._first[0]) / 1e9
        return round((self.latest.sim_time - self._first[1]) / wall, 3) if wall > 0 else None

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        try:
            self._body.close()
        except OSError:
            pass
