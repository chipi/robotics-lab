"""Mission Control's SQLite store (RFC-0014 §3.4.6, requirement O20): sites, areas, objects, goals, goal
runs, their decisions and their anomalies. One connection shared by the threads, serialised by a lock."""

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 4

# version -> what takes a store of that version to the next.
MIGRATIONS = {
    # to 2: one goal on several robots (RFC-0014 section 3.4.4): a run may have a parent (the group) and a group says how its
    # robots share the goal
    1: "ALTER TABLE goal_runs ADD COLUMN parent_id INTEGER; ALTER TABLE goal_runs ADD COLUMN share TEXT;",
    # to 3: per-client tokens, and the client a goal run was commanded by (RFC-0014 section 3.9)
    2: "ALTER TABLE goal_runs ADD COLUMN client TEXT;"
       " CREATE TABLE tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, client TEXT NOT NULL, hash TEXT NOT NULL UNIQUE,"
       " created_at REAL NOT NULL, revoked_at REAL);",
    # to 4: a goal run's anomalies, as its navigator raised them (RFC-0019's record; phase 5 item 3 step 3)
    3: "CREATE TABLE anomalies (run_id INTEGER NOT NULL REFERENCES goal_runs(id), n INTEGER NOT NULL, at REAL NOT NULL,"
       " data TEXT NOT NULL, PRIMARY KEY (run_id, n));",
}

SCHEMA = """
CREATE TABLE sites (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, frame TEXT NOT NULL DEFAULT 'site',
  dock_pose TEXT, guardrails TEXT NOT NULL DEFAULT '[]', retired INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE areas (
  site_id TEXT NOT NULL REFERENCES sites(id), id TEXT NOT NULL, name TEXT NOT NULL, type TEXT,
  outline TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
  PRIMARY KEY (site_id, id));
CREATE TABLE objects (
  site_id TEXT NOT NULL REFERENCES sites(id), id TEXT NOT NULL, kind TEXT NOT NULL, label TEXT,
  x REAL NOT NULL, y REAL NOT NULL, parts TEXT NOT NULL, confirmed INTEGER NOT NULL,
  landmark REAL NOT NULL, permanence REAL, confidence REAL NOT NULL, n INTEGER NOT NULL,
  unique_kind INTEGER NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
  seen_by TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY (site_id, id));
CREATE TABLE robot_sites (robot_id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES sites(id));
CREATE TABLE goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, folder TEXT NOT NULL, spec TEXT NOT NULL,
  retired INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE goal_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id INTEGER REFERENCES goals(id), goal TEXT NOT NULL,
  robot TEXT NOT NULL, site_id TEXT, target TEXT NOT NULL, state TEXT NOT NULL, reason TEXT,
  progress TEXT, result TEXT, broken TEXT, guardrails TEXT NOT NULL, conditions TEXT NOT NULL,
  run_key TEXT, as_expected INTEGER, created_at REAL NOT NULL, started_at REAL, ended_at REAL,
  parent_id INTEGER, share TEXT, client TEXT);
CREATE TABLE tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT, client TEXT NOT NULL, hash TEXT NOT NULL UNIQUE,
  created_at REAL NOT NULL, revoked_at REAL);
CREATE TABLE decisions (
  run_id INTEGER NOT NULL REFERENCES goal_runs(id), n INTEGER NOT NULL, at REAL NOT NULL,
  text TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (run_id, n));
CREATE TABLE anomalies (
  run_id INTEGER NOT NULL REFERENCES goal_runs(id), n INTEGER NOT NULL, at REAL NOT NULL,
  data TEXT NOT NULL, PRIMARY KEY (run_id, n));
"""


def dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def loads(text):
    return None if text is None else json.loads(text)


class Store:
    def __init__(self, path):
        """`path` is a file, or None for a database in memory (the tests)."""
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path) if path is not None else ":memory:", check_same_thread=False,
                                   isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self.lock = threading.RLock()
        with self.lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                self._db.executescript(SCHEMA)
                self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version > SCHEMA_VERSION:
                raise RuntimeError(f"{path}: schema version {version}, this build knows {SCHEMA_VERSION}")
            else:
                for v in range(version, SCHEMA_VERSION):       # an older store is brought up, one version at a time
                    self._db.executescript(MIGRATIONS[v])
                    self._db.execute(f"PRAGMA user_version = {v + 1}")

    def execute(self, sql: str, args=()) -> int:
        with self.lock:
            return self._db.execute(sql, args).lastrowid

    def one(self, sql: str, args=()):
        with self.lock:
            row = self._db.execute(sql, args).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, args=()) -> list:
        with self.lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    @contextmanager
    def transaction(self):
        """Nested uses join the outer one; an error rolls the whole of it back."""
        with self.lock:
            outer = not self._db.in_transaction
            if outer:
                self._db.execute("BEGIN")
            try:
                yield
            except BaseException:
                if outer:
                    self._db.execute("ROLLBACK")
                raise
            if outer:
                self._db.execute("COMMIT")

    def close(self) -> None:
        with self.lock:
            self._db.close()
