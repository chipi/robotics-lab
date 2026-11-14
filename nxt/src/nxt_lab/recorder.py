"""Samples motors and sensors at a fixed rate: a live ring buffer for the UI, and CSV files while recording."""

import collections
import csv
import threading
import time
from datetime import datetime
from pathlib import Path

from nxt_lab import deadman
from nxt_lab.config import DATA_DIR

RUNS_DIR = DATA_DIR / "runs"
PROGRAM_CHECK_SECONDS = 1.0


class Recorder:
    def __init__(self, controller, runs_dir: Path = RUNS_DIR):
        self.controller = controller
        self.runs_dir = runs_dir
        self.samples = collections.deque(maxlen=1200)
        self.seq = 0
        self.program = None
        self.recording = None
        self._file = None
        self._writer = None
        self._columns = []
        self._t0 = time.monotonic()
        self._lock = threading.Lock()
        self._last_program_check = 0.0

    def run_forever(self) -> None:
        while True:
            started = time.monotonic()
            try:
                self.sample_once()
            except Exception:
                pass
            period = 1.0 / self.controller.config.sample_hz
            time.sleep(max(0.0, period - (time.monotonic() - started)))

    def sample_once(self) -> None:
        robot = self.controller.robot
        if robot is None:
            self.program = None
            return
        now = time.monotonic()
        if now - self._last_program_check >= PROGRAM_CHECK_SECONDS:
            program = self.controller.call(lambda r: r.current_program())
            changed, self.program = program != self.program, program
            self._last_program_check = now
            if changed:
                self.controller.sync_deadman()
        tachos = self.controller.call(lambda r: r.read_tachos())
        # Reading a sensor can change its mode, which would disturb a program running on the brick.
        # robotd-lite is the exception: it leaves the other ports alone and reports its distance.
        paused = self.program and self.program != deadman.PROGRAM
        sensors = {} if paused else self.controller.call(lambda r: r.read_sensors())
        with self._lock:
            self.seq += 1
            sample = {
                "seq": self.seq,
                "t": round(now - self._t0, 3),
                "left": robot.left,
                "right": robot.right,
                "tacho": tachos,
                "sensors": sensors,
                "program": self.program,
            }
            self.samples.append(sample)
            if self.recording is not None:
                self._write_row(sample, now)

    def since(self, seq: int) -> list:
        with self._lock:
            return [s for s in self.samples if s["seq"] > seq]

    def start(self) -> dict:
        with self._lock:
            if self.recording is not None:
                return self.recording
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            name = datetime.now().strftime("run-%Y%m%d-%H%M%S.csv")
            sensors = self.controller.config.sensors
            self._columns = [(port, kind) for port, kind in sorted(sensors.items()) if kind != "none"]
            header = ["t", "power_left", "power_right", "tacho_A", "tacho_B", "tacho_C"]
            for port, kind in self._columns:
                header.append(f"s{port}_{kind}")
                if kind == "color":
                    header.append(f"s{port}_color_name")
            header.append("program")
            self._file = open(self.runs_dir / name, "w", newline="")
            self._writer = csv.writer(self._file)
            self._writer.writerow(header)
            self.recording = {"name": name, "rows": 0, "started": time.monotonic()}
            return self.recording

    def stop(self) -> dict | None:
        with self._lock:
            done = self.recording
            if self._file is not None:
                self._file.close()
            self._file = self._writer = None
            self.recording = None
            return done

    def _write_row(self, sample: dict, now: float) -> None:
        tacho = sample["tacho"]
        row = [
            round(now - self.recording["started"], 3),
            sample["left"],
            sample["right"],
            tacho.get("A"),
            tacho.get("B"),
            tacho.get("C"),
        ]
        for port, kind in self._columns:
            reading = sample["sensors"].get(port, {})
            row.append(reading.get("value"))
            if kind == "color":
                row.append(reading.get("label"))
        row.append(sample["program"] or "")
        self._writer.writerow(row)
        self._file.flush()
        self.recording["rows"] += 1

    def list_runs(self) -> list:
        if not self.runs_dir.exists():
            return []
        return [
            {"name": p.name, "size": p.stat().st_size}
            for p in sorted(self.runs_dir.glob("run-*.csv"), reverse=True)
        ]

    def run_path(self, name: str) -> Path:
        path = (self.runs_dir / name).resolve()
        if path.parent != self.runs_dir.resolve() or not path.name.endswith(".csv") or not path.exists():
            raise FileNotFoundError(name)
        return path
