"""The lab's data folder and its database (ADR-0004, ADR-0005).

    data/scenes/<scene>/scene.json
    data/runs/<robot>/<scene>/<run>/run.mcap      the record of truth
    data/index.sqlite                             derived: rebuilt from the files at any time

`Catalog` knows the runs, loads a run's records into memory when asked, and follows the runs that
are still being written (a live run is a run whose file has not ended). Every run it loads or
follows is written to the database: runs, streams, epochs, events and one row per tick.
"""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from miniview import keys, mcapio
from miniview.store import RunData

DEFAULT_DATA = Path(os.environ.get("MINIVIEW_DATA", "/work/robotics-lab/data"))
STOPPED_AFTER_S = 120.0     # a live file that has not grown for this long lost its writer

SCHEMA = """
create table if not exists scenes (id text primary key, name text, kind text, json text);
create table if not exists runs (id text primary key, scene text, robot text, kind text, status text,
  t0 real, t1 real, ticks integer, verdict text, events integer, path text, size integer, mtime real);
create table if not exists streams (run text, id text, json text, primary key (run, id));
create table if not exists epochs (run text, from_t real, map_to_world text);
create table if not exists events (run text, t real, kind text, text text);
create table if not exists ticks (run text, i integer, t real, bx real, by real, byaw real,
  tx real, ty real, tyaw real, vx real, vyaw real, pitch real, roll real, primary key (run, i));
"""


def run_dir(data: Path, robot: str, scene: str, run_id: str) -> Path:
    return data / "runs" / robot / scene / run_id


def _file_of(d: Path) -> Path:
    return d / mcapio.FINAL if (d / mcapio.FINAL).exists() else d / mcapio.LIVE


class Loaded:
    def __init__(self, path: Path):
        self.dir = path
        self.follower = mcapio.Follower(path)
        self.data = RunData()
        self.indexed_ticks = 0
        self.indexed_events = 0
        self.indexed_epochs = 0

    def poll(self) -> bool:
        recs = self.follower.poll()
        with self.data.changed:                         # readers serialize under the same lock
            for t, kind, p in recs:
                self.data.apply(t, kind, p)
            if recs or self.follower.done:
                if self.follower.done and self.data.run["status"] == "live":
                    self.data.run["status"] = "ended"   # finished without an end record
                    if self.data.run["verdict"] == "live":
                        self.data.run["verdict"] = "ended"
                self.data.finish_batch()
        return bool(recs)

    @property
    def live(self) -> bool:
        return not self.follower.done

    @property
    def path(self) -> Path:
        return _file_of(self.dir)


