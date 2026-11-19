"""The LEGO NXT's recordings as format 2 runs (ADR-0013): one run per nxt-web recording, key `nxt/unmapped/<run>`.

Two writers share this module so a run looks the same whichever made it: `observatory import --robot nxt` (a finished
recording: its CSV, plus the events of its old MCAP or of events.jsonl) and nxt-web itself (live, through the recorder).

- **Signals.** Every CSV column but `t` is a signal of the run (`power_left`, `tacho_A`, `s4_ultrasonic`, `s3_color_name`,
  `program`, ...): a number, or text for the colour name and the program. One signals tick per sample.
- **Odometry.** With the wheel geometry (sprocket diameter, effective track width) the tacho counts of the two tracks give a
  pose, integrated per sample, in the robot's own frame, starting at the first sample: the run's belief pose (frame `map`).
  Without both values there is no pose, and the run says why (`no_pose`): the geometry is never guessed.
- **Events.** nxt-web's command log (drive, stop, fire, programs, safety stops) as `event` records.
"""

import csv
import hashlib
import json
import math
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from runfile import keys
from runfile.mcapio import FINAL, Recorder, WriterBusy, new_run

ROBOT = "nxt"
SCENE = "unmapped"
KIND = "recording"
# Drawn size of the robot's marker, not a measurement: nxt-web does not know the robot's footprint.
FOOTPRINT = {"radius": 0.10, "height": 0.12, "size": "nominal, for drawing only"}
NO_POSE = "no wheel geometry (set odom_sprocket_diameter_m and odom_track_width_m)"
NAME_TIME = re.compile(r"^run-(\d{8})-(\d{6})")
UUID_NAMESPACE = uuid.UUID("6f6c6e6a-5b0c-4c0a-9f6e-6d696e697669")
TICKS_ABOUT = ("A", "B", "C")
TOLERANCE_S = 2.0           # events this close to a recording's start or end belong to it (the file name has whole seconds)


def unit_of(name: str) -> str | None:
    if name.startswith("power_"):
        return "%"
    if name.startswith("tacho_"):
        return "deg"
    if name.endswith("_ultrasonic"):
        return "cm"
    return None


def kind_of(name: str, values=()) -> str:
    """`text` for the program and the colour name; else `number` when every value present is one."""
    if name == "program" or name.endswith("_name"):
        return "text"
    for v in values:
        if v not in (None, ""):
            try:
                float(v)
            except ValueError:
                return "text"
    return "number"


def columns_for(sensors: dict) -> list:
    """nxt-web's CSV columns (and so the signals) for a sensor setup {port: type}, in its order."""
    names = ["power_left", "power_right", "tacho_A", "tacho_B", "tacho_C"]
    for port, kind in sorted(sensors.items()):
        if kind != "none":
            names.append(f"s{port}_{kind}")
            if kind == "color":
                names.append(f"s{port}_color_name")
    names.append("program")
    return names


def declare(columns: dict) -> list:
    """The run record's `signals` for {name: kind}."""
    return [dict({"name": n, "kind": k}, **({"unit": unit_of(n)} if unit_of(n) else {})) for n, k in columns.items()]


# ---- odometry ---------------------------------------------------------------------------------------------------
@dataclass
class Geometry:
    """Wheel geometry and the motor mapping. `track_width_m` is the EFFECTIVE track width for turning (tracks slip:
    calibrated, not measured, docs/adr/ADR-0013). `source` says where the numbers came from."""
    sprocket_diameter_m: float
    track_width_m: float
    left: str = "C"
    right: str = "B"
    invert_left: bool = False
    invert_right: bool = False
    source: str = "given"

    def record(self) -> dict:
        return {"sprocket_diameter_m": self.sprocket_diameter_m, "track_width_m": self.track_width_m, "left": self.left,
                "right": self.right, "invert_left": self.invert_left, "invert_right": self.invert_right,
                "source": self.source}


