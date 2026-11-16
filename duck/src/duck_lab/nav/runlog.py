"""The navigator's run as a miniview run, written while it runs (ADR-0014, RFC-0008 step 0).

`RunLog` turns what the navigator logs into format 2 records through miniview's `Recorder`: a row of ticks.jsonl
becomes the same records the importer would make (`miniview.adapters.duck.DuckLog`, so a run written live and the
same log imported later are the same run), and the things ticks.jsonl has no place for are added: every depth frame
(raw, with the state it was paired with and what was derived) and the IMU and decision values as signals.
ticks.jsonl is still written by the navigator; the format 2 run is the record.

Three threads write (the navigator's loop, the state stream, the depth stream), so every write is under one lock, and
a record from a thread's navigator that is no longer the current one (an evaluation starts a new navigator per goal) is
dropped. A failure to write costs the run, never the navigation: it is said once on stderr and the log goes quiet.
"""

import os
import sys
import threading
import time
from pathlib import Path

from miniview import keys
from miniview.adapters.duck import DuckLog, ROBOT
from miniview.mcapio import Recorder, WriterBusy, new_run

# The robot's named values (ADR-0013's generic signals; ADR-0014): the IMU per state sample, and what the navigator
# decides on as it last had it, in the same sample.
SIGNALS = [
    {"name": "pitch_deg", "kind": "number", "unit": "deg"},
    {"name": "roll_deg", "kind": "number", "unit": "deg"},
    {"name": "pitch_rate_dps", "kind": "number", "unit": "deg/s"},
    {"name": "qw", "kind": "number"}, {"name": "qx", "kind": "number"},
    {"name": "qy", "kind": "number"}, {"name": "qz", "kind": "number"},
    {"name": "nearest_mm", "kind": "number", "unit": "mm"},
    {"name": "block_m", "kind": "number", "unit": "m"},
    {"name": "room_m", "kind": "number", "unit": "m"},
    {"name": "turning", "kind": "number"},
]
NOWHERE = Path("/nonexistent/duck-run")        # no folder of a log: nothing to read start.json or results.json from


class RunLog:
    def __init__(self, data: Path, scene: str, name: str, kind: str, out_dir: Path | None = None, evaluation: bool = False,
                 started_at_ns: int | None = None):
        """Opens the run `duck/<scene>/<name>` in the data folder (WriterBusy if it exists or has a writer, ValueError for a key
        that is not one). `out_dir` is the navigator's own output folder (its results.json says the run was an evaluation's);
        `evaluation`: every goal starts on a reset simulator, with its own map, so each has its epoch."""
        key = keys.make_key("duck", scene, name)
        run = new_run(key, dict(ROBOT), scene, kind, started_at_ns or time.time_ns(), "writer", signals=SIGNALS,
                      writer={"program": "duck-lab", "version": "0.1.0"})
        self.key = key
        self.dir = keys.run_dir(Path(data), key)
        self._rec = Recorder(self.dir, run)
        self._log = DuckLog(Path(out_dir) if out_dir else NOWHERE, scene)
        self._log.start, self._log.header, self._log.fresh = None, [], True      # this run's own start, from its first pose and truth
        self._log.reset_per_goal = evaluation
        self._lock = threading.Lock()
        self._session = 0
        self._new_session = True              # the current navigator has written nothing yet: its first record opens a segment
        self.error = None
        self.closed = False

    def new_session(self) -> int:
        """A new navigator starts (an evaluation's next goal): what the one before it still sends is dropped."""
        with self._lock:
            self._session += 1
            self._new_session = True
            return self._session

    def _guard(self, sid: int, fn, thread: bool = False) -> None:
        with self._lock:
            if self.closed or self.error or sid != self._session:
                return
            if thread and self._log.reset_per_goal and self._log.boundary and not self._new_session:
                return                         # an evaluation's goal just ended: what its navigator's streams still send is no goal's
            try:
                fn()
                self._new_session = False
            except Exception as e:             # noqa: BLE001 - the navigator must not stop for its log
                self.error = f"{type(e).__name__}: {e}"
                print(f"miniview run {self.key}: not written any more ({self.error}); ticks.jsonl goes on", file=sys.stderr)

    def row(self, sid: int, row: dict) -> None:
        """A row as the navigator writes it to ticks.jsonl (with its time and the simulator's truth)."""
        self._guard(sid, lambda: [self._rec.add(*r) for r in self._log.feed_row(row)])

    def frame(self, sid: int, ts: float, payload: dict) -> None:
        """A depth frame record at the navigator's time `ts` (seconds since it started)."""
        self._guard(sid, lambda: self._rec.add(self._log._time(ts), "depth_frame", dict(payload, t_src=ts)), thread=True)

    def signals(self, sid: int, ts: float, values: dict) -> None:
        if values:
            self._guard(sid, lambda: self._rec.add(self._log._time(ts), "signals", {"values": values}), thread=True)

    def finish(self) -> Path | None:
        """The open segment and the verdict, then the run is compacted. Safe to call twice."""
        with self._lock:
            if self.closed:
                return None
            self.closed = True
            try:
                for t, kind, p in self._log.finish():
                    self._rec.add(t, kind, p)
                return self._rec.close()
            except Exception as e:             # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"
                print(f"miniview run {self.key}: not closed ({self.error}); `miniview repair {self.key}` closes it", file=sys.stderr)
                return None


def add_args(ap) -> None:
    ap.add_argument("--miniview-data", type=Path, default=None,
                    help="the lab's data folder: the run is written there as a miniview run (format 2) while it runs; "
                         "default $MINIVIEW_DATA, else only ticks.jsonl is written")
    ap.add_argument("--scene", default="apartment", help="the miniview run's scene (default apartment)")
    ap.add_argument("--run", help="the miniview run's name (default: the output folder's name)")


def open_from_args(args, default_name: str, kind: str, out_dir: Path | None, evaluation: bool = False) -> RunLog | None:
    """The run log the command line asks for, or None (no data folder given); a run that exists is an exit, not an overwrite."""
    data = args.miniview_data or (Path(os.environ["MINIVIEW_DATA"]) if os.environ.get("MINIVIEW_DATA") else None)
    if data is None:
        print("no miniview data folder (--miniview-data or MINIVIEW_DATA): only ticks.jsonl is written", file=sys.stderr)
        return None
    try:
        rl = RunLog(data, args.scene, args.run or default_name, kind, out_dir, evaluation)
    except (WriterBusy, ValueError) as e:
        raise SystemExit(f"cannot write the miniview run: {e}") from None
    print(f"miniview run {rl.key} -> {rl.dir}", file=sys.stderr)
    return rl
