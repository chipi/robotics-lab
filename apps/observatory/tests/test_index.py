"""The index, run states and the cache (ADR-0009). Run: cd apps/observatory && uv run python tests/test_index.py"""

import contextlib
import gc
import io
import json
import os
import subprocess
import sys
import tempfile
import tracemalloc
import argparse
from pathlib import Path

from helpers import FIXTURE, T0_NS, Checks, catalog, import_fixture, make_run, scene, tick
from runfile import catalog as catalog_mod
from runfile import keys, mcapio
from miniview import cli
from runfile.catalog import Loaded
from runfile.index import Index, IndexBusy

check = Checks("INDEX")
HEAD = [(0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]})]


def same_as_memory(cat, key):
    """The index's row, streams, events and segments against the run in memory."""
    ld = cat.get(key)
    r, row = ld.data.run, cat.index.row(key)
    return (row["ticks"] == r["ticks"] and row["events"] == len(r["events"]) and json.loads(row["epochs"]) == r["epochs"]
            and row["t0"] == r["t0"] and row["t1"] == r["t1"] and row["verdict"] == r["verdict"] and row["status"] == cat.status(ld)
            and cat.index.stream_rows(key) == r["streams"] and cat.index.event_rows(key) == r["events"]
            and [(s["index"], s["outcome"]) for s in cat.index.segment_rows(key)] == [(s["index"], s.get("outcome")) for s in r["segments"]]
            and row["rejects"] == r["rejects"])


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    return False


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def kill_writer(rec, d: Path, age_s: float = 0.0) -> None:
    """The writer's process is gone: its file closed without compaction, its lock left behind with a PID that is dead."""
    rec._fh.close()
    lock = json.loads((d / "writer.lock").read_text())
    (d / "writer.lock").write_text(json.dumps(dict(lock, pid=dead_pid())))
    if age_s:
        t = (d / "run.live.mcap").stat().st_mtime - age_s
        os.utime(d / "run.live.mcap", (t, t))


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    cat = catalog(data)
    cat.put_scene(scene())

    # ---- the index equals memory after a live run, epochs and events included ------------------------------------
    rec = make_run(data, "duck/room/live1", HEAD + [(0.5, "event", {"kind": "cleared", "text": "cleared"})], close=False)
    cat.scan()                                           # the run has an epoch and an event and no tick yet
    check("(setup) the live run is in memory and indexed with its epoch and its first event, before any tick",
          cat.index.row("duck/room/live1")["events"] == 1 and json.loads(cat.index.row("duck/room/live1")["epochs"])
          and "duck/room/live1" in cat.loaded)
    for i in range(6):
        rec.add(*tick(1.0 + i * 0.1, i * 0.03))
        if i == 2:
            rec.add(1.25, "event", {"kind": "cliff_stop", "text": "cliff_stop"})
            cat.follow_once()                            # a round in the middle: a partial batch
    rec.add(1.6, "segment", {"index": 0, "t_start": 1.0, "t_end": 1.6, "goal": [1.0, 0.0], "outcome": "reached", "origin_src": 1.0})
    rec.add(1.6, "epoch", {"map_to_world": [2.0, 0.0, 0.0]})
    cat.follow_once()
    check("a live run: the index equals memory (ticks, epochs, events, segments, streams, span)",
          same_as_memory(cat, "duck/room/live1") and len(cat.index.event_rows("duck/room/live1")) == 2
          and len(json.loads(cat.index.row("duck/room/live1")["epochs"])) == 2, cat.index.row("duck/room/live1"))
    rec.add(2.0, "end", {"verdict": "ended"})
    rec.close()
    cat.follow_once()
    check("after the run ends: still equal, status ended", same_as_memory(cat, "duck/room/live1")
          and cat.index.row("duck/room/live1")["status"] == "ended")

    # ---- the listing, the scenes page and questions across runs come from the index --------------------------------
    make_run(data, "duck/room/older", HEAD + [tick(1.0, 0.0), (1.5, "event", {"kind": "cliff_stop", "text": "cliff_stop a"}),
                                              (2.0, "end", {"verdict": "ended"})], started_at_ns=T0_NS - 10**12)
    make_run(data, "rover/room/other", HEAD + [tick(1.0, 0.0), (1.5, "event", {"kind": "tight_pivot", "text": "pivot"}),
                                               (2.0, "end", {"verdict": "ended"})], started_at_ns=T0_NS + 10**12)
    cat.scan()
    listing = cat.scenes_with_runs()["scenes"][0]["runs"]
    check("the scenes page lists runs newest first, by when they happened, with their key",
          [r["key"] for r in listing] == ["rover/room/other", "duck/room/live1", "duck/room/older"], [r["key"] for r in listing])
    check("the listing filters by robot, scene and status (from the index)",
          [r["key"] for r in cat.list_runs(robot="duck")] == ["duck/room/live1", "duck/room/older"]
          and [r["key"] for r in cat.list_runs(scene="nowhere")] == [] and len(cat.list_runs(status="ended")) == 3)
    loaded_before = set(cat.loaded)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_events(argparse.Namespace(data=str(data), run=None, all=True, kinds="cliff_stop", json=False))
    check("`miniview events --all --kind cliff_stop` answers across runs from the index",
          len(buf.getvalue().splitlines()) == 2 and "duck/room/older" in buf.getvalue() and "duck/room/live1" in buf.getvalue()
          and "tight_pivot" not in buf.getvalue(), buf.getvalue())
    jr = io.StringIO()
    with contextlib.redirect_stdout(jr):
        cli.cmd_events(argparse.Namespace(data=str(data), run=None, all=True, kinds="tight_pivot", json=True))
    check("... and as JSON", json.loads(jr.getvalue())[0]["run"] == "rover/room/other")
    check("the index is in WAL mode with a busy timeout, outside the data folder",
          cat.index.db.execute("pragma journal_mode").fetchone()[0] == "wal"
          and cat.index.db.execute("pragma busy_timeout").fetchone()[0] >= 1000 and not list(data.rglob("*.sqlite*")), cat.index.path)

    # ---- the service lock ---------------------------------------------------------------------------------------------
    cat.index.hold()
    other = Index(cat.index.path)
    check("a second service on the index is refused", other.held_elsewhere() and (lambda: _raises(IndexBusy, other.hold))())
    msg = None
    os.environ["MINIVIEW_INDEX"] = str(cat.index.path)          # the command finds the index as the service does
    try:
        cli.cmd_index(argparse.Namespace(data=str(data)))
    except SystemExit as e:
        msg = str(e)
    check("`miniview index` (the rebuild) refuses while a service holds the index, and leaves it as it was",
          bool(msg) and "holds" in msg and cat.index.row("duck/room/older") is not None, msg)

