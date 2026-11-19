"""The LEGO NXT's runs in format 2 (ADR-0013): the signals message and the tick protocol's signals tick, validation, the odometry
math, `miniview import --robot nxt` on the two real recordings (fixtures/nxt: their CSVs, the old MCAP, the command log), the
catalog and the API for a run of a scene with no layout, and a run written live.
Run: cd viewer && uv run python tests/test_nxt.py"""

import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from mcap.reader import make_reader

from helpers import Checks, catalog, get, serve, wait_until
from runfile import keys, mcapio, signals, validate, wire
from runfile.adapters import nxt
from runfile.mcapio import Recorder
from runfile.store import RunData, build

check = Checks("NXT")
FIX = Path(__file__).resolve().parent / "fixtures" / "nxt"
CSV_A, CSV_B = "run-20261114-094243", "run-20261114-145402"      # the first has no MCAP and no events in its time; the second has both


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return str(e) or True
    return False


DECL = [{"name": "power_left", "kind": "number", "unit": "%"}, {"name": "s4_ultrasonic", "kind": "number", "unit": "cm"},
        {"name": "s3_color_name", "kind": "text"}]


def mini_run(key="nxt/unmapped/t1", decl=DECL, **kw):
    return mcapio.new_run(key, {"name": "nxt", "radius": 0.1, "height": 0.1}, "unmapped", "recording", 1_700_000_000 * 10**9,
                          "writer", signals=decl, **kw)


# ---- the signals message ---------------------------------------------------------------------------------------
ss = signals.SignalSet(DECL, "nxt")
got = ss.decode(ss.encode({"power_left": 0.0, "s3_color_name": "blue"}))
check("a signals message round-trips, and a value of 0 is present while one not given is absent",
      got == {"power_left": 0.0, "s3_color_name": "blue"} and "s4_ultrasonic" not in got, got)
check("a message names a signal that is not declared, a number that is not finite, or text for a number: refused",
      all(raises(ValueError, ss.encode, v) for v in ({"x": 1}, {"power_left": math.nan}, {"power_left": "a"}, {"s3_color_name": 3}, {"power_left": True})))
check("a declaration needs distinct names that are identifiers, and a known kind",
      all(signals.check_decl(d) for d in ([], [{"name": "a b", "kind": "number"}], [{"name": "a", "kind": "number"}, {"name": "a", "kind": "text"}],
                                          [{"name": "a", "kind": "blob"}], [{"name": "1a", "kind": "number"}]))
      and signals.check_decl(DECL) is None)

# ---- validation (ADR-0008) -------------------------------------------------------------------------------------
bad = {"empty": {"values": {}}, "no values": {}, "nan": {"values": {"a": math.nan}}, "inf": {"values": {"a": math.inf}},
       "a list": {"values": [1, 2]}, "a bool": {"values": {"a": True}}, "a null": {"values": {"a": None}}, "an object": {"values": {"a": {}}}}
check("a signals record is checked: values is a non-empty object of finite numbers and text",
      validate.check(1.0, "signals", {"values": {"a": 1.5, "b": "text"}}, 0.0) is None
      and all(validate.check(1.0, "signals", p, 0.0) for p in bad.values()), [k for k, p in bad.items() if not validate.check(1.0, "signals", p, 0.0)])
check("the run record's signals, odometry and no_pose are checked",
      validate.check(0.0, "run", mini_run(), 0.0) is None and validate.check(0.0, "run", dict(mini_run(), signals=[{"name": "!", "kind": "number"}]), 0.0)
      and validate.check(0.0, "run", dict(mini_run(), no_pose=3), 0.0) and validate.check(0.0, "run", dict(mini_run(), odometry="x"), 0.0))
