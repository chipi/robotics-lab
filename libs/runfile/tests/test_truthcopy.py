"""The truth added by the runner (RFC-0021 step 2, runfile.truthcopy): a run written without truth and copied with the truth
put in by wall-clock time is the run the same rows make with the truth in them (today's path), record by record; live
(copied while it is written) and finished; one goal, and an evaluation (a reset and an epoch per goal); ticks with no
truth sample near them keep none and are counted; the payload's end is replaced by the runner's verdict; the truth log
reads back from its file (the offline case). No simulator.
Run: cd apps/observatory && uv run python tests/test_truthcopy.py"""

import atexit
import math
import shutil
import tempfile
from pathlib import Path

from helpers import Checks
from runfile import keys, mcapio
from runfile.adapters.duck import ROBOT, DuckLog
from runfile.truthcopy import TruthCopy, TruthLog

check = Checks("TRUTHCOPY")
tmp = Path(tempfile.mkdtemp(prefix="truthcopy-"))
atexit.register(shutil.rmtree, tmp, True)
T0 = 1_795_000_000 * 10**9
NOWHERE = Path("/nonexistent/duck-run")


def rows_of(goals: int, per_goal: int = 6) -> list:
    """The navigator's rows: ticks with the truth (pose, height, orientation) and the wall clock, a plan event, and each
    goal's end; an evaluation's second goal starts on a reset simulator, so its map and its map <- world are new."""
    out, t, wall = [], 0.0, T0 + 5_000_000_000
    for g in range(1, goals + 1):
        off = (0.3 * g, -0.2 * g, 0.1 * g)          # each goal's map <- world (a new map after the reset)
        for i in range(per_goal):
            t, wall = t + 0.1, wall + 100_000_000
            tx, ty, tyaw = 0.05 * i, 0.01 * i, 0.02 * i
            c, s = math.cos(off[2]), math.sin(off[2])
            pose = [round(off[0] + c * tx - s * ty, 4), round(off[1] + s * tx + c * ty, 4), round(off[2] + tyaw, 4)]
            r = {"pose": pose, "vx": 0.2, "vyaw": 0.0, "tilt": [0.5, -0.2], "nearest_mm": 500 - i, "t": round(t, 3),
                 "wall_ns": wall, "truth": [round(tx, 4), round(ty, 4), round(tyaw, 4)], "truth_z": 0.1161,
                 "truth_quat": [0.999, 0.001, -0.002, round(0.01 * i, 6)]}
            out.append(r)
            if i == 1:
                t, wall = t + 0.05, wall + 50_000_000
                out.append({"event": "plan", "pose": pose, "goal": [1.0, 0.5], "path": [[0, 0], [1.0, 0.5]],
                            "t": round(t, 3), "wall_ns": wall})
        t, wall = t + 0.05, wall + 50_000_000
        out.append({"event": "reached", "goal": [1.0 * g, 0.5], "pose": out[-1]["pose"], "t": round(t, 3), "wall_ns": wall})
    return out


def without_truth(rows: list) -> list:
    return [{k: v for k, v in r.items() if k not in ("truth", "truth_z", "truth_quat")} for r in rows]


def truth_log(rows: list, path: Path | None = None) -> TruthLog:
    log = TruthLog(path)
    for r in rows:
        if "truth" in r:
            log.add(r["wall_ns"], r["truth"], r["truth_z"], r["truth_quat"])
    return log


class Writer:
    """What duck_lab's RunLog does with a row (DuckLog's records into a Recorder), without the navigator's threads."""

    def __init__(self, data: Path, name: str, evaluation: bool):
        key = keys.make_key("duck", "room", name)
        self.key, self.dir = key, keys.run_dir(data, key)
        self.rec = mcapio.Recorder(self.dir, mcapio.new_run(key, dict(ROBOT), "room", "challenge", T0, "writer"))
        self.log = DuckLog(NOWHERE, "room")
        self.log.start, self.log.header, self.log.fresh = None, [], True
        self.log.reset_per_goal = evaluation

    def row(self, r: dict) -> None:
        for rec in self.log.feed_row(r):
            self.rec.add(*rec)

    def close(self) -> Path:
        for rec in self.log.finish():
            self.rec.add(*rec)
        return self.rec.close()


def write(data: Path, name: str, rows: list, evaluation: bool) -> Path:
    w = Writer(data, name, evaluation)
    for r in rows:
        w.row(r)
    w.close()
    return w.dir


def comparable(run_dir: Path) -> list:
    """The run's records, the run record's own identity (key, uuid) aside."""
    out = []
    for t, kind, p in mcapio.read(run_dir, keep_raw=True):
        if kind == "run":
            p = {k: v for k, v in p.items() if k not in ("key", "uuid")}
        out.append((round(t, 6), kind, p))
    return out