def geometry_from(cfg: dict | None, source: str, sprocket=None, track=None) -> Geometry | None:
    """The geometry in a nxt-web config (a dict as config.json holds it), with values given directly taking over;
    None unless both the diameter and the width are known and positive."""
    cfg = cfg or {}
    d = sprocket if sprocket is not None else cfg.get("odom_sprocket_diameter_m")
    w = track if track is not None else cfg.get("odom_track_width_m")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0 for x in (d, w)):
        return None
    given = sprocket is not None or track is not None
    return Geometry(float(d), float(w), cfg.get("left", "C"), cfg.get("right", "B"), bool(cfg.get("invert_left", False)),
                    bool(cfg.get("invert_right", False)), "command line" if given else source)


class Odometry:
    """A differential drive from two tracks' tacho counts (motor degrees): per sample, each track's distance is
    deg / 360 * pi * D, the robot moves the mean and turns (right - left) / W (counter-clockwise positive), on the
    midpoint heading. The first sample is the origin (x = y = yaw = 0); a sample with no count for either track holds the pose."""

    def __init__(self, g: Geometry):
        self.g = g
        self.m_per_deg = math.pi * g.sprocket_diameter_m / 360.0
        self.last = None
        self.x = self.y = self.yaw = 0.0

    def step(self, tacho: dict) -> tuple:
        g = self.g
        cur = (tacho.get(g.left), tacho.get(g.right))
        if None in cur:
            return self.pose()
        if self.last is not None:
            dl = (cur[0] - self.last[0]) * (-1 if g.invert_left else 1) * self.m_per_deg
            dr = (cur[1] - self.last[1]) * (-1 if g.invert_right else 1) * self.m_per_deg
            d, dyaw = (dl + dr) / 2.0, (dr - dl) / g.track_width_m
            self.x += d * math.cos(self.yaw + dyaw / 2.0)
            self.y += d * math.sin(self.yaw + dyaw / 2.0)
            self.yaw += dyaw
        self.last = cur
        return self.pose()

    def pose(self) -> tuple:
        return (self.x, self.y, math.atan2(math.sin(self.yaw), math.cos(self.yaw)))


# ---- the run ----------------------------------------------------------------------------------------------------
def run_record(key: str, started_at_ns: int, started_at_source: str, columns: dict, geometry: Geometry | None,
               source: dict | None = None, run_uuid: str | None = None, writer: dict | None = None) -> dict:
    return new_run(key, dict(FOOTPRINT, name=ROBOT), SCENE, KIND, started_at_ns, started_at_source, source, run_uuid,
                   signals=declare(columns), odometry=geometry.record() if geometry else None,
                   no_pose=None if geometry else NO_POSE, writer=writer)


def header(rec: Recorder, geometry: Geometry | None) -> None:
    """What opens a run with a pose: the map frame is the world frame (there is no scene to place it in)."""
    if geometry:
        rec.add(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})


def write_sample(rec: Recorder, t: float, values: dict, odom: Odometry | None = None, tacho: dict | None = None) -> None:
    """One sample: a pose tick when there is odometry, then a signals tick, both at t. Values that are None or empty are absent."""
    if odom is not None:
        rec.begin_tick(t, [round(v, 5) for v in odom.step(tacho or {})], t_src=t)
        rec.end_tick({})
    present = {}
    for k, v in values.items():
        v = int(v) if isinstance(v, bool) else v                     # a touch sensor reads a bool
        if v is None or v == "" or (isinstance(v, float) and not math.isfinite(v)):
            continue
        present[k] = v
    if present:
        rec.begin_signals(t, present, t_src=t)
        rec.end_tick({})


def event_text(e: dict) -> str:
    detail = " ".join(f"{k} {v}" for k, v in e.items() if k not in ("seq", "at", "kind", "ok", "error") and v not in (None, "", []))
    return " ".join(x for x in (e["kind"], detail, "FAILED" if e.get("ok") is False else "", str(e.get("error") or "")) if x)


def event_record(e: dict, t: float) -> tuple:
    """A command-log entry (nxt-web's events: seq, at, kind, ok, detail...) as an event record at run time t."""
    return (t, "event", {"kind": e["kind"], "text": event_text(e), "notable": True, "t_src": t,
                         "raw": {k: v for k, v in e.items() if k != "kind"}})


