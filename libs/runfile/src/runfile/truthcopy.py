"""The truth added to a run by the process that has it (RFC-0021 step 2): a payload writes its run without the simulator's
truth, and the runner, which reads the truth itself, writes the official run. A format 2 tick holds its truth inside it
(wire.TICK_PARTS) and a run has one writer (mcapio.Recorder's lock), so the runner does not add to the payload's run: it
follows it (mcapio.Follower, live or finished) and copies every record into a run of its own, putting into each tick the
truth sample nearest it in wall-clock time (the row's `wall_ns`, kept in the tick's raw), and writing the map <- world
epoch the payload's writer could not (adapters/duck.py writes it from the first tick with a truth; so does this).

    log = TruthLog()                     # filled by the runner's sampler: log.add(wall_ns, [x, y, yaw], z, quat)
    copy = TruthCopy(payload_run_dir, official_run_dir, key, log.nearest)
    while running: copy.pump()           # live: the Observatory follows the official run, truth about a poll late
    copy.add(copy.last_t, "event", {...})  # the runner's own records (the verdict)
    copy.finish("passed")

A tick with no sample within `max_gap_ns` keeps no truth and is counted (`unpaired`): the Observatory draws a tick with no
truth as it does on a real robot. The payload's own `end` is not copied (its writer cannot know the course's verdict);
`finish` writes the runner's. Nothing here knows a robot or a simulator: a truth is a pose by wall-clock time."""

import bisect
import json
import uuid
from pathlib import Path

from runfile.mcapio import Follower, Recorder
from runfile.se2 import compose, inverse

MAX_GAP_NS = 100_000_000       # a sample farther than this from a tick is not that tick's truth (0.1 s: 2 cm at 0.2 m/s)


class TruthLog:
    """The truth samples, (wall_ns, pose [x, y, yaw], z, quat [w, x, y, z]) in wall-clock order, looked up by nearest."""

    def __init__(self, path: Path | None = None):
        self.ns, self.samples = [], []
        self._fh = open(path, "a") if path else None      # every sample also as a line of JSON: the audit trail, the offline input

    def add(self, wall_ns: int, pose, z: float | None = None, quat=None) -> None:
        if self.ns and wall_ns < self.ns[-1]:
            raise ValueError(f"truth sample at {wall_ns} before the last one at {self.ns[-1]}")
        s = {"wall_ns": int(wall_ns), "pose": [round(v, 4) for v in pose[:3]],
             "z": None if z is None else round(z, 4), "quat": None if quat is None else [round(v, 6) for v in quat]}
        self.ns.append(s["wall_ns"])
        self.samples.append(s)
        if self._fh:
            self._fh.write(json.dumps(s) + "\n")
            self._fh.flush()

    @classmethod
    def load(cls, path: Path) -> "TruthLog":
        log = cls()
        for line in Path(path).read_text().splitlines():
            if line.strip():
                s = json.loads(line)
                log.add(s["wall_ns"], s["pose"], s.get("z"), s.get("quat"))
        return log

    def nearest(self, wall_ns: int, max_gap_ns: int = MAX_GAP_NS) -> dict | None:
        i = bisect.bisect_left(self.ns, wall_ns)
        best = min((j for j in (i - 1, i) if 0 <= j < len(self.ns)), key=lambda j: abs(self.ns[j] - wall_ns), default=None)
        if best is None or abs(self.ns[best] - wall_ns) > max_gap_ns:
            return None
        return self.samples[best]

    def close(self) -> None:
        if self._fh:
            self._fh.close()


class TruthCopy:
    def __init__(self, src_dir: Path, dst_dir: Path, key: str, truth, reset_per_goal: bool = False,
                 max_gap_ns: int = MAX_GAP_NS):
        """`truth(wall_ns, max_gap_ns)` -> a TruthLog sample or None. `reset_per_goal`: every goal starts on a reset simulator
        with its own map (an evaluation), so each segment's first tick with a truth gets its own epoch, as DuckLog does."""
        self.src, self.dst, self.key, self.truth = Path(src_dir), Path(dst_dir), key, truth
        self.reset_per_goal, self.max_gap_ns = reset_per_goal, max_gap_ns
        self.follower = Follower(self.src, keep_raw=True)
        self.rec = None
        self.fresh = True            # the next tick with a truth opens a map <- world epoch
        self.src_end = None          # the payload's own end record, not copied
        self.ticks = self.paired = self.unpaired = 0
        self.max_gap_seen_ns = 0

    @property
    def last_t(self) -> float:
        return self.rec.last_t if self.rec else 0.0

    def pump(self) -> int:
        """Copy what the payload has written since the last call; the number of records copied."""
        n = 0
        for t, kind, p in self.follower.poll():
            if kind == "run":
                if self.rec is not None:
                    raise ValueError(f"{self.src}: a second run record")
                self.rec = Recorder(self.dst, dict(p, key=self.key, uuid=str(uuid.uuid4())))
                continue
            if self.rec is None:
                raise ValueError(f"{self.src}: a {kind} record before the run record")
            if kind == "end":
                self.src_end = p
                continue
            if kind == "tick":
                self._pair(t, p)
            self.rec.add(t, kind, p)
            n += 1
            if kind == "segment" and self.reset_per_goal:
                self.fresh = True
        errors = self.follower.take_errors()
        if errors:
            raise ValueError(f"{self.src}: records that are not what they say: {errors[:3]}")
        return n

    def _pair(self, t: float, p: dict) -> None:
        self.ticks += 1
        wall = (p.get("raw") or {}).get("wall_ns")
        s = self.truth(wall, self.max_gap_ns) if isinstance(wall, int) else None
        if s is None:
            self.unpaired += 1
            return
        self.paired += 1
        self.max_gap_seen_ns = max(self.max_gap_seen_ns, abs(s["wall_ns"] - wall))
        p["truth"] = list(s["pose"])
        if s.get("z") is not None and s.get("quat") is not None:
            p["truth_3d"] = {"z": s["z"], "quat": list(s["quat"])}
        if self.fresh:
            m2w = compose(tuple(p["truth"]), inverse(tuple(p["belief"])))
            self.rec.add(t, "epoch", {"map_to_world": [round(v, 5) for v in m2w]})
            self.fresh = False

    def add(self, t: float, kind: str, payload: dict) -> None:
        """The runner's own record (an invariant, the verdict), at `t` or the run's last time if that is later."""
        self.rec.add(max(t, self.rec.last_t), kind, payload)

    def finish(self, verdict: str | None = None) -> Path:
        """What the payload wrote last, then the end (the runner's verdict, else the payload's), then the run compacted."""
        self.pump()
        if self.rec is None:
            raise ValueError(f"{self.src}: no run to copy")
        end = dict(self.src_end or {"verdict": "ended"})
        if verdict is not None:
            end["verdict"] = verdict
        self.rec.add(self.rec.last_t, "end", end)
        return self.rec.close()

    def stats(self) -> dict:
        return {"ticks": self.ticks, "paired": self.paired, "unpaired": self.unpaired,
                "max_gap_ms": round(self.max_gap_seen_ns / 1e6, 1)}