def diff(a: list, b: list) -> str:
    if len(a) != len(b):
        return f"{len(a)} records against {len(b)}: kinds {[k for _, k, _ in a][:12]} / {[k for _, k, _ in b][:12]}"
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"record {i}: {x} != {y}"
    return ""


for evaluation, goals in ((False, 1), (True, 2)):
    name = "evaluation" if evaluation else "one goal"
    rows = rows_of(goals)
    data = tmp / ("eval" if evaluation else "one")
    golden = write(data / "golden", "g", rows, evaluation)                      # today: the truth in the rows
    payload = write(data / "payload", "p", without_truth(rows), evaluation)     # the payload: no truth
    key = keys.make_key("duck", "room", "official")
    copy = TruthCopy(payload, keys.run_dir(data / "official", key), key, truth_log(rows).nearest, reset_per_goal=evaluation)
    copy.finish()
    a, b = comparable(golden), comparable(keys.run_dir(data / "official", key))
    check(f"{name}: the copied run is today's run, record by record (ticks with truth and 3D, epochs, segments, events, end)",
          not diff(a, b), diff(a, b))
    check(f"{name}: every tick paired, the gap 0 ms", copy.stats() == {"ticks": 6 * goals, "paired": 6 * goals, "unpaired": 0,
                                                                        "max_gap_ms": 0.0}, copy.stats())
    epochs = [p["map_to_world"] for _, k, p in b if k == "epoch"]
    check(f"{name}: one map <- world epoch per goal", len(epochs) == goals, epochs)
    check(f"{name}: the payload's own run has no truth and no epoch",
          not any(k == "epoch" or (k == "tick" and p.get("truth")) for _, k, p in comparable(payload)))

# Live: copied while the payload writes it, a pump between rows; the same run as copying it once it is finished.
rows = rows_of(1)
data = tmp / "live"
golden = write(data / "golden", "g", rows, False)
w = Writer(data / "payload", "p", False)
key = keys.make_key("duck", "room", "official")
copy = TruthCopy(w.dir, keys.run_dir(data / "official", key), key, truth_log(rows).nearest)
copied = []
for r in without_truth(rows):
    w.row(r)
    copied.append(copy.pump())
w.close()
copy.finish()
a, b = comparable(golden), comparable(keys.run_dir(data / "official", key))
check("live: copied a row at a time while the payload writes, the same run", not diff(a, b), diff(a, b))
check("live: records were copied as they came, not all at the end", sum(1 for n in copied if n) >= len(rows) - 2, copied)

# A tick whose wall clock has no sample within 0.1 s keeps no truth, and is counted; the others are paired as before.
rows = rows_of(1)
log = truth_log([r for r in rows if not (r.get("truth") and r["wall_ns"] == rows[3]["wall_ns"])])
data = tmp / "gap"
payload = write(data / "payload", "p", without_truth(rows), False)
key = keys.make_key("duck", "room", "official")
copy = TruthCopy(payload, keys.run_dir(data / "official", key), key, lambda ns, gap: log.nearest(ns, 40_000_000))
copy.finish()
ticks = [p for _, k, p in comparable(keys.run_dir(data / "official", key)) if k == "tick"]
check("a tick with no sample within the gap keeps no truth; the others have theirs",
      [bool(p.get("truth")) for p in ticks] == [True, True, False, True, True, True], [p.get("truth") for p in ticks])
check("... and it is counted", copy.stats()["unpaired"] == 1 and copy.stats()["paired"] == 5, copy.stats())

# The runner's verdict replaces the payload's end; its own records go in at the run's time.
rows = rows_of(1)
data = tmp / "verdict"
payload = write(data / "payload", "p", without_truth(rows), False)
key = keys.make_key("duck", "room", "official")
copy = TruthCopy(payload, keys.run_dir(data / "official", key), key, truth_log(rows).nearest)
copy.pump()
copy.add(0.0, "event", {"kind": "judged", "text": "PASS", "notable": True})
copy.finish("passed")
recs = comparable(keys.run_dir(data / "official", key))
check("the runner's event is written at the run's last time, not back in time",
      [k for _, k, _ in recs][-2:] == ["event", "end"] and recs[-2][0] == recs[-3][0], recs[-3:])
check("the end is the runner's verdict", recs[-1][2]["verdict"] == "passed", recs[-1])

