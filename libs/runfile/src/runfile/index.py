"""The index: the service's own database, outside the data folder (ADR-0009).

    runs      one row per run: who, when, how it ended, how big, and the file's size, mtime and inode
    streams   what each run holds, stream by stream
    events    every notable event of every run (questions across runs)
    segments  each goal's span
    scenes    the scenes on disk

Derived from the run files and rebuilt from them at any time. WAL with a busy timeout, so the commands
read it while the service writes it; a service holds the lock file beside it, and `observatory index`
(the rebuild) refuses while that lock is held.
"""

import fcntl
import json
import os
import sqlite3
import threading
from pathlib import Path

DEFAULT_INDEX = "/work/robotics-lab/state/miniview/index.sqlite"

SCHEMA = """
create table if not exists scenes (id text primary key, name text, kind text, json text);
create table if not exists runs (key text primary key, uuid text, robot text, scene text, kind text, status text,
  verdict text, started_at_ns integer, t0 real, t1 real, ticks integer, events integer, rejects integer,
  first_error text, error text, rewritten integer, epochs text, size integer, mtime_ns integer, inode integer);
create table if not exists streams (run text, id text, json text, primary key (run, id));
create table if not exists events (run text, t real, kind text, text text);
create table if not exists segments (run text, idx integer, goal text, outcome text, t_start real, t_end real,
  origin_src real, primary key (run, idx));
create index if not exists events_kind on events (kind);
create index if not exists events_run on events (run);
"""
RUN_COLS = ("key", "uuid", "robot", "scene", "kind", "status", "verdict", "started_at_ns", "t0", "t1", "ticks", "events",
            "rejects", "first_error", "error", "rewritten", "epochs", "size", "mtime_ns", "inode")


class IndexBusy(Exception):
    """A service holds the index."""


