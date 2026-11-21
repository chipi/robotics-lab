"""The simulated camera as a sensor the host serves (RFC-0021 step 6): the runner's side, not the navigator's. It reads the
truth itself (the host's body server) and answers on a socket with what the camera recognises, so the navigator gets what
a real camera's detector would give it and never the truth (duck_lab.nav.sim_camera has the sensor model).

    server = CameraServer(host, path).start()     # ...; server.stop()

Newline JSON-RPC 2.0 on a unix socket (the robot's sockets' framing, duck_lab.nav.client.Rpc):
  camera.info   -> {hfov_deg, range_m, period_s}
  camera.detect -> {wall_ns, detections: [{kind, x, y, radius, z0, z1, range_m, confidence, source}]}   relative to the duck
The navigator's side is duck_lab.nav.camera.CameraClient."""

from __future__ import annotations

import json
import socketserver
import threading
import time
from dataclasses import asdict
from pathlib import Path

from duck_lab.nav.sim_camera import SimCamera
from duck_lab.profile import load as load_profile
from simhost.truth import Body


class CameraServer:
    def __init__(self, host, path: Path, variant: str = "sim", seed: int | None = None, camera: SimCamera | None = None):
        if host.truth_port is None:
            raise ValueError(f"{host.source}: this host has no truth (truth_port is null): no simulated camera")
        self.path = Path(path)
        self.camera = camera or SimCamera(config=load_profile(variant).get("sensors.camera", {}), seed=seed)
        self.port = host.truth_port
        self._body = None
        self._lock = threading.Lock()        # one truth read, and the camera's random draws, at a time
        self._server = None
        self.looks = 0

    def call(self, method: str, p: dict):
        if method == "camera.info":
            return {k: self.camera.cfg[k] for k in ("hfov_deg", "range_m", "period_s")}
        if method == "camera.detect":
            with self._lock:
                pose = self._truth()
                found = self.camera.detect(pose)
                self.looks += 1
            return {"wall_ns": time.time_ns(), "detections": [asdict(d) for d in found]}
        raise KeyError(method)

    def _truth(self) -> tuple:
        """The duck's true pose; the body server connected again once when it went away (a reset restarts it)."""
        for attempt in (1, 2):
            try:
                if self._body is None:
                    self._body = Body(self.port)
                return self._body.read()[0]
            except (OSError, ValueError):
                if self._body is not None:
                    try:
                        self._body.close()
                    except OSError:
                        pass
                self._body = None
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    def start(self) -> "CameraServer":
        self._body = Body(self.port)
        self.path.unlink(missing_ok=True)
        server = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                for line in self.rfile:
                    try:
                        req = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    try:
                        out = {"jsonrpc": "2.0", "id": req.get("id"), "result": server.call(req.get("method"), req.get("params") or {})}
                    except KeyError as e:
                        out = {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": f"no method {e}"}}
                    except Exception as e:      # noqa: BLE001 - every error is the caller's answer
                        out = {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32000, "message": f"{type(e).__name__}: {e}"}}
                    try:
                        self.wfile.write((json.dumps(out) + "\n").encode())
                        self.wfile.flush()
                    except OSError:
                        return

        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True

        self._server = Server(str(self.path), Handler)
        threading.Thread(target=self._server.serve_forever, name="camera-server", daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._body is not None:
            try:
                self._body.close()
            except OSError:
                pass
            self._body = None
        self.path.unlink(missing_ok=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