# Offline: the truth log written while sampling, read back, gives the same run.
rows = rows_of(1)
data = tmp / "offline"
golden = write(data / "golden", "g", rows, False)
payload = write(data / "payload", "p", without_truth(rows), False)
truth_log(rows, data / "truth.jsonl").close()
key = keys.make_key("duck", "room", "official")
TruthCopy(payload, keys.run_dir(data / "official", key), key, TruthLog.load(data / "truth.jsonl").nearest).finish()
a, b = comparable(golden), comparable(keys.run_dir(data / "official", key))
check("offline: the truth log read back from its file gives the same run", not diff(a, b), diff(a, b))

log = TruthLog()
log.add(100, [0, 0, 0])
try:
    log.add(99, [0, 0, 0])
    went_back = False
except ValueError:
    went_back = True
check("a truth sample before the last one is refused", went_back)
check("nearest: within the gap, else None", log.nearest(150, 60)["wall_ns"] == 100 and log.nearest(300, 60) is None)

# An evaluation through the split: a reset simulator and a new payload per goal, so one payload run per goal (its own times
# from 0, its own map), copied one after the other into one official run (next_source).
two = rows_of(2)
cut = next(i for i, r in enumerate(two) if r.get("event") == "reached") + 1
goal1, goal2 = two[:cut], [dict(r, t=round(r["t"] - two[cut]["t"] + 0.1, 3)) for r in two[cut:]]   # goal 2 from t 0.1
data = tmp / "multi"
src1 = write(data / "p1", "p1", without_truth(goal1), False)
src2 = write(data / "p2", "p2", without_truth(goal2), False)
key = keys.make_key("duck", "room", "official")
copy = TruthCopy(src1, keys.run_dir(data / "official", key), key, truth_log(two).nearest)
copy.pump()
copy.next_source(src2)
copy.finish("passed")
recs = comparable(keys.run_dir(data / "official", key))
times = [t for t, _, _ in recs]
first2 = next(i for i, (_, k, p) in enumerate(recs) if k == "epoch" and i > 1)
check("two goals' runs into one: time never goes back", times == sorted(times), times[:5])
check("... the second goal starts a second after the first ends", abs(recs[first2][0] - (recs[first2 - 1][0] + 1.0 + 0.1)) < 1e-6,
      (recs[first2 - 1][0], recs[first2][0]))
epochs = [p["map_to_world"] for _, k, p in recs if k == "epoch"]
golden_epochs = [p["map_to_world"] for _, k, p in comparable(write(data / "golden", "g", two, True)) if k == "epoch"]
check("... one map <- world epoch per goal, each that goal's own (the same as today's evaluation run)",
      epochs == golden_epochs and len(epochs) == 2, (epochs, golden_epochs))
ticks = [p for _, k, p in recs if k == "tick"]
check("... every tick of both goals has its truth", len(ticks) == 12 and all(p.get("truth") for p in ticks), copy.stats())
segs = [(p["index"], p["t_start"], p["t_end"]) for _, k, p in recs if k == "segment"]
check("... segments numbered on from the first run's, each inside its own goal's time",
      [s[0] for s in segs] == list(range(len(segs))) and all(a <= b for _, a, b in segs)
      and segs[-1][1] >= recs[first2][0] - 1e-6, segs)
check("... the runner's verdict ends it", recs[-1][1] == "end" and recs[-1][2]["verdict"] == "passed")

# A payload's run goes on a moment after its goal (what it logs while it stops): a short segment of its own, no goal in it.
# One per goal would double the goals' segments; the one before a next goal is dropped, the run's very last one kept.
after = dict(goal1[-2], t=round(goal1[-1]["t"] + 0.05, 3), wall_ns=goal1[-1]["wall_ns"] + 50_000_000)
data = tmp / "trailing"
src1 = write(data / "p1", "p1", without_truth(goal1 + [after]), False)
src2 = write(data / "p2", "p2", without_truth(goal2 + [dict(after, t=round(goal2[-1]["t"] + 0.05, 3))]), False)
own = [p.get("outcome") for _, k, p in comparable(src1) if k == "segment"]
key = keys.make_key("duck", "room", "official")
copy = TruthCopy(src1, keys.run_dir(data / "official", key), key, truth_log(goal1 + [after] + two[cut:]).nearest)
copy.pump()
copy.next_source(src2)
copy.finish()
segs = [(p["index"], p.get("outcome")) for _, k, p in comparable(keys.run_dir(data / "official", key)) if k == "segment"]
check("a payload's run has its goal's segment and a trailing one with no goal", own == ["reached", None], own)
check("... copied with a next goal after it: its trailing one dropped, the last run's kept, numbered in order",
      segs == [(0, "reached"), (1, "reached"), (2, None)], segs)

check.done()
