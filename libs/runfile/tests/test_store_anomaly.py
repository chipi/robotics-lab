"""A run keeps what the robot recorded about an anomaly (RFC-0019 §4.1): an `anomaly` event carries the navigator's record (its severity,
summary, where in the map frame, the simulator's truth in the world frame), the other events are as they were, and the run has an
`anomalies` stream that counts them. Run: cd libs/runfile && uv run python tests/test_store_anomaly.py"""

import atexit
import shutil
import tempfile
from pathlib import Path

from runfile import keys, mcapio
from runfile.adapters.duck import ROBOT
from runfile.store import anomaly_of, build

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="store-anomaly-"))
atexit.register(shutil.rmtree, tmp, True)

RECORD = {"event": "anomaly", "anomaly": "pose_jump", "source": "robot", "module": "mapd", "severity": "major", "detector": "jump", "version": 1,
          "summary": "the pose moved 0.9 m between two ticks", "values": {"jump_m": 0.9, "margin_unit": "m"}, "margin": 0.6,
          "where": {"frame": "map", "belief": [1.2, -0.4], "mapd": [2.1, -0.4]}, "evidence": {"events": ["glance@12.0"]}, "related": [],
          "duration_s": 0.5, "truth": [1.4, -0.3, 0.2]}
ANOMALY = {"kind": "anomaly", "text": "anomaly pose_jump (major): the pose moved 0.9 m between two ticks", "notable": True, "t_src": 12.0, "raw": RECORD}
OTHER = {"kind": "tight_pivot", "text": "tight_pivot room_m 0.156", "notable": True, "t_src": 11.0, "raw": {"room_m": 0.156, "severity": "none"}}

key = keys.make_key("duck", "apartment", "anom")
path = mcapio.write(keys.run_dir(tmp, key), mcapio.new_run(key, dict(ROBOT), "apartment", "exploration", 1_000_000_000),
                    [(11.0, "event", OTHER), (12.0, "event", ANOMALY), (13.0, "end", {"verdict": "reached"})])
run = build(mcapio.read(path.parent)).run
by_kind = {e["kind"]: e for e in run["events"]}

# must fail: a store that drops the navigator's record leaves the pages nothing to show
a = by_kind["anomaly"].get("anomaly", {})
check("must fail: an anomaly event keeps its severity, summary, where and truth",
      a.get("severity") == "major" and a.get("summary") == RECORD["summary"] and a.get("where") == RECORD["where"] and a.get("truth") == RECORD["truth"], a)
check("it keeps the rest of the record too: the anomaly's name, source, module, detector, margin, values, duration",
      {k: a.get(k) for k in ("anomaly", "source", "module", "detector", "margin", "values", "duration_s")}
      == {k: RECORD[k] for k in ("anomaly", "source", "module", "detector", "margin", "values", "duration_s")}, a)
check("and not the event's own name, which is `kind`", "event" not in a, a)
check("other events are unchanged: no `anomaly` key, and what an event had is still there",
      "anomaly" not in by_kind["tight_pivot"] and by_kind["tight_pivot"] == {"t": 11.0, "kind": "tight_pivot", "text": OTHER["text"]}, by_kind["tight_pivot"])
check("the anomaly event still has its time, kind and text", (by_kind["anomaly"]["t"], by_kind["anomaly"]["text"]) == (12.0, ANOMALY["text"]), by_kind["anomaly"])
streams = {s["id"]: s for s in run["streams"]}
check("the run's `anomalies` stream counts the anomalies, and is not missing", streams["anomalies"]["count"] == 1 and not streams["anomalies"]["missing"], streams["anomalies"])

bare = {"kind": "anomaly", "text": "anomaly x", "notable": True, "t_src": 1.0, "raw": {"event": "anomaly", "anomaly": "x", "severity": "info", "summary": "s"}}
key2 = keys.make_key("duck", "apartment", "bare")
p2 = mcapio.write(keys.run_dir(tmp, key2), mcapio.new_run(key2, dict(ROBOT), "apartment", "exploration", 1_000_000_000),
                  [(1.0, "event", bare), (2.0, "end", {"verdict": "reached"})])
run2 = build(mcapio.read(p2.parent)).run
check("a record with no `where` or `truth` (a real robot) keeps only the fields it has", run2["events"][0]["anomaly"] == {"anomaly": "x", "severity": "info", "summary": "s"}, run2["events"][0])
check("a run with no anomaly has an `anomalies` stream that is missing", {s["id"]: s for s in build(mcapio.read(mcapio.write(
    keys.run_dir(tmp, keys.make_key("duck", "apartment", "none")), mcapio.new_run(keys.make_key("duck", "apartment", "none"), dict(ROBOT), "apartment",
                                                                                   "exploration", 1_000_000_000),
    [(1.0, "event", OTHER), (2.0, "end", {"verdict": "reached"})]).parent)).run["streams"]}["anomalies"]["missing"])
check("anomaly_of(None) is empty", anomaly_of(None) == {})

print()
print("STORE ANOMALY", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