d = RunData()
d.feed(0.0, "run", mini_run())
ok = d.feed(1.0, "signals", {"values": {"power_left": 50.0}})
undeclared = d.feed(2.0, "signals", {"values": {"nope": 1.0}})
wrong = d.feed(3.0, "signals", {"values": {"power_left": "fast"}})
check("a value of a signal the run did not declare, or of the wrong kind, is rejected and counted; a good one is kept",
      ok and not undeclared and not wrong and d.run["rejects"] == 2 and d.run["samples"] == 1 and "not declared" in d.run["first_error"], d.run["first_error"])
check("a run with signals and no pose is built with the stream list: one stream per signal, the pose streams missing with the reason",
      (lambda r, s: r["samples"] == 1 and s["signals.power_left"]["count"] == 1 and s["signals.s4_ultrasonic"]["missing"]
       and s["signals.power_left"]["unit"] == "%" and s["signals.s3_color_name"]["kind"] == "text"
       and s["belief.pose"]["missing"] and s["belief.pose"]["why"] == "not in this run")(build([(0.0, "run", mini_run()), (1.0, "signals", {"values": {"power_left": 5.0}})]).run,
          {x["id"]: x for x in build([(0.0, "run", mini_run()), (1.0, "signals", {"values": {"power_left": 5.0}})]).run["streams"]}))
check("the reason a run has no pose is the one its record gives",
      {x["id"]: x for x in build([(0.0, "run", mini_run(no_pose="no wheel geometry")), (1.0, "signals", {"values": {"power_left": 5.0}})]).run["streams"]}["belief.pose"]["why"] == "no wheel geometry")

# ---- the signals tick in the file -------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    rec = Recorder(keys.run_dir(data, "nxt/unmapped/t1"), mini_run())
    rec.begin_signals(1.0, {"power_left": 50.0, "s3_color_name": "blue"}, t_src=1.0)
    check("a signals tick stays open until end_tick: nothing else may be written in it",
          raises(ValueError, rec.add, 1.1, "event", {"kind": "k", "text": "t"}) and raises(ValueError, rec.begin_signals, 1.1, {"power_left": 1.0})
          and raises(ValueError, rec.begin_tick, 1.1, [0, 0, 0]) and raises(ValueError, rec.tick_truth, [0, 0, 0]))
    rec.end_tick({})
    rec.add(1.0, "signals", {"values": {"power_left": 51.0}})
    rec.begin_tick(1.5, [0.1, 0.0, 0.0], t_src=1.5)
    check("a signals tick cannot start inside a pose tick", raises(ValueError, rec.begin_signals, 1.5, {"power_left": 1.0}))
    rec.end_tick({})
    rec.begin_signals(1.5, {"s4_ultrasonic": 30.0})
    check("after a signals tick has begun no pose part is accepted in it", raises(ValueError, rec.tick_depth, []))
    rec.end_tick({})
    rec3 = Recorder(keys.run_dir(data, "nxt/unmapped/t3"), mini_run("nxt/unmapped/t3"))
    check("a value that cannot be encoded raises before anything is written, and leaves no tick open (the next one is written)",
          raises(ValueError, rec3.begin_signals, 2.0, {"nope": 1.0}) and raises(Exception, rec3.begin_tick, 2.0, ["x", 0, 0])
          and rec3.add(2.0, "signals", {"values": {"power_left": 1.0}}) is None)
    rec3.close()
    nosig = Recorder(keys.run_dir(data, "nxt/unmapped/t2"), mini_run("nxt/unmapped/t2", decl=None))
    check("begin_signals in a run that declares no signals is refused", raises(ValueError, nosig.begin_signals, 1.0, {"a": 1.0}))
    nosig.close()
    final = rec.close()
    with open(final, "rb") as fh:
        everything = list(make_reader(fh).iter_messages())
    chans = {c.topic: (c, s) for s, c, _ in everything}
    raw = [(c.topic, m) for _, c, m in everything]
    ch, sch = chans["/nxt/signals"]
    check("the signals travel on /<robot>/signals as protobuf with the message's own descriptor set (schema miniview.Signals)",
          ch.message_encoding == "protobuf" and sch.encoding == "protobuf" and sch.name == "miniview.Signals")
    # a reader that knows nothing of miniview: the descriptor in the file is enough to decode every value by name
    fds = descriptor_pb2.FileDescriptorSet.FromString(sch.data)
    pool = descriptor_pool.DescriptorPool()
    for f in fds.file:
        pool.Add(f)
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("miniview.Signals"))
    msg = cls.FromString(next(m.data for t, m in raw if t == "/nxt/signals"))
    check("the descriptor in the file decodes a signals message with plain protobuf (no miniview): values by name, absent ones absent",
          msg.power_left == 50.0 and msg.s3_color_name == "blue" and not msg.HasField("s4_ultrasonic"), str(msg))
    topics = [t for t, _ in raw]
    i = topics.index("/nxt/signals")
    check("a signals tick is the signals message then tick_extra, and a pose tick (belief, tick_extra) is a tick of its own",
          topics[i + 1] == "/miniview/tick_extra" and topics.count("/nxt/signals") == 3 and topics.count("/belief/pose") == 1, topics)
    recs = mcapio.read(final.parent)
    kinds = [(round(t, 3), k) for t, k, _ in recs]
    check("the reader returns the records in order: run, signals, signals, tick, signals, end",
          kinds == [(0.0, "run"), (1.0, "signals"), (1.0, "signals"), (1.5, "tick"), (1.5, "signals"), (1.5, "end")], kinds)
    check("the values come back as written, and only the signals a tick carried",
          recs[1][2]["values"] == {"power_left": 50.0, "s3_color_name": "blue"} and recs[4][2]["values"] == {"s4_ultrasonic": 30.0})

