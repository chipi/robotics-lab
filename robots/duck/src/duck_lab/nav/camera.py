"""The navigator's camera: a recogniser on a socket (RFC-0021 step 6). In the simulator the host serves it
(duck_lab.camera_server); on a real duck it would be the camera's detector. Either way the navigator gets Detections
relative to the duck and nothing of the world."""

from __future__ import annotations

from pathlib import Path

from duck_lab.nav.client import Rpc
from worldmodel.semantic_map import Detection


class CameraClient:
    def __init__(self, path: Path, timeout: float = 5.0):
        self._rpc = Rpc(Path(path), timeout=timeout)
        self.cfg = self._rpc.call("camera.info")         # hfov_deg, range_m, period_s

    def detect(self) -> list:
        return [Detection(**d) for d in self._rpc.call("camera.detect")["detections"]]

    def close(self) -> None:
        self._rpc.close()
