"""Reading runs (ADR-0008): every record checked, a bad run isolated as broken, rewrites noticed, the follower
never stops. Run: cd viewer && uv run python tests/test_reading.py"""

import json
import math
import os
import shutil
import tempfile
import threading
from pathlib import Path

from helpers import catalog, T0_NS, Checks, make_run, run_record, scene, tick, wait_until
from miniview import keys, mcapio, validate, wire

check = Checks("READING")
HEAD = [(0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]})]


def inject(rec, topic, obj, t=1.0, raw=None):
    """A message written straight to the file, as a buggy writer could."""
    rec._w.add_message(rec._ch[topic], T0_NS + round(t * 1e9), raw if raw is not None else json.dumps(obj).encode(),
                       T0_NS + round(t * 1e9))
    rec.flush()


def by_key(cat, key):
    return next(r for s in cat.scenes_with_runs()["scenes"] for r in s["runs"] if r["key"] == key)


# ---- the checks, kind by kind -------------------------------------------------------------------------------------
good = tick(1.0, 0.0)[2]
bad_ticks = {"belief null": dict(good, belief=None), "belief short": dict(good, belief=[0, 0]),
             "belief nan": dict(good, belief=[math.nan, 0, 0]), "belief inf": dict(good, belief=[0, math.inf, 0]),
             "belief text": dict(good, belief=[0, "x", 0]), "truth short": dict(good, truth=[1, 2]),
             "cmd long": dict(good, cmd=[1, 2, 3]), "depth point short": dict(good, depth=[[1, 2, 3]]),
             "depth kind": dict(good, depth=[[1, 2, 3, "ff"]]), "depth nan": dict(good, depth=[[math.nan, 0, 0, "f"]]),
             "bool as number": dict(good, belief=[True, 0, 0])}
check("a tick is checked field by field: types, lengths, finite numbers",
      validate.check(1.0, "tick", good, 0.0) is None and all(validate.check(1.0, "tick", p, 0.0) for p in bad_ticks.values()),
      [k for k, p in bad_ticks.items() if not validate.check(1.0, "tick", p, 0.0)])
check("time must not go back, nor be infinite or text",
      validate.check(1.0, "tick", good, 2.0) and validate.check(math.inf, "tick", good, 0.0)
      and validate.check("1", "tick", good, 0.0) and validate.check(2.0, "tick", good, 2.0) is None)
check("plans, worlds, events, epochs and ends are checked too",
      validate.check(1, "plan", {"path": [[0, 1], [0, "a"]]}, 0) and validate.check(1, "plan", {}, 0)
      and validate.check(1, "world", {"grid": {"res": 0.1, "origin": [0, 0], "w": 2, "h": 2, "cells": "???"}, "obstacles": [], "drops": []}, 0)
      and validate.check(1, "world", {"grid": {"res": 0, "origin": [0, 0], "w": 2, "h": 2, "cells": "????"}, "obstacles": [], "drops": []}, 0)
      and validate.check(1, "event", {"kind": "x"}, 0) and validate.check(1, "epoch", {"map_to_world": [1, 2]}, 0)
      and validate.check(1, "end", {}, 0) and validate.check(1, "mystery", {}, 0) and validate.check(1, "tick", [], 0))