# ---- importing a finished recording ----------------------------------------------------------------------------
def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _zone(tz: str | None):
    if tz is None:
        return None
    from zoneinfo import ZoneInfo

    return ZoneInfo(tz)


def local_ns(naive: datetime, tz: str | None) -> int:
    """A time of nxt-web's own machine (`datetime.now()`, no zone) in UTC nanoseconds: in `tz` (an IANA name), else in
    the zone of the machine this runs on."""
    z = _zone(tz)
    dt = naive.replace(tzinfo=z) if z else naive.astimezone()
    return round(dt.timestamp() * 1e9)


def time_in_name(name: str) -> datetime | None:
    m = NAME_TIME.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def read_old_mcap(path: Path) -> dict:
    """What an nxt-web MCAP of the old kind (mcap_log.py) holds: its states' (log_time, t), its events (log_time, entry) and
    its metadata (`config` as a dict). Empty lists when it cannot be read."""
    from mcap.reader import make_reader

    out = {"state": [], "events": [], "config": None}
    try:
        with open(path, "rb") as fh:
            reader = make_reader(fh)
            for _s, ch, msg in reader.iter_messages():
                body = json.loads(msg.data)
                if ch.topic == "/nxt/state" and isinstance(body.get("t"), (int, float)):
                    out["state"].append((msg.log_time, body["t"]))
                elif ch.topic == "/nxt/events" and isinstance(body.get("kind"), str):
                    out["events"].append((msg.log_time, body))
            for meta in reader.iter_metadata():
                if meta.name == "nxt_lab.run" and "config" in meta.metadata:
                    out["config"] = json.loads(meta.metadata["config"])
    except Exception:
        pass
    return out


def read_events_log(path: Path) -> list:
    out = []
    try:
        for line in path.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and isinstance(e.get("at"), str) and isinstance(e.get("kind"), str):
                out.append(e)
    except OSError:
        pass
    return out


def read_csv(path: Path) -> tuple:
    """(columns {name: kind}, rows [(t, {name: value}, {port: tacho})]); empty cells are absent."""
    with open(path, newline="") as fh:
        rd = csv.DictReader(fh)
        names = [c for c in (rd.fieldnames or []) if c != "t"]
        raw = list(rd)
    kinds = {c: kind_of(c, [r.get(c) for r in raw]) for c in names}
    rows = []
    for r in raw:
        try:
            t = float(r["t"])
        except (KeyError, TypeError, ValueError):
            continue
        vals = {}
        for c in names:
            v = r.get(c)
            if v in (None, ""):
                continue
            vals[c] = float(v) if kinds[c] == "number" else v
        rows.append((t, vals, {p: vals.get(f"tacho_{p}") for p in TICKS_ABOUT}))
    return kinds, rows


