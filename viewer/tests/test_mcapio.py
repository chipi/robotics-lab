"""Runs as MCAP: written, read back the same, followed while growing. Run: cd viewer && uv run python tests/test_mcapio.py"""

import sys
import tempfile
from pathlib import Path

from mcap.reader import make_reader

from miniview.mcapio import Follower, Recorder, read, write
from miniview.store import build

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


RECS = [
    (0.0, "run", {"id": "r1", "scene": "s", "kind": "exploration", "robot": {"name": "duck"}}),
    (0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]}),
    (1.0, "tick", {"belief": [0.0, 0.0, 0.0], "truth": [1.0, 0.0, 0.0], "tilt": None, "cmd": [0.3, 0.0],
                   "depth": [[0.4, 0.0, 0.0, "f"]]}),
    (1.05, "plan", {"path": [[0.0, 0.0], [1.0, 0.0]]}),
    (1.1, "tick", {"belief": [0.03, 0.0, 0.0], "truth": [1.03, 0.0, 0.0], "tilt": [1.0, 0.0], "cmd": [0.3, 0.0],
                   "depth": None}),
    (2.0, "event", {"kind": "trapped", "text": "trapped"}),
    (2.0, "end", {"verdict": "trapped"}),
]

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "run.mcap"
    write(p, RECS)
    back = read(p)
    check("records read back as written (times to the nanosecond)",
          [(round(t, 6), k, v) for t, k, v in back] == RECS, back[:2])
    with open(p, "rb") as fh:
        n = sum(1 for _ in make_reader(fh).iter_messages())
    check("a standard MCAP reader opens it", n == len(RECS), n)
    d = build(back)
    check("the run builds from it", d.run["status"] == "ended" and d.run["verdict"] == "trapped" and d.run["ticks"] == 2
          and d.frames["plan_at"] == [-1, 0] and d.run["t0"] == 1.0 and d.run["t1"] == 2.0,
          {k: d.run[k] for k in ("status", "verdict", "ticks", "t0", "t1")})

    # Live: a reader follows the file while the writer appends.
    q = Path(tmp) / "live.mcap"
    rec = Recorder(q)
    f = Follower(q)
    check("an empty run file reads as nothing yet", f.poll() == [])
    rec.add(*RECS[0])
    rec.add(*RECS[2])
    rec.flush()
    first = f.poll()
    check("records appear as soon as they are written", [k for _, k, _ in first] == ["run", "tick"], first)
    check("a second poll with nothing new returns nothing", f.poll() == [])
    with open(q, "ab") as fh:            # half a record on disk: the writer was interrupted mid-write
        fh.write(b"\x05\x40\x00")
    check("a half-written record is not read", f.poll() == [])
    with open(q, "r+b") as fh:
        fh.truncate(q.stat().st_size - 3)
    rec.add(*RECS[5])
    rec.close()
    rest = f.poll()
    check("the rest, then the footer ends the follow", [k for _, k, _ in rest] == ["event"] and f.done, (rest, f.done))

print("MCAPIO", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