# an interrupted signals tick is dropped and counted, as a pose tick is (the tick protocol, rule 4)
asm = wire.Assembler()
base = 1_700_000_000 * 10**9
run0 = mini_run()
out = asm.feed("/miniview/run", base, json.dumps(run0).encode())
sg = wire.signal_set(run0)
out = asm.feed(sg.topic, base + 10**9, sg.encode({"power_left": 1.0})) + asm.feed("/miniview/event", base + 2 * 10**9, b'{"kind":"k","text":"t"}')
check("a signals message that another record interrupts is dropped and counted, the other record still read",
      asm.partials == 1 and [k for _, k, _ in out] == ["event"] and "interrupted" in asm.drain()[0])

# ---- the odometry ---------------------------------------------------------------------------------------------
G = nxt.Geometry(sprocket_diameter_m=0.05, track_width_m=0.10)
o = nxt.Odometry(G)
o.step({"C": 100, "B": 100})
x, y, yaw = o.step({"C": 100 + 720, "B": 100 + 720})
check("odometry, straight: two turns of a 5 cm sprocket is 2 pi D = 0.3142 m, no turn",
      abs(x - 2 * math.pi * 0.05) < 1e-9 and abs(y) < 1e-12 and abs(yaw) < 1e-12, (x, y, yaw))
o = nxt.Odometry(G)
o.step({"C": 0, "B": 0})
x, y, yaw = o.step({"C": -360, "B": 360})
check("odometry, a spin in place: the right track forward and the left back by half a turn of the sprocket turns the robot by pi, counter-clockwise, on the spot",
      abs(x) < 1e-12 and abs(y) < 1e-12 and abs(abs(yaw) - math.pi) < 1e-9, (x, y, yaw))
o = nxt.Odometry(G)
o.step({"C": 0, "B": 0})
x, y, yaw = o.step({"C": -180, "B": 180})
check("odometry, a quarter spin to the left: yaw +pi/2 (the right track ahead of the left one), on the spot",
      abs(yaw - math.pi / 2) < 1e-9 and abs(x) < 1e-12 and abs(y) < 1e-12, (x, y, yaw))
o = nxt.Odometry(G)
o.step({"C": 0, "B": 0})
for k in range(1, 201):                                   # a quarter circle of radius 0.15 m, in 200 steps: left 360 deg, right 720 deg in all
    x, y, yaw = o.step({"C": 360 * k / 200, "B": 720 * k / 200})
