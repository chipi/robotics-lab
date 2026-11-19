"""A run as records, and the run as the pages and the queries see it (ADR-0005).

A record is (t, kind, payload). Kinds: `run` (who and where, once), `epoch` (the map -> world
transform from t on), `tick` (belief, truth, command, tilt, depth), `signals` (a robot's named values at t,
ADR-0013), `plan`, `world`, `event`, `objects` and `sighting` (the semantic map and the camera's sightings, ADR-0019), `segment` (a goal's span, ADR-0007), `end` (the verdict). Adapters produce records; the MCAP file stores them (`runfile.mcapio`); `RunData`
applies them one by one, so a finished run and a live one are built the same way.
"""

import threading

from runfile import signals, validate
from runfile.validate import BrokenRun

END_KINDS = ("trapped", "aborted", "no_frontier_left")


class RunData:
    """The run (run.json's shape) and its frames (frames.json's shape, CONTRACT.md), built record by
    record. `seq` counts applied records; `changed` is notified after every batch."""

    def __init__(self):
        self.changed = threading.Condition()
        self.generation = 0           # how many times the file was read again from its start: a stream's check for a rewrite
        self._init()

    def reset(self) -> None:
        """Start over (the file was replaced); the condition, and so the readers waiting on it, stay."""
        self.generation += 1
        self._init()

    def _init(self):
        self.run = {"id": None, "key": None, "uuid": None, "scene": None, "kind": "run", "robot": {}, "status": "live",
                    "started_at_ns": None, "started_at_source": None, "t0": 0.0, "t1": 0.0, "ticks": 0,
                    "verdict": "live", "epochs": [], "events": [], "segments": [], "streams": [],
                    "rejects": 0, "first_error": None, "error": None, "rewritten": 0, "generation": self.generation,
                    "samples": 0}
        self.raw = []                 # the depth frames, raw (ADR-0014): {t, rows, cols, distance_mm, status, frame_t_ns, ...}, in time order
        self.frames = {"t": [], "belief": [], "truth": [], "truth_3d": [], "tilt": [], "cmd": [], "depth": [], "plan_at": [],
                       "world_at": [], "plans": [], "worlds": []}
        self.sem = {"objects": [], "sightings": []}      # the semantic map's snapshots and the camera's sightings (RFC-0016), each {t, ...}, in time order
        self.sig = {"t": [], "v": {}}     # the signals ticks: times, and per declared signal its value at each (None: none then)
        self.sig_kinds = {}               # declared signal -> "number" | "text"
        self.sig_counts = {}              # per signal, how many ticks carried a value
        self.log = []                 # (seq, t, kind, payload): what live followers send
        self.seq = 0
        self.last_t = 0.0
        self.counts = {"truth": 0, "depth": 0, "tilt": 0, "raw": 0, "objects": 0, "sightings": 0, "f": 0, "o": 0, "v": 0, "b": 0}   # stream counts, kept as records arrive
        self.mem = 0                  # an estimate of the bytes this run holds in memory (the cache's measure)
        self._spanned = False

    def feed(self, t, kind: str, p) -> bool:
        """Check a record, then apply it. False for a bad one: skipped, counted, the first one's reason kept.
        BrokenRun when the run's own record is missing, first or invalid: the run cannot be read."""
        if self.run["key"] is None and kind != "run":
            raise BrokenRun(f"the first record is {kind!r}, not the run record")
        err = validate.check(t, kind, p, self.last_t)
        if err:
            if kind == "run":
                raise BrokenRun(f"run record: {err}")
            self.run["rejects"] += 1
            if self.run["first_error"] is None:
                self.run["first_error"] = f"{kind} at t={t}: {err}"
            return False
        if kind == "signals":
            err = self._check_signals(p)
            if err:
                self.run["rejects"] += 1
                if self.run["first_error"] is None:
                    self.run["first_error"] = f"{kind} at t={t}: {err}"
                return False
        self.last_t = max(self.last_t, t)
        self.apply(t, kind, p)
        return True

    def _check_signals(self, p: dict) -> str | None:
        """Every value is of a declared signal and of its kind (the run record declared them)."""
        for name, v in p["values"].items():
            kind = self.sig_kinds.get(name)
            if kind is None:
                return f"signal {name!r} is not declared by the run"
            if signals.value_error(kind, v):
                return f"signal {name!r} ({kind}) {signals.value_error(kind, v)}"
        return None

    def apply(self, t: float, kind: str, p: dict) -> None:
        r, f = self.run, self.frames
        if kind == "run":
            r.update({k: p[k] for k in ("key", "uuid", "scene", "kind", "robot", "started_at_ns", "started_at_source",
                                        "writer", "source", "signals", "odometry", "no_pose", "goal_run") if k in p})
            r["id"] = p["key"].rsplit("/", 1)[-1]
            for d in p.get("signals") or ():
                self.sig_kinds[d["name"]] = d["kind"]
                self.sig["v"][d["name"]] = []
                self.sig_counts[d["name"]] = 0
        elif kind in ("tick", "signals", "plan", "world", "event"):     # the span: what happened, not bookkeeping
            r["t0"] = min(r["t0"], t) if self._spanned else t
            r["t1"] = max(r["t1"], t) if self._spanned else t
            self._spanned = True
        if kind == "epoch":
            r["epochs"].append({"from_t": t, "map_to_world": p["map_to_world"]})
        elif kind == "tick":
            f["t"].append(t)
            for k in ("belief", "truth", "truth_3d", "tilt", "cmd", "depth"):
                f[k].append(p.get(k))
            c = self.counts
            c["truth"] += bool(p.get("truth"))
            c["tilt"] += bool(p.get("tilt"))
            if p.get("depth"):
                c["depth"] += 1
                for pt in p["depth"]:
                    c[pt[3]] = c.get(pt[3], 0) + 1
            f["plan_at"].append(len(f["plans"]) - 1)
            f["world_at"].append(len(f["worlds"]) - 1)
            r["ticks"] = len(f["t"])
        elif kind == "signals":
            self.sig["t"].append(t)
            for name, col in self.sig["v"].items():
                v = p["values"].get(name)
                col.append(v)
                self.sig_counts[name] += v is not None
            r["samples"] = len(self.sig["t"])
        elif kind == "plan":
            f["plans"].append({"t": t, "path": p["path"]})
        elif kind == "world":
            f["worlds"].append(dict(p, t=t))
        elif kind == "event":
            r["events"].append({"t": t, "kind": p["kind"], "text": p["text"], **({"decision": p["decision"]} if p.get("decision") else {}),
                                **({"room": p.get("room"), "votes": p.get("votes") or {}} if p["kind"] == "room" else {}),
                                **({"area": p.get("area") or {}} if p["kind"] == "area" else {}),
                                **({"site": p.get("site") or {}} if p["kind"] == "site" else {})})
        elif kind == "objects":
            self.sem["objects"].append({"t": t, "objects": p["objects"], "changes": p["changes"]})
            self.counts["objects"] += 1
        elif kind == "sighting":
            self.counts["sightings"] += 1
            self.sem["sightings"].append({"t": t, **{k: p[k] for k in ("pose", "hfov_deg", "range_m", "seen")}})
        elif kind == "depth_frame":
            self.raw.append(dict(p, t=t))
            self.counts["raw"] += 1
        elif kind == "segment":
            r["segments"].append(dict(p))
        elif kind == "end":
            r["status"], r["verdict"] = ("stopped" if p["verdict"] == "stopped" else "ended"), p["verdict"]
        self.seq += 1
        self.log.append((self.seq, t, kind, p))
        self.mem += _cost(kind, p)

    def finish_batch(self) -> None:
        self.run["streams"] = streams(self.frames, self.run["events"], self.counts, self.run, self.sig, self.sig_counts)
        with self.changed:
            self.changed.notify_all()

    def since(self, seq: int) -> list:
        """Records applied after seq (the live stream's resume point); the log's index is seq - 1."""
        return self.log[max(seq, 0):]