# ---- states, and what a restart does with them ------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    data, idx = Path(tmp) / "data", Path(tmp) / "state" / "index.sqlite"
    cat = catalog(data, index=idx)
    cat.put_scene(scene())
    make_run(data, "duck/room/done", HEAD + [tick(1.0, 0.0), (2.0, "end", {"verdict": "ended"})])
    junk = data / "runs/duck/room/junk"
    junk.mkdir(parents=True)
    (junk / "run.mcap").write_bytes(b"garbage")
    alive = make_run(data, "duck/room/alive", HEAD + [tick(1.0, 0.0)], close=False)
    grew = make_run(data, "duck/room/grew", HEAD + [tick(1.0, 0.0)], close=False)
    kill_writer(grew, data / "runs/duck/room/grew")            # dead writer, but the file grew just now
    crashed = make_run(data, "duck/room/crashed", HEAD + [tick(1.0, 0.0), tick(1.1, 0.1)], close=False)
    kill_writer(crashed, data / "runs/duck/room/crashed", age_s=1000)
    cat.scan()
    st = {r["key"]: r["status"] for r in cat.list_runs()}
    check("states: ended, broken; live = a writer's PID alive, or growth in the last 120 s; stopped = neither",
          st == {"duck/room/done": "ended", "duck/room/junk": "broken", "duck/room/alive": "live", "duck/room/grew": "live",
                 "duck/room/crashed": "stopped"}, st)
    check("a stopped run is not kept in memory or followed; live ones are", "duck/room/crashed" not in cat.loaded
          and "duck/room/alive" in cat.loaded and "duck/room/done" not in cat.loaded, list(cat.loaded))
    check("a stopped run still opens when asked, as stopped, ticks intact",
          cat.get("duck/room/crashed").data.run["ticks"] == 2 and cat.get("duck/room/crashed").data.run["status"] == "stopped")
    alive.close()

    # a restart: the index is read; only what changed is opened
    cat.follow_once()
    opened = []

    class Counting(Loaded):
        def __init__(self, key, path):
            opened.append(key)
            super().__init__(key, path)

    catalog_mod.Loaded = Counting
    try:
        cat2 = catalog(data, index=idx)
        cat2.scan()
        check("a restart opens no run that is final and unchanged: crashed, ended and broken ones stay in the index",
              "duck/room/crashed" not in opened and "duck/room/done" not in opened and "duck/room/junk" not in opened
              and {r["key"]: r["status"] for r in cat2.list_runs()}["duck/room/crashed"] == "stopped", opened)
        check("a restart opens the runs that were live, to summarize them (grew: live; alive: ended meanwhile)",
              set(opened) == {"duck/room/grew"} or set(opened) == {"duck/room/grew", "duck/room/alive"}, opened)
        st2 = {r["key"]: r["status"] for r in cat2.list_runs()}
        check("the scenes page after the restart comes from the index (no run opened for it)",
              [r["key"] for r in cat2.scenes_with_runs()["scenes"][0]["runs"]] and st2["duck/room/alive"] == "ended", st2)
        check("a restart keeps in memory only what is live", set(cat2.loaded) == {"duck/room/grew"}, list(cat2.loaded))
        n = len(opened)
        cat2.follow_once()
        cat2.scan()
        check("the crashed run is neither reloaded nor followed by later rounds", "duck/room/crashed" not in opened[n:] and len(opened) == n)
        # its file changes (a repair compacts it): it is read again, as stopped
        cli.cmd_repair(argparse.Namespace(data=str(data), run="duck/room/crashed"))
        cat2.scan()
        r = {x["key"]: x for x in cat2.list_runs()}["duck/room/crashed"]
        check("a stopped run whose file changed (repaired) is opened again; a repair is not a rewrite",
              "duck/room/crashed" in opened[n:] and r["status"] == "stopped" and r["rewritten"] == 0, r)
        # a changed ended run is summarized, not kept
        make_run(Path(tmp) / "second", "duck/room/done", HEAD + [tick(5.0, 0.0), tick(5.1, 0.1), (6.0, "end", {"verdict": "ended"})])
        os.replace(Path(tmp) / "second/runs/duck/room/done/run.mcap", data / "runs/duck/room/done/run.mcap")
        cat3 = catalog(data, index=idx)
        cat3.scan()
        check("a run whose file changed while the service was down is summarized from its new file, and not kept",
              "duck/room/done" in opened and cat3.index.row("duck/room/done")["ticks"] == 2 and "duck/room/done" not in cat3.loaded)
        os.environ["MINIVIEW_INDEX"] = str(idx)
        before = {r["key"]: (r["status"], r["events"]) for r in cat3.list_runs()}
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_index(argparse.Namespace(data=str(data)))
        after = {r["key"]: (r["status"], r["events"]) for r in catalog(data, index=idx).list_runs()}
        check("`miniview index` rebuilds the index from the files when no service holds it", before == after and len(after) == 5, (before, after))
    finally:
        catalog_mod.Loaded = Loaded