check("odometry, an arc: left 360 deg and right 720 deg of a 5 cm sprocket on a 10 cm track is a quarter circle of radius 0.15 m",
      abs(x - 0.15) < 2e-3 and abs(y - 0.15) < 2e-3 and abs(yaw - math.pi / 2) < 1e-6, (x, y, yaw))
o = nxt.Odometry(nxt.Geometry(0.05, 0.10, invert_left=True))
o.step({"C": 0, "B": 0})
x, y, yaw = o.step({"C": -720, "B": 720})
check("odometry, an inverted left motor counts backwards when the robot goes forward: the same straight line", abs(x - 2 * math.pi * 0.05) < 1e-9 and abs(yaw) < 1e-12, (x, y, yaw))
o = nxt.Odometry(G)
o.step({"C": 0, "B": 0})
p1 = o.step({"C": 360, "B": None})
p2 = o.step({"C": 360, "B": 360})
check("a sample with no count for a track holds the pose, and the next one takes the whole distance since the last good count",
      p1 == (0.0, 0.0, 0.0) and abs(p2[0] - math.pi * 0.05) < 1e-9, (p1, p2))
check("without both a diameter and a width above zero there is no geometry",
      nxt.geometry_from({}, "x") is None and nxt.geometry_from({"odom_sprocket_diameter_m": 0.05}, "x") is None
      and nxt.geometry_from({"odom_sprocket_diameter_m": 0.05, "odom_track_width_m": 0}, "x") is None
      and nxt.geometry_from({"odom_sprocket_diameter_m": 0.05, "odom_track_width_m": 0.1}, "config.json").source == "config.json")

