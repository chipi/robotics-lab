"""Samples motors and sensors at a fixed rate: a live ring buffer for the UI, and per recording a CSV (the Plot view
reads it) and a miniview run (ADR-0013): format 2, written while it is recorded, so it is live in miniview and
compacted when the recording stops."""

import collections
import csv
import hashlib
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from miniview import keys
from miniview.adapters import nxt as nxt_run
from miniview.mcapio import FINAL, Recorder as RunWriter

from nxt_lab import deadman
from nxt_lab.config import DATA_DIR

RUNS_DIR = DATA_DIR / "runs"
PROGRAM_CHECK_SECONDS = 1.0
RUN_NAME = re.compile(r"^run-[0-9]{8}-[0-9]{6}(-[0-9]+)?$")


def default_miniview_data() -> Path:
    """The lab's data folder for the runs of this recorder: $MINIVIEW_DATA, else `miniview/` in nxt-web's own data folder."""
    v = os.environ.get("MINIVIEW_DATA", "").strip()
    return Path(v) if v else DATA_DIR / "miniview"


def data_owner() -> tuple | None:
    """$NXT_DATA_OWNER as (uid, gid): who the runs written into the lab's data folder belong to. The image runs as root (the
    brick's device nodes need it), so without it a host bind mount fills with root's files (ADR-0013)."""
    v = os.environ.get("NXT_DATA_OWNER", "").strip()
    if not v:
        return None
    uid, _, gid = v.partition(":")
    return int(uid), int(gid or uid)


def hand_over(top: Path, path: Path, owner: tuple | None) -> None:
    """Give `owner` what this process created at `path` (everything in it) and in the folders between `top` and it. Only
    paths this process's user owns are changed: a folder that was already someone's stays theirs."""
    if owner is None:
        return
    me = os.geteuid()
    paths = [path, *path.rglob("*")] if path.is_dir() else [path]
    parent = path.parent
    while parent != top and top in parent.parents:
        paths.append(parent)
        parent = parent.parent
    for p in paths:
        try:
            st = p.lstat()
        except FileNotFoundError:
            continue
        if st.st_uid == me and (st.st_uid, st.st_gid) != owner:
            os.chown(p, *owner, follow_symlinks=False)