# ---- the cache is bounded by memory; live runs and open streams stay --------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    for name in "abcd":
        import_fixture(data, name)                              # explore9 under four names: about 1.8 MB each in memory
    cat = catalog(data, cache_mb=4.5)
    cat.scan()
    check("(setup) four runs indexed, none held after a summary", len(cat.list_runs()) == 4 and not cat.loaded)
    for n in "abc":
        cat.get(f"duck/apartment/{n}")
    check("the cache holds what fits (2 of 3 runs at 4.5 MB) and drops the least recently used",
          list(cat.loaded) == ["duck/apartment/b", "duck/apartment/c"] and cat.evictions == 1 and cat.cache_used() <= 4.5 * 1048576,
          (list(cat.loaded), cat.cache_used()))
    cat.get("duck/apartment/b")
    cat.get("duck/apartment/d")
    check("a run used again moves to the front: the least recently used goes next", list(cat.loaded) == ["duck/apartment/b", "duck/apartment/d"], list(cat.loaded))
    again = cat.get("duck/apartment/a")
    check("a run that was evicted loads again, whole", again.data.run["ticks"] == 116 and again.data.run["status"] == "ended")
    cat.get("duck/apartment/b").pins += 1                      # an open live stream
    cat.get("duck/apartment/c")
    cat.get("duck/apartment/d")
    check("a run with an open stream is pinned: not evicted while pinned", "duck/apartment/b" in cat.loaded, list(cat.loaded))
    cat.get("duck/apartment/b").pins -= 1
    live = make_run(data, "duck/room/livex", HEAD + [tick(1.0, 0.0)], close=False)
    cat.scan()
    for n in "acd":
        cat.get(f"duck/apartment/{n}")
    check("a live run is pinned: it stays however much else is loaded", "duck/room/livex" in cat.loaded, list(cat.loaded))
    live.close()

    # the estimate against what the interpreter really holds
    d = keys.run_dir(data, "duck/apartment/a")
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    ld = Loaded("duck/apartment/a", d)
    ld.poll()
    gc.collect()
    actual = tracemalloc.get_traced_memory()[0] - before
    tracemalloc.stop()
    check("the estimate of a run's memory is within 25% of what tracemalloc measures", 0.75 < ld.data.mem / actual < 1.25,
          f"estimate {ld.data.mem / 1e6:.2f} MB, measured {actual / 1e6:.2f} MB")

check.done()