# ---- the import: both real recordings -----------------------------------------------------------------------------
IMPORT_TZ = "Europe/Zurich"
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    shutil.copytree(FIX, Path(tmp) / "nxt")
    runs = Path(tmp) / "nxt" / "runs"
    for name in (CSV_A, CSV_B):
        nxt.import_csv(runs / f"{name}.csv", data, tz=IMPORT_TZ, say=lambda *_: None)
    cat = catalog(data)
    cat.scan()
    dirs = {name: keys.run_dir(data, f"nxt/unmapped/{name}") for name in (CSV_A, CSV_B)}
    check("an import leaves run.mcap and source/ (the CSV; the old MCAP when there is one) in the run's folder, whose key is nxt/unmapped/<name>",
          all(sorted(p.name for p in d.iterdir()) == ["run.mcap", "source"] for d in dirs.values())
          and (dirs[CSV_B] / "source" / f"{CSV_B}.csv").read_bytes() == (runs / f"{CSV_B}.csv").read_bytes()
          and (dirs[CSV_B] / "source" / f"{CSV_B}.mcap").exists() and not (dirs[CSV_A] / "source" / f"{CSV_A}.mcap").exists())
    for name in (CSV_A, CSV_B):
        ld = cat.get(f"nxt/unmapped/{name}")
        run = ld.data.run
        header = (FIX / "runs" / f"{name}.csv").read_text().splitlines()[0].split(",")
        rows = len((FIX / "runs" / f"{name}.csv").read_text().splitlines()) - 1
        sig = ld.data.sig
        every_column = [c for c in header if c != "t"]
        landed = all(sum(v is not None for v in sig["v"][c]) == rows for c in every_column if c != "program") if name == CSV_B else True
        check(f"{name}: every CSV column is a signal, one sample per row, the times are the CSV's, no rejects",
              [d["name"] for d in run["signals"]] == every_column and run["samples"] == rows and len(sig["t"]) == rows and run["rejects"] == 0 and landed,
              (run["samples"], rows, run["rejects"], run["first_error"]))
        csv_t = [float(line.split(",")[0]) for line in (FIX / "runs" / f"{name}.csv").read_text().splitlines()[1:]]
        check(f"{name}: the sample times are the CSV's t, the values are the CSV's", sig["t"] == csv_t and sig["v"]["power_left"][0] == float((FIX / "runs" / f"{name}.csv").read_text().splitlines()[1].split(",")[1]))
        kinds = {d["name"]: d["kind"] for d in run["signals"]}
        check(f"{name}: the colour name and the program are text, the rest numbers, with units",
              kinds["s3_color_name"] == "text" and kinds["program"] == "text" and kinds["tacho_B"] == "number" and kinds["s3_color"] == "number"
              and {d["name"]: d.get("unit") for d in run["signals"]}["s4_ultrasonic"] == "cm", kinds)
        check(f"{name}: key, scene, robot, kind, no pose and the reason, the source's SHA-256",
              run["key"] == f"nxt/unmapped/{name}" and run["scene"] == "unmapped" and run["robot"]["name"] == "nxt" and run["kind"] == "recording"
              and run["ticks"] == 0 and run["no_pose"].startswith("no wheel geometry (set odom_sprocket_diameter_m and odom_track_width_m)")
              and run["source"]["sha256"] == nxt.sha256_of(runs / f"{name}.csv") and run["verdict"] == "recorded", run.get("no_pose"))
    a, b = cat.get(f"nxt/unmapped/{CSV_A}").data.run, cat.get(f"nxt/unmapped/{CSV_B}").data.run
    # started_at: a recording with its MCAP has the source's own clock (exact); one with only its file name has the name's time, local to the machine
    ns_a = nxt.local_ns(nxt.time_in_name(f"{CSV_A}.csv"), IMPORT_TZ)
    check("started_at of a recording with no other clock is the file name's time, local to the zone given (Europe/Zurich, UTC+1 in November), whole seconds",
          a["started_at_ns"] == ns_a == 1794645763 * 10**9 and a["started_at_source"] == "file_name", (a["started_at_ns"], a["started_at_source"]))
    state = [(m.log_time, json.loads(m.data)["t"]) for s, c, m in make_reader(open(FIX / "runs" / f"{CSV_B}.mcap", "rb")).iter_messages() if c.topic == "/nxt/state"][0]
    check("started_at of a recording with its old MCAP is that file's own clock: the first state's log time minus its t, to the nanosecond",
          b["started_at_ns"] == state[0] - round(state[1] * 1e9) and b["started_at_source"] == "source_clock", (b["started_at_ns"], b["started_at_source"]))
    check("the file name's time, read as UTC+1, matches the source clock to the second: the name's zone is the machine's and the choice is right for these",
          abs(b["started_at_ns"] - nxt.local_ns(nxt.time_in_name(f"{CSV_B}.csv"), IMPORT_TZ)) < 1.2e9)
    ev = [(e["t"], e["kind"]) for e in b["events"]]
    check("the events of the old MCAP are there, in order, from the run's time zero (record start, then the drives and stops)",
          ev and ev[0][1] == "record start" and ev == sorted(ev) and any(k == "drive" for _, k in ev) and len(ev) == 6, ev)
    check("the events log (events.jsonl) has nothing in the first recording's time, and the importer says so by having no events", a["events"] == [])
    check("signals presence: the run's span is the CSV's, with the last event inside it",
          b["t0"] == 0.0 and abs(b["t1"] - 6.491) < 1e-9 and max(t for t, _ in ev) <= b["t1"], (b["t0"], b["t1"]))

    # the events of a recording with no MCAP come from the command log by time, and its `record start` is the exact start
    only_csv = Path(tmp) / "only" / "runs"
    only_csv.mkdir(parents=True)
    shutil.copy(runs / f"{CSV_B}.csv", only_csv)
    entries = [e for _, e in nxt.read_old_mcap(runs / f"{CSV_B}.mcap")["events"]]
    log_lines = [{"seq": 1, "at": "2026-11-14T14:50:00.000", "kind": "connect", "ok": True}] + [
        {k: v for k, v in e.items()} for e in entries] + [{"seq": 99, "at": "2026-11-14T15:30:00.000", "kind": "late", "ok": True}]
    (only_csv / "events.jsonl").write_text("".join(json.dumps(x) + "\n" for x in log_lines))
    d2 = Path(tmp) / "data2"
    nxt.import_csv(only_csv / f"{CSV_B}.csv", d2, tz=IMPORT_TZ, say=lambda *_: None)
    r2 = catalog(d2).get(f"nxt/unmapped/{CSV_B}").data.run
    check("with only a command log: the events in the recording's time are taken by their clock, the ones far outside are not, and `record start` fixes the start to the millisecond",
          [e["kind"] for e in r2["events"]] == [e["kind"] for e in b["events"]] and r2["started_at_source"] == "record_start_event"
          and abs(r2["started_at_ns"] - b["started_at_ns"]) < 2e6 and all(abs(x["t"] - y["t"]) < 2e-3 for x, y in zip(r2["events"], b["events"])),
          (r2["started_at_source"], [e["kind"] for e in r2["events"]]))

    # ---- the catalog and the API for a scene with no layout -------------------------------------------------------
    sc = cat.scenes_with_runs()["scenes"]
    check("the scene `unmapped` is listed with its runs although no scenes/unmapped/scene.json exists",
          [s["id"] for s in sc] == ["unmapped"] and len(sc[0]["runs"]) == 2 and sc[0]["kind"] == "no layout" and cat.scene("unmapped") is None, sc[0]["kind"])
    httpd, base = serve(cat, follow=False)
    code, runj, _ = get(base, f"/api/v1/runs/nxt/unmapped/{CSV_B}")
    check("GET run: samples, the declared signals, no ticks, the reason for no pose, one stream per signal",
          code == 200 and runj["samples"] == 13 and runj["ticks"] == 0 and len(runj["signals"]) == 9
          and {s["id"] for s in runj["streams"] if s["id"].startswith("signals.")} == {f"signals.{d['name']}" for d in runj["signals"]}
          and next(s for s in runj["streams"] if s["id"] == "belief.pose")["why"].startswith("no wheel geometry"))
    code, w, _ = get(base, f"/api/v1/runs/nxt/unmapped/{CSV_B}/signals")
    check("GET signals: the samples whole, columnar, with their index in the run", code == 200 and w["i0"] == 0 and w["n"] == 13 and len(w["t"]) == 13
          and w["v"]["power_left"][0] == 50.0 and w["v"]["s3_color_name"][0] == "blue")
    code, w, _ = get(base, f"/api/v1/runs/nxt/unmapped/{CSV_B}/signals?from=2.5&to=3.5")
    check("GET signals?from=&to= is a window, i0 its first sample's number", code == 200 and w["t"] == [2.991, 3.491] and w["i0"] == 5, (w["t"], w["i0"]))
    code, _, _ = get(base, f"/api/v1/runs/nxt/unmapped/{CSV_B}/signals?from=5&to=1")
    check("GET signals with from after to is a 400", code == 400)
    code, pr, _ = get(base, f"/api/v1/runs/nxt/unmapped/{CSV_B}/presence")
    check("GET presence has a row for each signal with data", code == 200 and all(f"signals.{n}" in pr["streams"] for n in ("power_left", "tacho_A", "s3_color_name"))
          and pr["streams"]["signals.power_left"]["spans"] == [[0.49, 6.491]] and "signals.program" in pr["streams"], pr["streams"].get("signals.power_left"))
    code, st, _ = get(base, f"/api/v1/runs/nxt/unmapped/{CSV_B}/state?t=2.6")
    check("GET state at t: the sample at or before it, with every signal's value, and no pose",
          code == 200 and st["tick"] is None and st["signals"]["t"] == 2.491 and st["signals"]["values"]["tacho_C"] == 1077.0
          and st["signals"]["values"]["s3_color_name"] == "green", st)
    code, sc_ = get(base, "/api/v1/scenes/unmapped")[:2]
    check("GET scenes/unmapped is a 404 (there is no scene to draw)", code == 404)
    code, frames, _ = get(base, f"/api/v1/runs/nxt/unmapped/{CSV_B}/frames")
    check("GET frames of a run with no pose is an empty window, not an error", code == 200 and frames["t"] == [] and frames["ticks"] == 0)
    httpd.shutdown()

    # ---- the command line ----------------------------------------------------------------------------------------
    d3 = Path(tmp) / "data3"
    py = [sys.executable, "-m", "miniview.cli", "--data", str(d3)]
    env = {"MINIVIEW_INDEX": str(Path(tmp) / "cli.sqlite"), "PATH": "/usr/bin:/bin"}
    r = subprocess.run(py + ["import", "--robot", "nxt", "--tz", IMPORT_TZ, "--sprocket-diameter", "0.043", "--track-width", "0.12",
                             str(runs / f"{CSV_B}.csv")], capture_output=True, text=True, env=env)
    check("miniview import --robot nxt <csv> imports into scene unmapped, and says what it did", r.returncode == 0 and "pose from the tracks (command line)" in r.stdout
          and (d3 / "runs" / "nxt" / "unmapped" / CSV_B / "run.mcap").exists(), r.stdout + r.stderr)
    r = subprocess.run(py + ["state", CSV_B, "--at", "2.6"], capture_output=True, text=True, env=env)
    check("miniview state of an NXT run with a pose prints the pose and the signals at t", r.returncode == 0 and "tick" in r.stdout and "signals at 2.49 s (sample 5 of 13)" in r.stdout
          and "tacho_C 1077.0" in r.stdout and "s3_color_name green" in r.stdout, r.stdout + r.stderr)
    r = subprocess.run(py + ["--data", str(data), "state", CSV_B, "--at", "2.6"], capture_output=True, text=True, env=env)
    check("and of one with no pose says why there is none, then the signals and the last event", r.returncode == 0 and "no pose: no wheel geometry" in r.stdout
          and "signals at 2.49 s" in r.stdout and "last event" in r.stdout, r.stdout + r.stderr)
    r = subprocess.run(py + ["import", "--robot", "nxt", "--sprocket-diameter", "0.043", str(runs / f"{CSV_A}.csv")], capture_output=True, text=True, env=env)
    check("only one of the two geometry values is refused", r.returncode != 0 and "both" in (r.stdout + r.stderr))
    r = subprocess.run(py + ["import", "--robot", "nxt", str(runs / f"{CSV_B}.csv")], capture_output=True, text=True, env=env)
    check("importing the same recording again is refused (the run exists)", r.returncode != 0 and "already exists" in (r.stdout + r.stderr), r.stdout + r.stderr)

    # ---- with the wheel geometry: a pose, from the tachos --------------------------------------------------------
    cfg = json.loads((FIX / "config.json").read_text())
    (Path(tmp) / "nxt" / "config.json").write_text(json.dumps(dict(cfg, odom_sprocket_diameter_m=0.043, odom_track_width_m=0.12)))
    d4 = Path(tmp) / "data4"
    nxt.import_csv(runs / f"{CSV_B}.csv", d4, tz=IMPORT_TZ, say=lambda *_: None)
    ld = catalog(d4).get(f"nxt/unmapped/{CSV_B}")
    run4, fr = ld.data.run, ld.data.frames
    check("with the geometry in the config beside the recordings (the recording's own MCAP has none): a pose per sample, recorded with its source",
          run4["ticks"] == 13 and run4["samples"] == 13 and run4.get("no_pose") is None
          and run4["odometry"] == {"sprocket_diameter_m": 0.043, "track_width_m": 0.12, "left": "C", "right": "B", "invert_left": False, "invert_right": False,
                                   "source": "config.json"}, run4.get("odometry"))
    check("the pose starts at the origin (the first sample), the first four samples (50% straight: B and C each +225 deg) advance by 225/360*pi*0.043 m each",
          fr["belief"][0] == [0.0, 0.0, 0.0] and abs(fr["belief"][1][0] - 225 / 360 * math.pi * 0.043) < 1e-4 and abs(fr["belief"][1][1]) < 1e-4, fr["belief"][:2])
    check("the spin in the recording (left forward, right back: 40/-40) turns the robot clockwise, on the spot", fr["belief"][5][2] < -1.5 and abs(fr["belief"][5][0] - fr["belief"][3][0]) < 0.02, fr["belief"][3:6])
    check("the belief pose is in the map frame, and there is one identity epoch (no scene to place it in)",
          run4["epochs"] == [{"from_t": 0.0, "map_to_world": [0.0, 0.0, 0.0]}])
    check("a pose tick and the signals tick of one sample share its time: signals are in the same instants as the poses", ld.data.sig["t"] == fr["t"])
    s4 = {s["id"]: s for s in run4["streams"]}
    check("with a pose the pose streams are present, and the signals too", not s4["belief.pose"]["missing"] and not s4["signals.tacho_B"]["missing"])
    d5 = Path(tmp) / "data5"
    nxt.import_csv(runs / f"{CSV_B}.csv", d5, tz=IMPORT_TZ, sprocket=0.05, track=0.10, say=lambda *_: None)
    r5 = catalog(d5).get(f"nxt/unmapped/{CSV_B}").data.run
    check("a geometry given on the command line wins over the config's, and says so", r5["odometry"]["sprocket_diameter_m"] == 0.05 and r5["odometry"]["source"] == "command line")