class Index:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or os.environ.get("MINIVIEW_INDEX") or DEFAULT_INDEX)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        self.db.execute("pragma journal_mode = wal")
        self.db.execute("pragma busy_timeout = 5000")
        self.db.execute("pragma synchronous = normal")
        self.db.executescript(SCHEMA)
        self.mutex = threading.RLock()
        self._lock_fh = None

    # ---- the service lock ------------------------------------------------------------------------------
    @property
    def lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".service")

    def hold(self) -> None:
        """Become the service that owns this index (until the process ends). IndexBusy if another is."""
        fh = open(self.lock_path, "a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.seek(0)
            other = fh.read().strip()
            fh.close()
            raise IndexBusy(f"a service holds {self.path} (pid {other or '?'})") from None
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        self._lock_fh = fh

    def held_elsewhere(self) -> str | None:
        """The pid of the service that holds the index, or None. (Probing takes and releases the lock.)"""
        if self._lock_fh is not None:
            return None
        try:
            fh = open(self.lock_path, "a+")
        except OSError:
            return None
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.seek(0)
            return fh.read().strip() or "?"
        else:
            fcntl.flock(fh, fcntl.LOCK_UN)
            return None
        finally:
            fh.close()

    def clear(self) -> None:
        """Empty the runs' tables, for a rebuild. The caller has checked that no service holds the index."""
        with self.mutex, self.db:
            for table in ("runs", "streams", "events", "segments"):
                self.db.execute(f"delete from {table}")

    # ---- scenes -----------------------------------------------------------------------------------------
    def put_scene(self, sc: dict) -> None:
        with self.mutex, self.db:
            self.db.execute("insert or replace into scenes values (?, ?, ?, ?)",
                            (sc["id"], sc.get("name", sc["id"]), sc.get("kind", ""), json.dumps(sc)))

    # ---- runs -------------------------------------------------------------------------------------------
    def row(self, key: str) -> dict | None:
        with self.mutex:
            cur = self.db.execute(f"select {', '.join(RUN_COLS)} from runs where key = ?", (key,))
            r = cur.fetchone()
        return dict(zip(RUN_COLS, r)) if r else None

    def rows(self) -> dict:
        """Every run's row, by key, in one query (a scan compares the files with them)."""
        with self.mutex:
            return {r[0]: dict(zip(RUN_COLS, r)) for r in self.db.execute(f"select {', '.join(RUN_COLS)} from runs")}

    def keys(self) -> list:
        with self.mutex:
            return [k for (k,) in self.db.execute("select key from runs")]

    def drop(self, key: str) -> None:
        with self.mutex, self.db:
            for table, col in (("runs", "key"), ("streams", "run"), ("events", "run"), ("segments", "run")):
                self.db.execute(f"delete from {table} where {col} = ?", (key,))

    def write(self, row: dict, streams: list, events: list, segments: list, from_event: int, from_segment: int) -> None:
        """One transaction: the run's row, its streams, and the events and segments from the given offsets on
        (0 means all: the old ones are deleted in the same transaction, so a count and its rows never disagree)."""
        key = row["key"]
        with self.mutex, self.db:
            self.db.execute(f"insert or replace into runs ({', '.join(RUN_COLS)}) values ({', '.join('?' * len(RUN_COLS))})",
                            [row[c] for c in RUN_COLS])
            self.db.execute("delete from streams where run = ?", (key,))
            self.db.executemany("insert into streams values (?, ?, ?)", [(key, s["id"], json.dumps(s)) for s in streams])
            if from_event == 0:
                self.db.execute("delete from events where run = ?", (key,))
            self.db.executemany("insert into events values (?, ?, ?, ?)",
                                [(key, e["t"], e["kind"], e["text"]) for e in events[from_event:]])
            if from_segment == 0:
                self.db.execute("delete from segments where run = ?", (key,))
            self.db.executemany("insert or replace into segments values (?, ?, ?, ?, ?, ?, ?)",
                                [(key, s["index"], json.dumps(s.get("goal")), s.get("outcome"), s["t_start"], s["t_end"],
                                  s.get("origin_src")) for s in segments[from_segment:]])

    def runs(self, robot: str | None = None, scene: str | None = None, status: str | None = None) -> list:
        where, args = [], []
        for col, v in (("robot", robot), ("scene", scene), ("status", status)):
            if v:
                where.append(f"{col} = ?")
                args.append(v)
        sql = (f"select {', '.join(RUN_COLS)} from runs" + (" where " + " and ".join(where) if where else "")
               + " order by started_at_ns desc, key")
        with self.mutex:
            return [dict(zip(RUN_COLS, r)) for r in self.db.execute(sql, args)]

    def scenes(self) -> list:
        with self.mutex:
            return [dict(zip(("id", "name", "kind"), r)) for r in self.db.execute("select id, name, kind from scenes order by id")]

    def stream_rows(self, key: str) -> list:
        with self.mutex:
            return [json.loads(j) for (j,) in self.db.execute("select json from streams where run = ? order by rowid", (key,))]

    def event_rows(self, key: str) -> list:
        with self.mutex:
            return [{"t": t, "kind": k, "text": x} for t, k, x in
                    self.db.execute("select t, kind, text from events where run = ? order by rowid", (key,))]

    def segment_rows(self, key: str) -> list:
        with self.mutex:
            return [{"index": i, "goal": json.loads(g) if g else None, "outcome": o, "t_start": a, "t_end": b}
                    for i, g, o, a, b in self.db.execute(
                        "select idx, goal, outcome, t_start, t_end from segments where run = ? order by idx", (key,))]

    def events_across(self, kinds=None) -> list:
        """(run key, t, kind, text) over all runs, newest run first."""
        sql = "select e.run, e.t, e.kind, e.text from events e join runs r on r.key = e.run"
        args = []
        if kinds:
            sql += f" where e.kind in ({', '.join('?' * len(kinds))})"
            args = list(kinds)
        with self.mutex:
            return list(self.db.execute(sql + " order by r.started_at_ns desc, e.run, e.rowid", args))