def import_csv(csv_path: Path, data: Path, scene: str = SCENE, say=print, tz: str | None = None, sprocket: float | None = None,
               track: float | None = None, started_at_ns: int | None = None, config_path: Path | None = None) -> Path:
    """One nxt-web recording (run-YYYYMMDD-HHMMSS.csv) into the data folder as the run `nxt/<scene>/<name>`; its path."""
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise SystemExit(f"no {csv_path}")
    try:
        key = keys.make_key(ROBOT, scene, csv_path.stem.lower())
    except ValueError as e:
        raise SystemExit(f"cannot import {csv_path}: {e}") from None
    out_dir = keys.run_dir(data, key)
    kinds, rows = read_csv(csv_path)
    old = read_old_mcap(csv_path.with_suffix(".mcap")) if csv_path.with_suffix(".mcap").exists() else {"state": [], "events": [], "config": None}
    cfg_path = config_path or csv_path.resolve().parent.parent / "config.json"
    try:
        file_cfg = json.loads(cfg_path.read_text())
    except (OSError, ValueError):
        file_cfg = None
    # The motor mapping is the recording's own (its MCAP carried the config), the wheel geometry is the robot's: the
    # recording's when it has one, else the config file's.
    cfg, cfg_source = (old["config"], "recording") if old["config"] else (file_cfg, cfg_path.name)
    if geometry_from(cfg, cfg_source) is None and geometry_from(file_cfg, cfg_path.name):
        cfg = dict(cfg or {}, odom_sprocket_diameter_m=file_cfg["odom_sprocket_diameter_m"],
                   odom_track_width_m=file_cfg["odom_track_width_m"])
        cfg_source = cfg_path.name
    geometry = geometry_from(cfg, cfg_source, sprocket, track)
    if geometry is None and (sprocket is not None or track is not None):
        raise SystemExit("both --sprocket-diameter and --track-width are needed, and above zero")
    logs = [e for p in ("events.jsonl", "events-fake.jsonl") for e in read_events_log(csv_path.parent / p)]

    named = time_in_name(csv_path.name)
    if started_at_ns is not None:
        started, started_src = started_at_ns, "given"
    elif old["state"]:
        log_ns, t0 = old["state"][0]
        started, started_src = log_ns - round(t0 * 1e9), "source_clock"
    elif named:
        started, started_src = local_ns(named, tz), "file_name"
        mark = next((e for e in logs if e["kind"] == "record start" and 0 <= _at_ns(e, tz) - started < 1.5e9), None)
        if mark:                                    # the command log's own "record start" is ms from the real start: the name only has seconds
            started, started_src = _at_ns(mark, tz), "record_start_event"
    else:
        started, started_src = csv_path.stat().st_mtime_ns, "file_mtime"
    end_s = rows[-1][0] if rows else 0.0

    if old["events"]:
        events = [event_record(e, max(0.0, (ns - started) / 1e9)) for ns, e in old["events"]]
    else:
        lo, hi = -TOLERANCE_S, end_s + TOLERANCE_S
        events = [event_record(e, max(0.0, (_at_ns(e, tz) - started) / 1e9)) for e in logs if lo <= (_at_ns(e, tz) - started) / 1e9 <= hi]
    events.sort(key=lambda r: r[0])

    sha = sha256_of(csv_path)
    run = run_record(key, started, started_src, kinds, geometry, {"name": csv_path.name, "sha256": sha},
                     str(uuid.uuid5(UUID_NAMESPACE, f"{key}:{sha}")))
    try:
        rec = Recorder(out_dir, run)
    except WriterBusy as e:
        raise SystemExit(f"cannot import {csv_path}: {e}") from None
    header(rec, geometry)
    odom = Odometry(geometry) if geometry else None
    pending = iter(events)
    nxt = next(pending, None)
    for t, vals, tacho in rows:
        while nxt is not None and nxt[0] <= t:
            rec.add(*nxt)
            nxt = next(pending, None)
        write_sample(rec, t, vals, odom, tacho)
    while nxt is not None:
        rec.add(*nxt)
        nxt = next(pending, None)
    (out_dir / "source").mkdir(exist_ok=True)
    shutil.copyfile(csv_path, out_dir / "source" / csv_path.name)
    if csv_path.with_suffix(".mcap").exists():
        shutil.copyfile(csv_path.with_suffix(".mcap"), out_dir / "source" / csv_path.with_suffix(".mcap").name)
    elif events:
        (out_dir / "source" / "events.jsonl").write_text("".join(json.dumps(r[2]["raw"] | {"kind": r[2]["kind"]}) + "\n" for r in events))
    rec.add(rec.last_t, "end", {"verdict": "recorded" if rows else "empty", "source_sha256": sha})
    rec.close()
    say(f"{key}: {len(rows)} samples, {len(events)} events, "
        f"{'pose from the tracks (' + geometry.source + ')' if geometry else 'no pose'}, started {started_src} -> {out_dir / FINAL}")
    return out_dir / FINAL


def _at_ns(entry: dict, tz: str | None) -> int:
    try:
        return local_ns(datetime.fromisoformat(entry["at"]), tz)
    except ValueError:
        return 0