# ---- a run written live (what nxt-web does) -----------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    cols = {"power_left": "number", "tacho_B": "number", "tacho_C": "number", "s3_color_name": "text", "program": "text"}
    g = nxt.Geometry(0.043, 0.12, source="config")
    run = nxt.run_record("nxt/unmapped/run-20261116-100000", 1_700_000_000 * 10**9, "writer", cols, g)
    rec = Recorder(keys.run_dir(data, "nxt/unmapped/run-20261116-100000"), run)
    nxt.header(rec, g)
    odom = nxt.Odometry(g)
    cat = catalog(data)
    cat.scan()
    ld = cat.get("nxt/unmapped/run-20261116-100000")
    check("a run being written is live in the catalog before it has a sample", cat.status(ld) == "live" and ld.data.run["samples"] == 0)
    for i in range(5):
        nxt.write_sample(rec, 0.2 * i, {"power_left": 50, "tacho_B": 90 * i, "tacho_C": 90 * i, "s3_color_name": "blue", "program": ""}, odom, {"B": 90 * i, "C": 90 * i})
    cat.follow_once()
    check("the samples show in the catalog as they are written (one flush per tick), the empty value absent",
          ld.data.run["samples"] == 5 and ld.data.run["ticks"] == 5 and ld.data.sig["v"]["program"] == [None] * 5 and ld.data.run["status"] == "live", (ld.data.run["samples"], ld.data.run["ticks"]))
    httpd, base = serve(cat, follow=False)
    code, w, _ = get(base, "/api/v1/runs/nxt/unmapped/run-20261116-100000/signals")
    check("the API serves a live run's samples so far", code == 200 and w["n"] == 5 and len(w["t"]) == 5)
    httpd.shutdown()
    nxt.write_sample(rec, 1.0, {"power_left": 0, "tacho_B": 360, "tacho_C": 360, "s3_color_name": "red"}, odom, {"B": 360, "C": 360})
    rec.close()
    cat.follow_once()
    wait_until(lambda: ld.data.run["status"] == "ended" or ld.follower.done, 5, what="the compacted run")
    check("compaction at the end: run.mcap, no live file or lock, the same samples, the end record", (keys.run_dir(data, "nxt/unmapped/run-20261116-100000") / "run.mcap").exists()
          and not (keys.run_dir(data, "nxt/unmapped/run-20261116-100000") / "run.live.mcap").exists() and ld.data.run["samples"] == 6 and ld.data.run["verdict"] == "ended")

check.done()