with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    cat = catalog(data)
    cat.put_scene(scene())
    make_run(data, "duck/room/fine", HEAD + [tick(1.0, 0.0), tick(1.1, 0.03), (2.0, "end", {"verdict": "ended"})])

    # ---- a garbage file: the service still starts; the run is listed as broken, with its error --------------------
    junk = data / "runs" / "duck" / "room" / "junk"
    junk.mkdir(parents=True)
    (junk / "run.mcap").write_bytes(b"this is not an MCAP file, whatever its name says")
    # ---- no valid run record ----------------------------------------------------------------------------------------
    rec = mcapio.Recorder(keys.run_dir(data, "duck/room/norun"), dict(run_record("duck/room/norun"), uuid=None))
    rec.close()
    # ---- a key that is not the folder's ----------------------------------------------------------------------------
    make_run(data, "duck/room/aaa", HEAD + [tick(1.0, 0.0), (2.0, "end", {"verdict": "ended"})])
    (data / "runs/duck/room/aaa").rename(data / "runs/duck/room/bbb")
    cat.scan()
    junk_r, norun_r, bbb_r, fine_r = (by_key(cat, f"duck/room/{n}") for n in ("junk", "norun", "bbb", "fine"))
    check("a garbage file does not stop the scan: listed broken with the reason, not loaded",
          junk_r["status"] == "broken" and "not an MCAP" in junk_r["error"] and cat.get("duck/room/junk").data.run["ticks"] == 0, junk_r)
    check("a run with no valid run record is broken", norun_r["status"] == "broken" and "run record" in norun_r["error"], norun_r)
    check("a run whose record names another key than its folder is broken, never listed under a second name",
          bbb_r["status"] == "broken" and "duck/room/aaa" in bbb_r["error"]
          and not any(r["key"] == "duck/room/aaa" for s in cat.scenes_with_runs()["scenes"] for r in s["runs"]), bbb_r)
    check("the good run beside them is untouched", fine_r["status"] == "ended" and cat.get("duck/room/fine").data.run["ticks"] == 2, fine_r)

    # ---- bad records: skipped and counted, the first reason kept, the run still served ----------------------------
    rec = make_run(data, "duck/room/dirty", HEAD + [tick(1.0, 0.0)], close=False)
    inject(rec, "/belief/pose", None, 1.1, raw=b'{"timestamp":{"sec":1,"nsec":0},"frame_id":"map","pose":null}')   # the belief of a tick
    inject(rec, "/miniview/event", {"kind": "no text"}, 1.2)
    inject(rec, "/miniview/plan", {"path": [[0, 1], [0, "a"]]}, 1.3)
    inject(rec, "/miniview/event", {"kind": "late", "text": "late"}, 0.5)         # time goes back
    inject(rec, "/miniview/event", None, 1.4, raw=b"not json at all")
    rec.add(*tick(1.5, 0.1))
    ld = cat.get("duck/room/dirty")
    ld.poll()
    r = ld.data.run
    check("bad records are skipped and counted; the good ones around them are applied",
          r["ticks"] == 2 and r["rejects"] >= 4 and r["status"] == "live" and not ld.error, {k: r[k] for k in ("ticks", "rejects", "status")})
    check("the first error is kept, with the time", bool(r["first_error"]) and " at " in r["first_error"], r["first_error"])
    check("the listing carries the rejects and the first error",
          by_key(cat, "duck/room/dirty")["rejects"] >= 4 and by_key(cat, "duck/room/dirty")["first_error"] == r["first_error"])
    rec.close()

    # ---- the follower never dies; one run's failure is that run's ---------------------------------------------------
    live_a = make_run(data, "duck/room/livea", HEAD + [tick(1.0, 0.0)], close=False)
    live_b = make_run(data, "duck/room/liveb", HEAD + [tick(1.0, 0.0)], close=False)
    cat.scan()
    boom = cat.get("duck/room/livea")
    real = type(boom)._poll

    def poll_or_die(self):
        if self.key == "duck/room/livea":
            raise RuntimeError("a bug that only this run triggers")
        return real(self)

    type(boom)._poll = poll_or_die
    try:
        live_a.add(*tick(1.1, 0.1))
        live_b.add(*tick(1.1, 0.1))
        cat.follow_once()
        check("an exception while following one run marks that run broken, with its reason",
              by_key(cat, "duck/room/livea")["status"] == "broken" and "RuntimeError" in by_key(cat, "duck/room/livea")["error"])
        check("the other live run kept growing", cat.get("duck/room/liveb").data.run["ticks"] == 2)
        orig_scan, calls = cat.scan, []

        def flaky_scan():
            calls.append(1)
            if len(calls) == 1:
                raise OSError("the disk hiccuped")
            return orig_scan()

        cat.scan = flaky_scan
        th = threading.Thread(target=cat.follow_forever, kwargs={"every_s": 0.01, "rescan_s": 0.0}, daemon=True)
        th.start()
        live_b.add(*tick(1.2, 0.2))
        wait_until(lambda: cat.get("duck/room/liveb").data.run["ticks"] == 3, what="the live run to grow after the failed round")
        check("a failed round of the follower is logged, and the loop goes on", th.is_alive() and len(calls) > 1)
    finally:
        type(boom)._poll = real
        cat.scan = orig_scan

    # ---- a file replaced under the reader: read again, and the run says so ------------------------------------------
    other = Path(tmp) / "other"
    make_run(other, "duck/room/fine", HEAD + [tick(5.0, 0.5), tick(5.1, 0.6), tick(5.2, 0.7), (6.0, "end", {"verdict": "ended"})])
    os.replace(other / "runs/duck/room/fine/run.mcap", data / "runs/duck/room/fine/run.mcap")
    cat.scan()
    r = cat.get("duck/room/fine").data.run
    check("a finished run replaced by another file is read again: new content, rewritten counted",
          r["ticks"] == 3 and r["t0"] == 5.0 and r["rewritten"] == 1, {k: r[k] for k in ("ticks", "t0", "rewritten")})

    # ---- a poll of a finished run between the replace and the scan must not hide the replace -----------------------
    # CI 2026-11-15 (22be841): the check above failed when the follower thread left running polled the
    # finished run first: its poll stored the new file's signature without reading it.
    make_run(other, "duck/room/fine2", HEAD + [tick(1.0, 0.0), (2.0, "end", {"verdict": "ended"})])
    os.replace(other / "runs/duck/room/fine2/run.mcap", (data / "runs/duck/room/fine2").mkdir(parents=True) or
               data / "runs/duck/room/fine2/run.mcap")
    cat.scan()
    ld = cat.get("duck/room/fine2")
    other2 = Path(tmp) / "other2"                          # the same key, written elsewhere
    make_run(other2, "duck/room/fine2", HEAD + [tick(7.0, 0.5), tick(7.1, 0.6), (8.0, "end", {"verdict": "ended"})])
    os.replace(other2 / "runs/duck/room/fine2/run.mcap", data / "runs/duck/room/fine2/run.mcap")
    ld.poll()                                              # what a follower round does to a finished run
    cat.scan()
    r = cat.get("duck/room/fine2").data.run
    check("a poll between the replace and the scan does not hide the replace",
          r["ticks"] == 2 and r["t0"] == 7.0 and r["rewritten"] == 1, {k: r[k] for k in ("ticks", "t0", "rewritten")})

    # ---- a live file cut and rewritten under the reader -------------------------------------------------------------
    rec = make_run(data, "duck/room/cut", HEAD + [tick(1.0, 0.0), tick(1.1, 0.1), tick(1.2, 0.2)], close=False)
    ld = cat.get("duck/room/cut")
    ld.poll()                                              # the follower thread started above may have opened the run before its third tick
    check("(setup) the live run has its three ticks", ld.data.run["ticks"] == 3)
    other2 = Path(tmp) / "other2"
    rec2 = make_run(other2, "duck/room/cut", HEAD + [tick(9.0, 0.9)], close=False)
    live = data / "runs/duck/room/cut/run.live.mcap"
    with open(live, "r+b") as fh:                       # same file (same inode), cut and rewritten shorter
        fh.truncate(0)
        fh.write((other2 / "runs/duck/room/cut/run.live.mcap").read_bytes())
    ld.poll()
    r = ld.data.run
    check("a live file that shrank is read from the start: the new content, and `rewritten`",
          r["ticks"] == 1 and r["t0"] == 9.0 and r["rewritten"] == 1, {k: r[k] for k in ("ticks", "t0", "rewritten")})

    # ---- a live file replaced by a longer one (another inode) -------------------------------------------------------
    rec3 = make_run(other2, "duck/room/cut2", HEAD + [tick(7.0, 0.7)] * 1, close=False)
    rec4 = make_run(data, "duck/room/cut2", HEAD + [tick(1.0, 0.0)], close=False)
    ld2 = cat.get("duck/room/cut2")
    for i in range(1, 6):
        rec3.add(*tick(7.0 + i * 0.1, 0.7))
    replacement = Path(tmp) / "replacement.mcap"
    shutil.copy(other2 / "runs/duck/room/cut2/run.live.mcap", replacement)
    os.replace(replacement, data / "runs/duck/room/cut2/run.live.mcap")
    ld2.poll()
    check("a live file replaced by a longer one (another inode) is read from the start too",
          ld2.data.run["ticks"] == 6 and ld2.data.run["t0"] == 7.0 and ld2.data.run["rewritten"] == 1,
          {k: ld2.data.run[k] for k in ("ticks", "t0", "rewritten")})

    # ---- a replaced broken file is read again ---------------------------------------------------------------------
    shutil.copy(data / "runs/duck/room/fine/run.mcap", Path(tmp) / "good.mcap")
    make_run(other, "duck/room/junk", HEAD + [tick(1.0, 0.0), (2.0, "end", {"verdict": "ended"})])
    os.replace(other / "runs/duck/room/junk/run.mcap", junk / "run.mcap")
    cat.scan()
    check("a broken run whose file was replaced by a good one is read again", by_key(cat, "duck/room/junk")["status"] == "ended")

check.done()