def _cost(kind: str, p: dict) -> int:
    """Bytes a record costs in memory, measured on explore9 and phase1-run18 with tracemalloc (tests/test_index.py)."""
    if kind == "tick":
        return 1000 + 165 * len(p.get("depth") or ())
    if kind == "signals":
        return 400 + 120 * len(p["values"])
    if kind == "plan":
        return 380 + 165 * len(p["path"])
    if kind == "depth_frame":
        return 700 + 40 * len(p["distance_mm"])
    if kind == "objects":
        return 500 + 700 * len(p["objects"])
    if kind == "sighting":
        return 500 + 400 * len(p["seen"])
    if kind == "world":
        return 750 + len(p["grid"]["cells"]) + 165 * (len(p["obstacles"]) + len(p["drops"]))
    return 600


def build(records) -> RunData:
    d = RunData()
    for t, kind, p in records:
        d.feed(t, kind, p)
    d.finish_batch()
    return d


def verdict_of(events: list, evaluated: bool) -> str:
    if evaluated:
        return "evaluated"
    if events and events[-1]["kind"] in END_KINDS:
        return events[-1]["kind"]
    return "ended"


def streams(f: dict, events: list, counts: dict, run: dict | None = None, sig: dict | None = None,
            sig_counts: dict | None = None) -> list:
    """What the run holds, stream by stream, for the streams tree and its badges (CONTRACT.md). A run that declares
    signals has one stream per signal (id `signals.<name>`); a run with no pose says why in `no_pose`."""
    span = (f["t"][-1] - f["t"][0]) if len(f["t"]) > 1 else 0.0
    no_pose = (run or {}).get("no_pose") or "not in this run"

    def rate(n, sp=None):
        sp = span if sp is None else sp
        return round(n / sp, 1) if sp else None

    def s(sid, group, name, frame, count, modes=("at",), default="at", parent=None, why="not in this run", sp=None):
        e = {"id": sid, "group": group, "name": name, "frame": frame, "count": count, "rate_hz": rate(count, sp),
             "missing": count == 0, "time_modes": list(modes), "default_mode": default}
        if parent:
            e["parent"] = parent
        if count == 0:
            e["why"] = why
        return e

    n = len(f["t"])
    truth, depth_frames, tilt, kinds = counts["truth"], counts["depth"], counts["tilt"], counts
    last = f["worlds"][-1] if f["worlds"] else {"obstacles": [], "drops": []}
    track = ("at", "window", "upto")
    out = [
        s("scene.boxes", "Scene", "walls and furniture", "world", 1, why="no scene"),
        s("scene.hazards", "Scene", "hazards", "world", 1, why="no scene"),
        s("belief.pose", "Robot (belief)", "pose", "map", n, why=no_pose),
        s("belief.track", "Robot (belief)", "track", "map", n, track, "upto", why=no_pose),
        s("truth.pose", "Truth", "pose", "world", truth, why="no simulator truth"),
        s("truth.track", "Truth", "track", "world", truth, track, "upto", why="no simulator truth"),
        s("sensors.depth", "Sensors", "depth", "map", depth_frames, track, "at"),
    ]
    for k, sid, name in (("f", "floor", "floor"), ("o", "obstacle", "obstacle"), ("v", "overhead", "overhead"),
                         ("b", "below", "below the floor")):
        out.append(s(f"sensors.depth.{sid}", "Sensors", name, "map", kinds.get(k, 0), track, "at",
                     parent="sensors.depth", why="none of this kind"))
    out += [
        s("sensors.tilt", "Sensors", "tilt", "robot", tilt),
        s("sensors.raw", "Sensors", "raw depth frame", "robot", counts["raw"]),
        s("world.grid", "World model", "map grid", "map", len(f["worlds"])),
        s("world.obstacles", "World model", "obstacle memory", "map", len(last["obstacles"])),
        s("world.drops", "World model", "drops", "map", len(last["drops"]), why="no drop seen"),
        s("world.gaps", "World model", "gaps", "map", len(f["worlds"]) if f["plans"] else 0, why="needs a world model and a plan"),
        s("plan.path", "Plan", "path", "map", len(f["plans"])),
        s("semantic.objects", "Semantic map", "objects", "map", counts.get("objects", 0), why="no object recognised"),
        s("semantic.sighting", "Semantic map", "sightings", "map", counts.get("sightings", 0), why="no sighting recorded"),
        s("semantic.areas", "Semantic map", "areas", "map", max((len(e["site"].get("areas") or []) for e in events if e["kind"] == "site"),
                                                                default=0), why="no site with areas"),
        s("events", "Events", "events", "time", len(events), why="no events"),
    ]
    st = sig["t"] if sig else []
    sig_span = (st[-1] - st[0]) if len(st) > 1 else 0.0
    for d in (run or {}).get("signals") or ():
        e = s(f"signals.{d['name']}", "Signals", d["name"], "time", (sig_counts or {}).get(d["name"], 0), modes=(), sp=sig_span,
              why="no value in this run")
        e["kind"], e["unit"] = d["kind"], d.get("unit")
        out.append(e)
    return out
