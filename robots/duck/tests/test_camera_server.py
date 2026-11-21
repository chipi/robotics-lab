"""The simulated camera as a sensor the host serves (RFC-0021 step 6, duck_lab/camera_server.py and duck_lab/nav/camera.py):
a fake body server holds the duck at a pose; the camera server reads it, the navigator's client asks over the socket and
gets what the camera recognises, relative to the duck, and nothing of the world. The body server restarted (a reset) is
connected again. No simulator.
Run: cd robots/duck && uv run python tests/test_camera_server.py"""

import json
import math
import socket
import socketserver
import tempfile
import threading
from pathlib import Path

import simhost
from duck_lab.camera_server import CameraServer
from duck_lab.nav.camera import CameraClient
from duck_lab.nav.sim_camera import SimCamera
from worldmodel.semantic_map import Detection

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


class FakeBody(socketserver.ThreadingTCPServer):
    """The body server's hello and read; the trunk at `pose` (x, y, yaw). Counts its connections."""
    allow_reuse_address = daemon_threads = True

    def __init__(self, pose, port=0):
        self.pose, self.connections, self.open = pose, 0, []
        super().__init__(("127.0.0.1", port), Handler)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.server.connections += 1
        self.server.open.append(self.connection)
        for line in self.rfile:
            req = json.loads(line)
            x, y, yaw = self.server.pose
            out = {"ok": True} if req["op"] == "hello" else \
                {"trunk": [x, y, 0.116], "sim_time": 1.0, "imu": {"quat": [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]}}
            self.wfile.write((json.dumps(out) + "\n").encode())


def serve(body):
    threading.Thread(target=body.serve_forever, daemon=True).start()
    return body


def kill(body):
    """As the process ending: no new connection, and the open ones closed."""
    body.shutdown()
    body.server_close()
    for c in body.open:
        try:
            c.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        c.close()


OFFICE_WEST = (2.5, -0.6, math.pi)          # test_world_model: from here the green capsule (lm_office, at 0.95, -0.6) is in view
body = serve(FakeBody(OFFICE_WEST))
port = body.server_address[1]
tmp = Path(tempfile.mkdtemp(prefix="cam-"))
host = simhost.parse({"host": 1, "kind": "pollen-duck-sim", "robot": "duck-a", "pollen": {"microduck": "/m", "microduck_rl": "/r"},
                      "state": str(tmp), "truth_port": port, "cargo_bin": "/c"}, tmp / "host.json")
check("the host file names the camera's socket in its state folder", host.sockets["camera"] == tmp / "duck-a-camera.sock",
      host.sockets)
exact = SimCamera(config={"p_detect": 1.0, "range_noise": 0.0, "bearing_noise_deg": 0.0}, seed=1)
server = CameraServer(host, host.sockets["camera"], camera=exact).start()
client = CameraClient(host.sockets["camera"])
check("camera.info: the field of view, range and period, the navigator's to know", set(client.cfg) == {"hfov_deg", "range_m", "period_s"}
      and client.cfg["hfov_deg"] == 60.0, client.cfg)
found = client.detect()
caps = [d for d in found if d.kind == "green_capsule"]
check("camera.detect: the capsule in view is recognised, as a Detection", len(caps) == 1 and isinstance(caps[0], Detection), found)
c = caps[0]
check("relative to the duck: 1.55 m ahead (the capsule is at x 0.95, the duck at 2.5 facing west), none of it a world coordinate",
      abs(c.x - 1.55) < 1e-6 and abs(c.y) < 1e-6 and (round(c.x, 3), round(c.y, 3)) != (0.95, -0.6), (c.x, c.y))
check("the same as the sensor model answers from the truth in its own process (the old way)",
      [(d.kind, round(d.x, 6), round(d.y, 6)) for d in found]
      == [(d.kind, round(d.x, 6), round(d.y, 6)) for d in SimCamera(config=exact.cfg, seed=1).detect(OFFICE_WEST)], found)

with socket.socket(socket.AF_UNIX) as s:
    s.connect(str(host.sockets["camera"]))
    s.sendall(b'{"jsonrpc": "2.0", "id": 1, "method": "camera.detect"}\n')
    raw = json.loads(s.makefile().readline())["result"]
check("what goes over the socket is the detections and a wall clock: no pose, no truth",
      set(raw) == {"wall_ns", "detections"} and all(set(d) <= {"kind", "x", "y", "radius", "z0", "z1", "range_m", "confidence",
                                                               "source", "evidence"} for d in raw["detections"]), raw)
body.pose = (2.5, -0.6, 0.0)
check("the duck turned east (the truth moved): the capsule is out of view", not [d for d in client.detect() if d.kind == "green_capsule"])

# a reset restarts the body server: the camera connects again, on the next look
kill(body)
before = server.looks
body2 = serve(FakeBody(OFFICE_WEST, port))
check("after the body server came back (a reset), the next look connects again and sees",
      [d.kind for d in client.detect() if d.kind == "green_capsule"] == ["green_capsule"] and server.looks == before + 1
      and body2.connections == 1, (server.looks, body2.connections))
kill(body2)
try:
    client.detect()
    gone = None
except RuntimeError as e:
    gone = str(e)
check("with no body server at all, the look is an error the navigator records (camera_failed), not a made-up answer",
      gone is not None and "camera.detect" in gone, gone)

try:
    CameraServer(host, host.sockets["camera"], camera=exact).start()
    second = None
except RuntimeError as e:
    second = str(e)
check("a second runner on the same host is refused the camera's socket while the first serves it (one runner per simulator)",
      second is not None and "already served" in second and host.sockets["camera"].exists(), second)
client.close()
server.stop()
check("stopped: the socket is gone", not host.sockets["camera"].exists())
no_truth = simhost.parse({"host": 1, "kind": "pollen-duck-sim", "robot": "duck-a", "pollen": {"microduck": "/m", "microduck_rl": "/r"},
                          "state": str(tmp), "truth_port": None, "cargo_bin": "/c"}, tmp / "real.json")
try:
    CameraServer(no_truth, tmp / "x.sock")
    refused = None
except ValueError as e:
    refused = str(e)
check("a host with no truth (the real duck) has no simulated camera: refused, saying why", refused and "no truth" in refused, refused)

print()
print("CAMERA SERVER", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