class Recorder:
    def __init__(self, controller, runs_dir: Path = RUNS_DIR, miniview_data: Path | None = None):
        self.controller = controller
        self.runs_dir = runs_dir
        self.miniview_data = miniview_data or default_miniview_data()
        self.samples = collections.deque(maxlen=1200)
        self.seq = 0
        self.program = None
        self.recording = None
        self._file = None
        self._writer = None
        self._run = None              # the miniview run being written: {"key", "writer", "odom", "error"}
        self._columns = []
        self._header = []
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
                "deadman": robot.deadman_state,
            }
            self.samples.append(sample)
            if self.recording is not None:
                self._write_row(sample, now)

    def since(self, seq: int) -> list:
        with self._lock:
            return [s for s in self.samples if s["seq"] > seq]

    def _free_name(self) -> str:
        """run-YYYYMMDD-HHMMSS, with -2, -3, ... when that name (a CSV, or a miniview run) is already taken."""
        base = datetime.now().strftime("run-%Y%m%d-%H%M%S")
        for n in range(1, 1000):
            name = base if n == 1 else f"{base}-{n}"
            if not (self.runs_dir / f"{name}.csv").exists() and not keys.run_dir(self.miniview_data, f"{nxt_run.ROBOT}/{nxt_run.SCENE}/{name}").exists():
                return name
        raise RuntimeError(f"no free run name after {base}")

    def start(self) -> dict:
        with self._lock:
            if self.recording is not None:
                return self.recording
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            name = self._free_name()
            config = self.controller.config
            sensors = config.sensors
            self._columns = [(port, kind) for port, kind in sorted(sensors.items()) if kind != "none"]
            header = ["t"] + nxt_run.columns_for(sensors)
            self._header = header
            self._file = open(self.runs_dir / f"{name}.csv", "w", newline="")
            self._writer = csv.writer(self._file)
            self._writer.writerow(header)
            self._start_run(name, header[1:], config)
            self.recording = {"name": f"{name}.csv", "rows": 0, "started": time.monotonic()}
            if self._run:
                self.recording["run"] = self._run["key"]
            return self.recording

    def _start_run(self, name: str, columns: list, config) -> None:
        """Open the miniview run beside the CSV. A failure here costs the run, never the recording: the CSV goes on."""
        self._run = None
        try:
            key = f"{nxt_run.ROBOT}/{nxt_run.SCENE}/{name}"
            geometry = nxt_run.geometry_from(config.to_dict(), "config")
            run = nxt_run.run_record(key, time.time_ns(), "writer", {c: nxt_run.kind_of(c) for c in columns}, geometry,
                                     {"name": f"{name}.csv"}, writer={"program": "nxt-web", "version": "0.1.0"})
            writer = RunWriter(keys.run_dir(self.miniview_data, key), run)
            nxt_run.header(writer, geometry)
            self._run = {"key": key, "writer": writer, "odom": nxt_run.Odometry(geometry) if geometry else None, "error": None}
        except Exception as exc:
            self._run = {"key": None, "writer": None, "odom": None, "error": f"{type(exc).__name__}: {exc}"}
            return
        self._hand_over()

    def _hand_over(self) -> None:
        """The run's folder and files to $NXT_DATA_OWNER; a failure is the run's error, never the recording's."""
        try:
            hand_over(self.miniview_data, keys.run_dir(self.miniview_data, self._run["key"]), data_owner())
        except (OSError, ValueError) as exc:
            self._run["error"] = f"owner: {type(exc).__name__}: {exc}"

    def stop(self) -> dict | None:
        with self._lock:
            done = self.recording
            if self._file is not None:
                self._file.close()
                self._finish_run(self.runs_dir / done["name"], done["rows"])
            self._file = self._writer = self._run = None
            self.recording = None
            return done

    def _finish_run(self, csv_path: Path, rows: int) -> None:
        run = self._run
        if not run or not run["writer"]:
            return
        try:
            sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
            run["writer"].add(run["writer"].last_t, "end", {"verdict": "recorded" if rows else "empty", "source_sha256": sha})
            run["writer"].close()
        except Exception as exc:
            run["error"] = f"{type(exc).__name__}: {exc}"           # the live file stays: `miniview repair` closes it
        self._hand_over()                                            # run.mcap is new

    def _run_time(self, now: float) -> float:
        """Run time for a moment: seconds since the recording began, never behind what was already written."""
        return max(round(now - self.recording["started"], 3), self._run["writer"].last_t, 0.0)

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
        run = self._run
        if run and run["writer"]:
            try:
                nxt_run.write_sample(run["writer"], self._run_time(now), dict(zip(self._header[1:], row[1:])), run["odom"], tacho)
            except Exception as exc:
                run["error"] = f"{type(exc).__name__}: {exc}"
                run["writer"] = None                              # the miniview run stops here (its live file stays); the CSV goes on

    def log_event(self, entry: dict) -> None:
        """A command-log entry, into the recording's miniview run while recording."""
        with self._lock:
            run = self._run
            if run and run["writer"]:
                try:
                    run["writer"].add(*nxt_run.event_record(entry, self._run_time(time.monotonic())))
                except Exception as exc:
                    run["error"] = f"{type(exc).__name__}: {exc}"
                    run["writer"] = None

    def run_status(self) -> dict | None:
        """What the page shows of the miniview run of the recording in progress: its key, and an error if writing it failed."""
        run = self._run
        return {"key": run["key"], "error": run["error"]} if run else None

    def _final(self, name: str) -> Path:
        return keys.run_dir(self.miniview_data, f"{nxt_run.ROBOT}/{nxt_run.SCENE}/{Path(name).stem}") / FINAL

    def list_runs(self) -> list:
        if not self.runs_dir.exists():
            return []
        out = []
        for p in sorted(self.runs_dir.glob("run-*.csv"), reverse=True):
            final = self._final(p.name) if RUN_NAME.match(p.stem) else None
            out.append({"name": p.name, "size": p.stat().st_size,
                        "mcap": p.with_suffix(".mcap").name if final and final.exists() else None})
        return out

    def run_path(self, name: str) -> Path:
        """The file a download names: the CSV, or `<run>.mcap`: the finished miniview run of that recording."""
        path = (self.runs_dir / name).resolve()
        if path.parent == self.runs_dir.resolve() and path.suffix == ".csv" and path.exists():
            return path
        if path.parent == self.runs_dir.resolve() and path.suffix == ".mcap" and RUN_NAME.match(path.stem) and self._final(name).exists():
            return self._final(name)
        raise FileNotFoundError(name)
