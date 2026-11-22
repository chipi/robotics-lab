"""The lab's data folder, the index over it, and the runs in memory (ADR-0004, ADR-0006, ADR-0008, ADR-0009).

    data/scenes/<scene>/scene.json
    data/runs/<robot>/<scene>/<run>/run.mcap       the record of truth (run.live.mcap + writer.lock while written)
    $OBSERVATORY_INDEX                              the service's own index (runfile.index), outside the data

`Catalog` knows every run from the index, opens a run's records into memory when asked, and follows the
runs that are still being written. A run is `live`, `ended`, `stopped` (its writer died) or `broken`;
the last three are final until the file changes. Loaded runs live in a cache bounded by memory
(`OBSERVATORY_CACHE_MB`): the least recently used go first; live runs and runs with an open stream stay.
Nothing that goes wrong inside one run leaves it (ADR-0008).
"""

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from runfile import env, installation, keys, mcapio
from runfile.index import Index
from runfile.store import RunData
from runfile.validate import BrokenRun

log = logging.getLogger("runfile")

STOPPED_AFTER_S = 120.0     # a live file with no writer that has not grown for this long lost its writer
FOLLOW_EVERY_S = 0.25      # how often the follower looks at the live runs: the latency of a live page is about this
FINAL = ("ended", "stopped", "broken")


def default_data() -> Path | None:
    """The lab's data folder: $OBSERVATORY_DATA, else the installation file's `data` (phase 5 step 1), else None."""
    v = env.get("DATA", "").strip()
    if v:
        return Path(v)
    inst = installation.load(required=False)
    return inst.data if inst is not None else None


def _file_of(d: Path) -> Path:
    return d / mcapio.FINAL if (d / mcapio.FINAL).exists() else d / mcapio.LIVE


def signature(d: Path):
    """(file name, inode, size, mtime_ns) of a run's current file; None when it has none."""
    f = _file_of(d)
    try:
        st = f.stat()
    except OSError:
        return None
    return (f.name, st.st_ino, st.st_size, st.st_mtime_ns)


class Loaded:
    """One run: its follower, its records so far. A failure in here marks this run broken (with the
    reason) and is logged with its key."""

    def __init__(self, key: str, path: Path):
        self.key = key
        self.dir = path
        self.follower = mcapio.Follower(path)
        self.data = RunData()
        self.error = None
        self.stopped = False
        self.sig = None
        self.io = threading.RLock()     # one reader of the file at a time (the follower, a scan, a request)
        self.pins = 0
        self.indexed_events = 0
        self.indexed_segments = 0
        self.indexed_status = None

    def mark_broken(self, msg: str) -> None:
        self.error = msg
        self.sig = signature(self.dir)
        r = self.data.run
        robot, scene, name = self.key.split("/")
        r.update(key=self.key, id=name, scene=r["scene"] or scene, status="broken", verdict="broken", error=msg)
        r["robot"] = r["robot"] or {"name": robot}
        log.error("run %s is broken: %s", self.key, msg)
        with self.data.changed:
            self.data.changed.notify_all()

    def mark_stopped(self) -> None:
        """Its writer died: the run ends here, as `stopped`, until its file changes."""
        self.stopped = True
        with self.data.changed:
            self.data.run.update(status="stopped", verdict="stopped")
            self.data.changed.notify_all()
        log.warning("run %s: its writer is gone and the file stopped growing; stopped", self.key)

    def rebuild(self) -> None:
        """Read the file again from the start (it was replaced, or repaired)."""
        with self.data.changed:
            self.data.reset()
            self.follower = mcapio.Follower(self.dir)
            self.error, self.stopped = None, False
            self.indexed_events = self.indexed_segments = 0

    def poll(self) -> bool:
        """Read what the file gained; True when the run changed. Never raises."""
        with self.io:
            if self.error or self.stopped:
                return False
            try:
                return self._poll()
            except Exception as e:      # whatever this one run holds, it is this run's failure
                self.mark_broken(f"{type(e).__name__}: {e}")
                return True

    def _poll(self) -> bool:
        gen, was_done = self.follower.generation, self.follower.done
        recs = self.follower.poll()
        with self.data.changed:                         # readers serialize under the same lock
            if self.follower.generation != gen:
                self.data.reset()
                self.indexed_events = self.indexed_segments = 0
            for t, kind, p in recs:
                self.data.feed(t, kind, p)
                if kind == "run" and self.data.run["key"] != self.key:
                    raise BrokenRun(f"the run record says {self.data.run['key']!r}, its folder is {self.key!r}")
            bad = self.follower.take_errors()
            for msg in bad:
                self.data.run["rejects"] += 1
                self.data.run["first_error"] = self.data.run["first_error"] or msg
            if self.follower.generation != gen:
                self.data.run["rewritten"] = self.follower.rewrites
            finished = self.follower.done and not was_done
            if recs or bad or finished or self.follower.generation != gen:
                if self.follower.done and self.data.run["status"] == "live":
                    self.data.run["status"] = "ended"   # finished without an end record
                    if self.data.run["verdict"] == "live":
                        self.data.run["verdict"] = "ended"
                self.data.finish_batch()
        if self.data.run["key"] is None and (recs or bad):
            raise BrokenRun("no valid run record: " + (bad[0] if bad else "the first message is not the run record"))
        # The signature says which file the records came from: only a poll that read the file may
        # take the file's signature. A poll of a finished run reads nothing, and taking the signature
        # then would hide a replaced file from check_changed (CI, 2026-11-15).
        if recs or bad or self.sig is None or self.follower.generation != gen or self.follower.done != was_done:
            self.sig = signature(self.dir)
        return bool(recs or bad)

    def check_changed(self) -> bool:
        """A run that was final (finished, stopped, broken) and whose file changed: read again. True when it was."""
        with self.io:
            sig = signature(self.dir)
            if sig is None or self.sig is None or sig == self.sig or not (self.follower.done or self.error or self.stopped):
                return False
            if self.stopped and not self.error and self.sig[0] == sig[0] == mcapio.LIVE and sig[1] == self.sig[1] and sig[2] > self.sig[2]:
                self.stopped = False                # a paused writer wrote again: the same file grew, the run goes on
                with self.data.changed:
                    self.data.run.update(status="live", verdict="live")
                    self.data.changed.notify_all()
                self.poll()
                log.warning("run %s: its file grew again after it had stopped; following it again", self.key)
                return True
            repaired = self.sig[0] == mcapio.LIVE and sig[0] == mcapio.FINAL      # compaction (or a repair), not a rewrite
            with self.data.changed:     # readers wait for the new content; they never see the run empty
                self.rebuild()
                self.poll()
                if not repaired:
                    self.data.run["rewritten"] += 1
        log.warning("run %s: its file changed; read again from the start", self.key)
        return True

    @property
    def live(self) -> bool:
        return not self.follower.done and not self.error and not self.stopped

    @property
    def path(self) -> Path:
        return _file_of(self.dir)


