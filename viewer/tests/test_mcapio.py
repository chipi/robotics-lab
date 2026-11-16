"""Runs as MCAP, format 2 (ADR-0006, ADR-0007): identity, the writer's lock and flush, absolute time, segments,
Foxglove shapes, nothing dropped, compaction and repair, on explore9 (a real run's log) and on small runs.
Run: cd viewer && uv run python tests/test_mcapio.py"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcap.reader import make_reader

from helpers import FIXTURE, T0_NS, Checks, import_fixture, make_run, run_record, tick
from miniview import cli, keys, mcapio, schemas, wire
from miniview.importer import sha256_of
from miniview.mcapio import Follower, Recorder, WriterBusy
from miniview.store import build

check = Checks("MCAPIO")


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return str(e) or True
    return False


def messages(path):
    with open(path, "rb") as fh:
        r = make_reader(fh)
        return [(ch.topic, sc.name, m) for sc, ch, m in r.iter_messages()]


# ---- identity (ADR-0006) -------------------------------------------------------------------------------------
check("a key is robot/scene/run, each part lower case, digits, - and _",
      keys.split_key("duck/apartment/phase1-run18") == ("duck", "apartment", "phase1-run18")
      and all(raises(ValueError, keys.split_key, k) for k in ("duck/apartment", "Duck/a/b", "a/b/c d", "a/b/c/d", "a//c", "../a/b")))

with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    run = import_fixture(data)
    final = run / "run.mcap"
    msgs = messages(final)
    first = msgs[0][2]
    rec0 = json.loads(first.data)
    src_lines = [json.loads(line) for line in (FIXTURE / "ticks.jsonl").read_text().splitlines()]

    check("an import leaves run.mcap and source/, no live file or lock",
          sorted(p.name for p in run.iterdir()) == ["run.mcap", "source"], sorted(p.name for p in run.iterdir()))
    check("the run record is first: format 2, key, uuid, robot, writer, wall-clock start with its origin",
          msgs[0][0] == "/miniview/run" and rec0["format"] == 2 and rec0["key"] == "duck/apartment/explore9"
          and len(rec0["uuid"]) == 36 and rec0["robot"]["name"] == "duck" and rec0["writer"]["program"] == "miniview"
          and rec0["started_at_ns"] == T0_NS and rec0["started_at_source"] == "given", rec0)
    check("the source log is copied beside the run and its SHA-256 recorded",
          (run / "source" / "ticks.jsonl").read_bytes() == (FIXTURE / "ticks.jsonl").read_bytes()
          and rec0["source"] == {"name": "ticks.jsonl", "sha256": sha256_of(FIXTURE / "ticks.jsonl")}, rec0["source"])
    run2 = import_fixture(Path(tmp) / "data2")
    check("the same source imported again keeps its uuid",
          json.loads(messages(run2 / "run.mcap")[0][2].data)["uuid"] == rec0["uuid"])

    # ---- absolute time, publish time = the source's clock ------------------------------------------------------
    ticks = [m for m in msgs if m[0] == "/belief/pose"]
    check("log_time is absolute: the run's start plus t (not 1970)", first.log_time == T0_NS
          and all(m.log_time >= T0_NS for _, _, m in msgs), (first.log_time, T0_NS))
    src_ticks = [r for r in src_lines if "pose" in r and "event" not in r]
    check("publish_time is the source's own clock, and t_src is kept per tick",
          len(ticks) == len(src_ticks) and all(abs(m.publish_time / 1e9 - r["t"]) < 1e-6 for (_, _, m), r in zip(ticks, src_ticks)),
          len(ticks))

    # ---- the file: standard shapes, schemas, compaction --------------------------------------------------------
    with open(final, "rb") as fh:
        r = make_reader(fh)
        summ = r.get_summary()
        topics = {ch.topic: summ.schemas[ch.schema_id].name for ch in summ.channels.values()}
        chunks = summ.chunk_indexes
        stats = summ.statistics
    check("Foxglove schemas on the standard shapes, miniview.* on ours",
          topics["/belief/pose"] == "foxglove.PoseInFrame" and topics["/truth/pose"] == "foxglove.PoseInFrame"
          and topics["/tf"] == "foxglove.FrameTransform" and topics["/map"] == "foxglove.Grid"
          and topics["/depth"] == "foxglove.PointCloud" and all(topics[t] == wire.CHANNELS[t] for t in topics), topics)
    # explore9 has no raw frames: an empty /depth/raw channel made Lichtblick open an Image panel waiting for it (2026-11-16)
    check("a channel only for a topic the run wrote: no empty channels", set(topics) == {m[0] for m in msgs}
          and "/depth/raw" not in topics, sorted(set(topics) - {m[0] for m in msgs}))
    with open(final, "rb") as fh:
        enc = {ch.topic: (ch.message_encoding, summ.schemas[ch.schema_id].encoding) for ch in make_reader(fh).get_summary().channels.values()}
    check("the Foxglove channels are protobuf with a FileDescriptorSet, ours are JSON with a JSON schema",
          all(v == ("protobuf", "protobuf") for t, v in enc.items() if t in wire.PROTO) and all(v == ("json", "jsonschema") for t, v in enc.items() if t not in wire.PROTO), enc)
    from google.protobuf import descriptor_pb2
    fds = descriptor_pb2.FileDescriptorSet.FromString(next(s_.data for s_ in summ.schemas.values() if s_.name == "foxglove.PoseInFrame"))
    check("the descriptor set carries the message and what it imports (Pose, Vector3, Quaternion, Timestamp)",
          {"foxglove/PoseInFrame.proto", "foxglove/Pose.proto", "google/protobuf/timestamp.proto"} <= {f.name for f in fds.file}, [f.name for f in fds.file])
    check("compacted: zstd chunks, a summary with statistics, message indexes",
          chunks and all(c.compression == "zstd" for c in chunks) and stats.message_count == len(msgs)
          and all(c.message_index_offsets for c in chunks), (len(chunks), stats.message_count))

    def required_ok(topic, name):
        sch = schemas.foxglove(name.split(".")[1])
        for t, _, m in msgs:
            if t == topic:
                o = wire._unpb(topic, m.data)
                return all(k in o for k in sch["required"])
        return False

    check("each Foxglove message carries every property its published schema requires",
          all(required_ok(t, n) for t, n in (("/belief/pose", "foxglove.PoseInFrame"), ("/tf", "foxglove.FrameTransform"),
                                             ("/map", "foxglove.Grid"), ("/depth", "foxglove.PointCloud"))))
    cloud = wire._unpb("/depth", next(m for t, _, m in msgs if t == "/depth").data)
    pts = base64.b64decode(cloud["data"])
    check("/depth is a point cloud with the return kind as a field",
          [f["name"] for f in cloud["fields"]] == ["x", "y", "z", "kind"] and len(pts) % cloud["point_stride"] == 0
          and chr(pts[12]) in "fovb", cloud["fields"])
    tf = wire._unpb("/tf", next(m for t, _, m in msgs if t == "/tf").data)
    check("the map -> world transform is a FrameTransform", tf["parent_frame_id"] == "world" and tf["child_frame_id"] == "map")

    # ---- nothing dropped ---------------------------------------------------------------------------------------
    raw = Follower(run, keep_raw=True).poll()
    by_kind = {}
    for t, k, p in raw:
        by_kind.setdefault(k, []).append((t, p))
    ticks_back = by_kind["tick"]
    lost = []
    for (t, p), src in zip(ticks_back, src_ticks):
        for k, v in src.items():
            if k == "t":
                ok = p["t_src"] == v
            elif k == "pose":
                ok = p["belief"] == [round(x, 4) for x in v[:3]]
            elif k == "truth":
                ok = p["truth"] == [round(x, 4) for x in v[:3]]
            elif k == "vx":
                ok = p["cmd"][0] == v
            elif k == "vyaw":
                ok = p["cmd"][1] == v
            elif k == "depth":
                ok = len(p["depth"]) == len(v) and all(abs(a[0] - b[0]) < 1e-3 and a[3] == b[3] for a, b in zip(p["depth"], v))
            else:
                ok = p["raw"].get(k) == v
            if not ok:
                lost.append((k, v))
    check("every field of every tick of the source is in the record or in raw", len(ticks_back) == len(src_ticks) and not lost, lost[:3])
    src_events = [r for r in src_lines if r.get("event") not in (None, "plan", "world")]
    ev_back = [p for _, p in by_kind["event"]]
    inf_ok = all(("nearest_drop_m" not in e["raw"]) or e["raw"]["nearest_drop_m"] in ("inf", "-inf") or isinstance(e["raw"]["nearest_drop_m"], float)
                 for e in ev_back)
    check("every event of the source is kept with all its fields (not only the notable ones); infinities as text",
          len(ev_back) == len(src_events) and inf_ok
          and all(e["raw"] == {k: v for k, v in s.items() if k not in ("t", "event")} or "inf" in json.dumps(e["raw"])
                  for e, s in zip(ev_back, src_events)), (len(ev_back), len(src_events)))
    plans = [r for r in src_lines if r.get("event") == "plan"]
    check("plans and worlds are kept with their other fields",
          len(by_kind["plan"]) == len(plans) and all("goal" in p["raw"] for _, p in by_kind["plan"])
          and len(by_kind["world"]) == sum(1 for r in src_lines if r.get("event") == "world")
          and all("truth_z" in p["raw"] for _, p in by_kind["world"]))
    check("without keep_raw the viewer's records have no raw and no un-notable events",
          all("raw" not in p for _, k, p in Follower(run).poll() if k != "run")
          and len([1 for _, k, _ in Follower(run).poll() if k == "event"]) == 15)

    d = build(Follower(run).poll())
    check("the run builds from it: the same ticks, verdict, span as the source",
          d.run["ticks"] == len(src_ticks) and d.run["verdict"] == "trapped" and d.run["status"] == "ended"
          and d.run["key"] == "duck/apartment/explore9" and d.run["id"] == "explore9" and d.run["t0"] == 31.771,
          {k: d.run[k] for k in ("ticks", "verdict", "t0", "t1")})

    # ---- segments at goal-ending events, never at clock jumps ---------------------------------------------------
    segs = [p for _, p in by_kind["segment"]]
    goal_ends = [r for r in src_lines if r.get("event") in ("reached", "refused", "timeout", "stalled", "aborted") and r.get("goal") is not None]
    check("a segment closes at each goal-ending event that has a goal, with that goal and outcome",
          len(segs) == len(goal_ends) + 1 and [s["outcome"] for s in segs[:-1]] == [e["event"] for e in goal_ends]
          and all(s["index"] == i for i, s in enumerate(segs)) and "outcome" not in segs[-1], segs)

with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    # a clock jump with no goal-ending event is one segment; time still only grows
    log = Path(tmp) / "logs" / "jump1"
    log.mkdir(parents=True)
    rows = [{"t": 1.0, "pose": [0, 0, 0], "truth": [0, 0, 0]}, {"t": 2.0, "pose": [0, 0, 0], "truth": [0, 0, 0]},
            {"t": 0.5, "pose": [0, 0, 0], "truth": [0, 0, 0]}, {"t": 0.6, "pose": [0, 0, 0], "truth": [0, 0, 0]}]
    (log / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    from miniview.importer import import_duck
    import_duck(log, "room", data, say=lambda *_: None, started_at_ns=T0_NS)
    recs = Follower(data / "runs" / "duck" / "room" / "jump1", keep_raw=True).poll()
    ts = [t for t, k, _ in recs if k == "tick"]
    segs = [p for _, k, p in recs if k == "segment"]
    check("a clock jump without a goal-ending event starts no segment; time never goes back, t_src is kept",
          len(segs) == 1 and ts == sorted(ts) and [p["t_src"] for _, k, p in recs if k == "tick"] == [1.0, 2.0, 0.5, 0.6], (ts, segs))

with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    key = "duck/room/r1"
    d = data / "runs" / "duck" / "room" / "r1"

    # ---- one writer: the lock, refusing what exists --------------------------------------------------------------
    rec = Recorder(d, run_record(key))
    lock = json.loads((d / "writer.lock").read_text())
    check("while written: run.live.mcap beside writer.lock (PID, host, start time)",
          sorted(p.name for p in d.iterdir()) == ["run.live.mcap", "writer.lock"] and lock["pid"] > 0 and lock["host"]
          and lock["started_at_ns"] > 0, lock)
    check("a second writer on a run being written is refused, and changes nothing",
          raises(WriterBusy, Recorder, d, run_record(key)) is not False and (d / "writer.lock").exists())

    # ---- flushed per record: a reader sees each at once ----------------------------------------------------------
    f = Follower(d)
    check("the run record is there at once", [k for _, k, _ in f.poll()] == ["run"])
    rec.add(*tick(1.0, 0.0))
    got = f.poll()
    check("a tick is on disk when add returns (no close, no flush call)", [k for _, k, _ in got] == ["tick"]
          and got[0][2]["depth"] == [[0.4, 0.0, 0.0, "o"]] and got[0][2]["belief"] == [0.0, 0.0, 0.0], got)
    check("a second poll with nothing new returns nothing", f.poll() == [])
    size = (d / "run.live.mcap").stat().st_size
    with open(d / "run.live.mcap", "ab") as fh:         # half a record: the writer was interrupted mid-write
        fh.write(b"\x05\x40\x00")
    check("a half-written record is not read", f.poll() == [])
    with open(d / "run.live.mcap", "r+b") as fh:
        fh.truncate(size)
    rec.add(*tick(1.1, 0.03))
    check("what follows is read", [k for _, k, _ in f.poll()] == ["tick"])
    check("time that goes back is refused by the writer", raises(ValueError, rec.add, *tick(0.5, 0.0)) is not False)

    # a tick whose last message never came (a crash mid-tick) is not a tick
    w = rec._w
    pre = (d / "run.live.mcap").stat().st_size
    for topic, ns, pub, data_ in mcapio.wire.to_messages(1.2, "tick", tick(1.2, 0.06)[2], T0_NS)[:2]:
        w.add_message(rec.channel(topic), ns, data_, pub)
    rec.flush()
    check("a tick without its last message is not emitted", f.poll() == [])

    # ---- compaction while a reader follows: nothing twice, nothing lost --------------------------------------------
    for topic, ns, pub, data_ in mcapio.wire.to_messages(1.2, "tick", tick(1.2, 0.06)[2], T0_NS)[2:]:      # the writer finishes the tick
        w.add_message(rec.channel(topic), ns, data_, pub)
    rec.last_t = 1.2
    rec.flush()
    rec.add(*tick(1.3, 0.09))
    rec.add(2.0, "event", {"kind": "trapped", "text": "trapped"})
    rec.add(2.0, "end", {"verdict": "trapped"})
    mid = f.poll()
    rec.close()
    check("after close: run.mcap only, no live file, no lock", sorted(p.name for p in d.iterdir()) == ["run.mcap"],
          sorted(p.name for p in d.iterdir()))
    rest = f.poll()
    check("the follower continues across compaction without repeating or losing a record",
          [k for _, k, _ in mid + rest] == ["tick", "tick", "event", "end"] and f.done, [k for _, k, _ in mid + rest])
    check("a new reader of the compacted run gets all of it",
          [k for _, k, _ in Follower(d).poll()] == ["run", "tick", "tick", "tick", "tick", "event", "end"])
    check("a run that exists is refused by a writer", raises(WriterBusy, Recorder, d, run_record(key)) is not False)
    check("a run record whose key is not the folder's is refused by the writer",
          raises(ValueError, Recorder, data / "runs" / "duck" / "room" / "other", run_record(key)) is not False)

    # ---- a crashed writer: repair closes it as stopped ---------------------------------------------------------------
    key2 = "duck/room/crash1"
    d2 = data / "runs" / "duck" / "room" / "crash1"
    rec = make_run(data, key2, [tick(1.0, 0.0), tick(1.1, 0.03)], close=False)
    rec._fh.close()                                     # the process is gone; the lock and the live file stay
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    (d2 / "writer.lock").write_text(json.dumps({"pid": gone.pid, "host": lock["host"], "started_at_ns": 1}))
    gone_alive = mcapio.writer_alive(d2)
    (d2 / "writer.lock").write_text(json.dumps({"pid": os.getpid(), "host": lock["host"], "started_at_ns": 1}))
    check("a lock whose PID is gone is not a live writer; this process's is", not gone_alive and mcapio.writer_alive(d2))
    check("repair refuses a run whose writer is alive",
          raises(SystemExit, cli.cmd_repair, argparse.Namespace(data=str(data), run=key2)) is not False
          and (d2 / "run.live.mcap").exists())
    (d2 / "writer.lock").write_text(json.dumps({"pid": gone.pid, "host": lock["host"], "started_at_ns": 1}))
    check("repair refuses a file that grew in the last two minutes (its writer may be on another host)",
          raises(SystemExit, cli.cmd_repair, argparse.Namespace(data=str(data), run=key2)) is not False and (d2 / "run.live.mcap").exists())
    t_old = (d2 / "run.live.mcap").stat().st_mtime - 1000
    os.utime(d2 / "run.live.mcap", (t_old, t_old))
    cli.cmd_repair(argparse.Namespace(data=str(data), run=key2))
    recs = Follower(d2).poll()
    check("repair compacts a dead writer's file with the verdict stopped; live file and lock gone",
          [k for _, k, _ in recs] == ["run", "tick", "tick", "end"] and recs[-1][2]["verdict"] == "stopped"
          and sorted(p.name for p in d2.iterdir()) == ["run.mcap"], [k for _, k, _ in recs])
    check("repair of a run with nothing to repair says so", raises(SystemExit, cli.cmd_repair, argparse.Namespace(data=str(data), run=key2)) is not False)


# Lichtblick's reader of JSON schemas rejects an array without an item type and an array of arrays
# (2026-11-15: /miniview/tilt, /miniview/plan and /miniview/memory failed to load there).
def lichtblick_problems(node, path="$"):
    out = []
    if isinstance(node, dict):
        if node.get("type") == "array":
            items = node.get("items")
            if not isinstance(items, dict) or "type" not in items:
                out.append(f"{path}: array without an item type")
            elif items.get("type") == "array":
                out.append(f"{path}: array of arrays")
        for k, v in node.items():
            out += lichtblick_problems(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += lichtblick_problems(v, f"{path}[{i}]")
    return out


bad = {name: lichtblick_problems(json.loads(schemas.schema_bytes(f"miniview.{name}"))) for name in schemas.MINIVIEW}
check("our schemas use only what Lichtblick reads (no untyped arrays, no arrays of arrays)",
      not any(bad.values()), {k: v for k, v in bad.items() if v})

check.done()