class Catalog:
    def __init__(self, data: Path = DEFAULT_DATA):
        self.data = Path(data)
        (self.data / "runs").mkdir(parents=True, exist_ok=True)
        (self.data / "scenes").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data / "index.sqlite", check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()
        self.loaded = {}         # run id -> Loaded
        self.paths = {}          # run key -> the run's folder

    # ---- scenes ----------------------------------------------------------------------------------
    def scene(self, scene_id: str) -> dict | None:
        p = self.data / "scenes" / scene_id / "scene.json"
        return json.loads(p.read_text()) if p.exists() else None

    def put_scene(self, scene: dict) -> Path:
        p = self.data / "scenes" / scene["id"] / "scene.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(scene, separators=(",", ":")))
        return p

    # ---- runs ------------------------------------------------------------------------------------
    def scan(self) -> None:
        """Find run files; load the new or changed ones into the database."""
        with self.lock:
            self.scan_paths()
            for rid, d in sorted(self.paths.items()):
                st = _file_of(d).stat()
                row = self.db.execute("select size, mtime, status from runs where id = ?", (rid,)).fetchone()
                if rid in self.loaded or (row and row[0] == st.st_size and row[1] == st.st_mtime and row[2] == "ended"):
                    continue
                self.get(rid)
            for s in sorted((self.data / "scenes").glob("*/scene.json")):
                sc = json.loads(s.read_text())
                self.db.execute("insert or replace into scenes values (?, ?, ?, ?)",
                                (sc["id"], sc.get("name", sc["id"]), sc.get("kind", ""), json.dumps(sc)))
            self.db.commit()

    def resolve(self, run_id: str) -> str | None:
        """A key, or a short name when exactly one run has it."""
        if run_id in self.paths:
            return run_id
        named = [k for k in self.paths if k.rsplit("/", 1)[-1] == run_id]
        return named[0] if len(named) == 1 else None

    def get(self, run_id: str) -> Loaded | None:
        with self.lock:
            run_id = self.resolve(run_id) or run_id
            if run_id in self.loaded:
                return self.loaded[run_id]
            p = self.paths.get(run_id)
            if p is None:
                self.scan_paths()
                run_id = self.resolve(run_id) or run_id
                p = self.paths.get(run_id)
            if p is None:
                return None
            ld = Loaded(p)
            ld.poll()
            if not ld.data.log:
                ld.data.finish_batch()
            self.loaded[run_id] = ld
            self._index(ld)
            return ld

    def scan_paths(self) -> None:
        for p in sorted((self.data / "runs").glob("*/*/*")):
            if (p / mcapio.FINAL).exists() or (p / mcapio.LIVE).exists():
                self.paths[keys.key_of(self.data, p)] = p

    def status(self, ld: Loaded) -> str:
        if not ld.live:
            return ld.data.run["status"]
        idle = time.time() - ld.path.stat().st_mtime
        return "stopped" if idle > STOPPED_AFTER_S else "live"

    def follow_once(self) -> list:
        """Poll every live run once; return the ids that grew."""
        grew = []
        with self.lock:
            live = [ld for ld in self.loaded.values() if ld.live]
        for ld in live:
            if ld.poll():
                grew.append(ld.data.run["key"])
                with self.lock:
                    self._index(ld)
        return grew

    def follow_forever(self, every_s: float = 0.25, rescan_s: float = 2.0) -> None:
        last_scan = 0.0
        while True:
            if time.monotonic() - last_scan > rescan_s:
                self.scan()
                last_scan = time.monotonic()
            self.follow_once()
            time.sleep(every_s)

    # ---- the database ----------------------------------------------------------------------------
    def _index(self, ld: Loaded) -> None:
        r, f, db = ld.data.run, ld.data.frames, self.db
        if not r.get("key"):
            return
        st = ld.path.stat()
        robot = (r.get("robot") or {}).get("name", "")
        db.execute("insert or replace into runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (r["key"], r["scene"], robot, r.get("kind", ""), self.status(ld), r["t0"], r["t1"], r["ticks"],
                    r["verdict"], len(r["events"]), str(ld.path), st.st_size, st.st_mtime))
        db.execute("delete from streams where run = ?", (r["key"],))
        db.executemany("insert into streams values (?, ?, ?)", [(r["key"], s["id"], json.dumps(s)) for s in r["streams"]])
        if ld.indexed_ticks == 0:
            for table in ("epochs", "events", "ticks"):
                db.execute(f"delete from {table} where run = ?", (r["key"],))
        db.executemany("insert into epochs values (?, ?, ?)",
                       [(r["key"], e["from_t"], json.dumps(e["map_to_world"])) for e in r["epochs"][ld.indexed_epochs:]])
        db.executemany("insert into events values (?, ?, ?, ?)",
                       [(r["key"], e["t"], e["kind"], e["text"]) for e in r["events"][ld.indexed_events:]])
        rows = []
        for i in range(ld.indexed_ticks, len(f["t"])):
            b, tr, cmd, tilt = f["belief"][i], f["truth"][i] or [None] * 3, f["cmd"][i] or [None, None], f["tilt"][i]
            rows.append((r["key"], i, f["t"][i], *b[:3], *tr[:3], *cmd[:2], *(tilt or [None, None])[:2]))
        db.executemany("insert or replace into ticks values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        ld.indexed_ticks, ld.indexed_events, ld.indexed_epochs = len(f["t"]), len(r["events"]), len(r["epochs"])
        db.commit()

    def scenes_with_runs(self) -> dict:
        """index.json's shape (CONTRACT.md): the scenes, each with its runs, newest first."""
        with self.lock:
            out = {}
            for sid, name, kind in self.db.execute("select id, name, kind from scenes order by id"):
                out[sid] = {"id": sid, "name": name, "kind": kind, "runs": []}
            for rid, scene, robot, kind, status, t0, t1, verdict, events in self.db.execute(
                    "select id, scene, robot, kind, status, t0, t1, verdict, events from runs order by mtime desc"):
                if rid in self.loaded:
                    status = self.status(self.loaded[rid])
                out.setdefault(scene, {"id": scene, "name": scene, "kind": "", "runs": []})["runs"].append(
                    {"id": rid.rsplit("/", 1)[-1], "key": rid, "robot": robot, "kind": kind, "status": status, "length_s": round(t1 - t0, 1),
                     "verdict": verdict, "events": events})
            return {"format": 1, "scenes": list(out.values())}