class Catalog:
    def __init__(self, data: Path | None = None, index: Path | None = None, cache_mb: float | None = None):
        data = Path(data) if data else default_data()
        if data is None:
            raise SystemExit("no data folder: set OBSERVATORY_DATA or pass --data")
        self.data = data
        for sub in ("runs", "scenes"):
            try:
                (self.data / sub).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass                                    # a read-only mount that lacks it: nothing there
        self.index = Index(index)
        self.cache_bytes = int(float(cache_mb if cache_mb is not None else env.get("CACHE_MB", 1024))
                               * 1024 * 1024)
        self.lock = threading.RLock()
        self.loaded = OrderedDict()   # run key -> Loaded, least recently used first
        self.paths = {}               # run key -> the run's folder
        self.evictions = 0
        self._keylocks = {}
        self.read_only = False     # a service holds the index: this catalog reads it and writes nothing to it (ADR-0009)
        self._missed = {}          # keys looked for and not found, and when: a bad key does not rescan the folder every time

    # ---- scenes ----------------------------------------------------------------------------------
    def scene(self, scene_id: str) -> dict | None:
        p = self.data / "scenes" / scene_id / "scene.json"
        try:
            sc = json.loads(p.read_text())
        except (OSError, ValueError):
            return None
        return sc if sc.get("id") == scene_id else None

    def put_scene(self, scene: dict) -> Path:
        p = self.data / "scenes" / scene["id"] / "scene.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(scene, separators=(",", ":")))
        return p

    # ---- finding runs ------------------------------------------------------------------------------
    def scan_paths(self) -> None:
        found = {}
        for p in sorted((self.data / "runs").glob("*/*/*")):
            if not ((p / mcapio.FINAL).exists() or (p / mcapio.LIVE).exists()):
                continue
            try:
                found[keys.key_of(self.data, p)] = p
            except ValueError as e:
                log.warning("not a run: %s (%s)", p, e)
        self.paths = found

    def candidates(self, name: str) -> list:
        return [k for k in self.paths if k.rsplit("/", 1)[-1] == name]

    def resolve(self, run_id: str) -> str | None:
        """A key, or a short name when exactly one run has it; None otherwise (see `candidates`)."""
        if run_id in self.paths:
            return run_id
        c = self.candidates(run_id)
        return c[0] if len(c) == 1 else None

    # ---- the cache ----------------------------------------------------------------------------------
    def _pinned(self, ld: Loaded) -> bool:
        return ld.pins > 0 or self.status(ld) == "live"

    def cache_used(self) -> int:
        with self.lock:
            return sum(ld.data.mem for ld in self.loaded.values())

    def _evict(self, keep: str | None = None) -> None:
        """Drop the least recently used runs until the estimate fits; live runs, runs with an open stream and `keep` stay."""
        with self.lock:
            total = sum(ld.data.mem for ld in self.loaded.values())
            for key in list(self.loaded):
                if total <= self.cache_bytes:
                    break
                ld = self.loaded[key]
                if key == keep or self._pinned(ld):
                    continue
                del self.loaded[key]
                total -= ld.data.mem
                self.evictions += 1

    def get(self, run_id: str) -> Loaded | None:
        """The run in memory, loading it (and keeping it in the cache) when it is not there."""
        with self.lock:
            key = self.resolve(run_id)
            if key is None:
                now = time.monotonic()
                if now - self._missed.get(run_id, -10.0) > 1.0:           # a run may have appeared; a key that was just missing, once a second
                    self.scan_paths()
                    key = self.resolve(run_id)
                    if key is None:
                        if len(self._missed) > 256:
                            self._missed.clear()
                        self._missed[run_id] = now
            if key is None:
                return None
            ld = self.loaded.get(key)
            if ld:
                self.loaded.move_to_end(key)
                return ld
            kl = self._keylocks.setdefault(key, threading.Lock())
            path = self.paths[key]
        with kl:                                        # one load per run at a time, without holding the catalog
            with self.lock:
                ld = self.loaded.get(key)
                if ld:
                    return ld
            ld = self._open(key, path)
            with self.lock:
                self.loaded[key] = ld
            self._index_or_break(ld)
            self._evict(keep=key)
            return ld

    def _index_or_break(self, ld: Loaded, status: str | None = None) -> None:
        """Write the run to the index; if that fails, the run is broken (with the reason), not the request."""
        try:
            self._index(ld, status)
        except Exception as e:
            log.exception("indexing run %s failed", ld.key)
            if not ld.error:
                ld.mark_broken(f"index: {type(e).__name__}: {e}")
            try:
                self._index(ld, "broken")
            except Exception:
                pass

    def _open(self, key: str, path: Path) -> Loaded:
        ld = Loaded(key, path)
        ld.poll()
        if not ld.data.log:
            ld.data.finish_batch()
        return ld

    # ---- states -------------------------------------------------------------------------------------
    def status(self, ld: Loaded) -> str:
        """live, ended, stopped or broken. A live file is live while its writer's PID is alive or it grew
        in the last STOPPED_AFTER_S seconds; after that it is stopped, for good."""
        if ld.error:
            return "broken"
        if ld.stopped:
            return "stopped"
        if ld.data.run["status"] in ("ended", "stopped"):      # an end record (a repaired run's says stopped)
            return ld.data.run["status"]
        if ld.follower.done:
            return "ended"
        try:
            idle = time.time() - (ld.dir / mcapio.LIVE).stat().st_mtime
        except OSError:
            return "live"                               # being compacted this instant
        if mcapio.writer_alive(ld.dir) or idle < STOPPED_AFTER_S:
            return "live"
        ld.mark_stopped()
        return "stopped"

    # ---- scanning and following ----------------------------------------------------------------------
    def scan(self) -> None:
        """Bring the index up to date with the folder. A run whose file is as the index remembers it, and
        is final, is not opened. Any other is opened and summarized: kept in memory only if it is live."""
        with self.lock:
            self.scan_paths()
            paths = dict(self.paths)
        if self.read_only:
            return
        rows = self.index.rows()
        for key, d in sorted(paths.items()):
            try:
                self._scan_one(key, d, rows.get(key))
            except Exception:
                log.exception("scanning run %s failed", key)
        for key in set(self.index.keys()) - set(paths):
            self.index.drop(key)
            with self.lock:
                self.loaded.pop(key, None)
        for s in sorted((self.data / "scenes").glob("*/scene.json")):
            try:
                sc = json.loads(s.read_text())
                if sc.get("id") != s.parent.name:
                    log.warning("scene %s says it is %r: not indexed", s, sc.get("id"))
                    continue
                self.index.put_scene(sc)
            except Exception:
                log.exception("scene %s cannot be read", s)

    def _scan_one(self, key: str, d: Path, row: dict | None) -> None:
        with self.lock:
            ld = self.loaded.get(key)
        if ld:
            if ld.check_changed():
                self._index_or_break(ld)
            return
        sig = signature(d)
        if row and sig and (row["inode"], row["size"], row["mtime_ns"]) == sig[1:] and row["status"] in FINAL:
            return
        ld = self._open(key, d)
        with self.lock:
            kept = self.loaded.get(key)                 # a request may have opened it meanwhile: its Loaded is the one
        if kept is not None:
            return
        self._index_or_break(ld)
        if self.status(ld) == "live":
            with self.lock:
                kept = self.loaded.setdefault(key, ld)
                self.loaded.move_to_end(key)
            if kept is not ld:
                self._index_or_break(kept)

    def follow_once(self) -> list:
        """Poll every live run once, bring the index along; the keys of the runs that changed."""
        grew = []
        with self.lock:
            runs = list(self.loaded.values())
        for ld in runs:
            try:
                changed = ld.poll()
                status = self.status(ld)
                if changed or status != ld.indexed_status:
                    self._index_or_break(ld, status)
                    grew.append(ld.key)
            except Exception:
                log.exception("following run %s failed", ld.key)
        return grew

    def follow_forever(self, every_s: float = FOLLOW_EVERY_S, rescan_s: float = 2.0) -> None:
        last_scan = 0.0
        while True:
            try:
                if time.monotonic() - last_scan > rescan_s:
                    self.scan()
                    last_scan = time.monotonic()
                self.follow_once()
            except Exception:
                log.exception("the follower's round failed; going on")
            time.sleep(every_s)

    # ---- the index ----------------------------------------------------------------------------------
    def _index(self, ld: Loaded, status: str | None = None) -> None:
        """Write the run's row, streams and new events and segments in one transaction."""
        if self.read_only:
            return
        status = status or self.status(ld)
        with ld.data.changed:                           # a consistent copy; the write happens outside
            r = ld.data.run
            sig = ld.sig or (None, None, None, None)
            row = {"key": ld.key, "uuid": r["uuid"], "robot": (r["robot"] or {}).get("name"), "scene": r["scene"],
                   "kind": r["kind"], "status": status, "verdict": r["verdict"], "started_at_ns": r["started_at_ns"],
                   "t0": r["t0"], "t1": r["t1"], "ticks": r["ticks"], "events": len(r["events"]),
                   "rejects": r["rejects"], "first_error": r["first_error"], "error": r["error"],
                   "rewritten": r["rewritten"], "epochs": json.dumps(r["epochs"]), "size": sig[2], "mtime_ns": sig[3],
                   "inode": sig[1]}
            events, segments, streams = list(r["events"]), list(r["segments"]), list(r["streams"])
            from_event, from_segment = ld.indexed_events, ld.indexed_segments
            if from_event > len(events) or from_segment > len(segments):
                from_event = from_segment = 0
        self.index.write(row, streams, events, segments, from_event, from_segment)
        ld.indexed_events, ld.indexed_segments, ld.indexed_status = len(events), len(segments), status

    # ---- listing, from the index ---------------------------------------------------------------------
    def list_runs(self, robot=None, scene=None, status=None) -> list:
        out = []
        for r in self.index.runs(robot, scene, status):
            out.append({"id": r["key"].rsplit("/", 1)[-1], "key": r["key"], "robot": r["robot"], "scene": r["scene"],
                        "kind": r["kind"], "status": r["status"], "length_s": round((r["t1"] or 0) - (r["t0"] or 0), 1),
                        "verdict": r["verdict"], "events": r["events"], "started_at_ns": r["started_at_ns"],
                        "rejects": r["rejects"], "first_error": r["first_error"], "error": r["error"],
                        "rewritten": r["rewritten"]})
        return out

    def scenes_with_runs(self) -> dict:
        """index.json's shape (CONTRACT.md): the scenes, each with its runs, newest first."""
        out = {s["id"]: dict(s, runs=[]) for s in self.index.scenes()}
        for r in self.list_runs():
            # a run of a scene with no scene.json (RFC-0009 "a run without a known scene", ADR-0013 `unmapped`): listed, nothing drawn of the scene
            out.setdefault(r["scene"], {"id": r["scene"], "name": r["scene"], "kind": "no layout", "runs": []})["runs"].append(r)
        return {"format": 2, "scenes": list(out.values())}
