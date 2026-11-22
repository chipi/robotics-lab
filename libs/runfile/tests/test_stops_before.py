"""A stop recorded before the navigator contract (libs/runner/CONTRACT.md) is shown by its name now (the operator's decision,
2026-11-22): a run's `aborted` event and verdict read back as `stopped_by_guardrail` or `cancelled`, by the stop's recorded
reason, from a run file (runfile.wire, runfile.store) and from a navigator's log (runfile.adapters.duck); a run recorded since
reads as it was written. Run: cd libs/runfile && uv run python tests/test_stops_before.py"""

import atexit
import shutil
import tempfile
from pathlib import Path

from runfile import keys, mcapio
from runfile.adapters.duck import ROBOT, DuckLog
from runfile.navcontract import stop_before
from runfile.store import build

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="stops-before-"))
atexit.register(shutil.rmtree, tmp, True)

# the reasons the Observatory's index holds for its 9 `aborted` events (2026-11-22), and a cancel's
for why, end in (("invariant fall: trunk at 0.041 m, below 0.06 m", "stopped_by_guardrail"),
                 ("truth guard: 0.29 m from the staircase, trunk 0.270 m", "stopped_by_guardrail"),
                 ("guardrail contact: the trunk is 0.07 m from unseen_box", "stopped_by_guardrail"),
                 ("cancelled by Mission Control", "cancelled"), ("Cancelled by the runner", "cancelled"),
                 (None, "stopped_by_guardrail")):
    check(f"an old stop for {why!r} is {end}", stop_before(why) == end, stop_before(why))


def old_run(name: str, why: str) -> Path:
    """A run file as a navigator wrote it before the contract: its stop an `aborted` event, its verdict `aborted`."""
    key = keys.make_key("duck", "apartment", name)
    ev = {"kind": "aborted", "text": f"aborted why {why}", "notable": True, "t_src": 2.0, "raw": {"why": why}}
    return mcapio.write(keys.run_dir(tmp, key), mcapio.new_run(key, dict(ROBOT), "apartment", "exploration", 1_000_000_000),
                        [(2.0, "event", ev), (2.0, "end", {"verdict": "aborted"})])


for name, why, end in (("fall", "invariant fall: trunk at 0.041 m, below 0.06 m", "stopped_by_guardrail"),
                       ("cancel", "cancelled by Mission Control", "cancelled")):
    d = build(mcapio.read(old_run(name, why).parent))
    stops = [e for e in d.run["events"] if e["kind"] in ("aborted", "stopped_by_guardrail", "cancelled")]
    check(f"a run file's old stop ({name}) reads as {end}, its text too", [e["kind"] for e in stops] == [end]
          and stops[0]["text"] == f"{end} why {why}", stops)
    check(f"its verdict reads as {end}", d.run["verdict"] == end, d.run["verdict"])

key = keys.make_key("duck", "apartment", "now")
ev = {"kind": "cancelled", "text": "cancelled why the operator", "notable": True, "t_src": 2.0, "raw": {"why": "the operator"}}
d = build(mcapio.read(mcapio.write(keys.run_dir(tmp, key), mcapio.new_run(key, dict(ROBOT), "apartment", "goal-run", 1_000_000_000),
                                   [(2.0, "event", ev), (2.0, "end", {"verdict": "cancelled"})]).parent))
check("a run recorded since reads as it was written", [e["kind"] for e in d.run["events"]] == ["cancelled"]
      and d.run["verdict"] == "cancelled", (d.run["events"], d.run["verdict"]))

# a navigator's log (ticks.jsonl) of before the contract, read by the adapter
for why, end in (("truth guard: 0.29 m from the staircase, trunk 0.270 m", "stopped_by_guardrail"),
                 ("cancelled by Mission Control", "cancelled")):
    log = DuckLog(tmp / "nowhere", "apartment")
    log.start, log.header, log.fresh = None, [], True
    recs = log.feed_row({"t": 1.0, "pose": [0, 0, 0]}) + log.feed_row({"t": 2.0, "event": "aborted", "why": why})
    evs = [p for _, k, p in recs if k == "event"]
    check(f"a log's old stop ({end}) is read as {end}, notable, its reason kept", [e["kind"] for e in evs] == [end]
          and evs[0]["notable"] and evs[0]["raw"].get("why") == why, evs)
    verdict = [p["verdict"] for _, k, p in log.finish() if k == "end"]
    check(f"and the run it makes ends {end}", verdict == [end], verdict)

print()
print("STOPS BEFORE", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
