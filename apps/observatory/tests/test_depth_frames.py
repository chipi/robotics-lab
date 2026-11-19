"""Replay logging in format 2 (ADR-0014): a depth frame is a record of its own (the raw 8x8 distances and statuses as two
foxglove.RawImage, then a JSON message with its times, the state it was paired with and what was derived from it), and an event
may carry the decision behind it. Round trip through the file, the tick protocol (a frame another record interrupts is dropped),
the reader's checks, the service's /sensor, the commands. No fixed sleeps.
Run: cd apps/observatory && uv run python tests/test_depth_frames.py"""

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from mcap.reader import make_reader

from helpers import Checks, catalog, get, make_run, run_record, scene, serve, tick
from runfile import keys, schemas, wire
from miniview import query
from runfile.mcapio import Follower, Recorder
from runfile.store import RunData, build

check = Checks("DEPTH-FRAMES")
STATE = {"quat": [0.99, 0.0, 0.1, 0.0], "odom_z": 0.116, "tof": {"pos": [0.085, 0.02, 0.12], "quat": [0.9, 0.0, 0.4, 0.0]}}
DISTANCES = [100 * i for i in range(64)]
DISTANCES[5] = -1                                   # the sensor's int16: a negative value survives the image
STATUS = [5] * 60 + [0, 12, 13, 255]


def frame(t, **kw):
    p = {"rows": 8, "cols": 8, "distance_mm": list(DISTANCES), "status": list(STATUS), "seq": 7, "frame_t_ns": 123_456_789_000,
         "state_t_ns": 123_450_000_000, "pair_dt_ms": -6.5, "t_src": t, "state": STATE, "pose": [1.0, 2.0, 0.5],
         "derived": {"points": [[0.1, 0.2, 0.0, "f"], [0.3, -0.1, 0.12, "o"]], "drop_points": [[0.4, 0.0, 0.5]], "block_m": 0.25}}
    p.update(kw)
    return (t, "depth_frame", p)


DECISION = {"rule": "cliff_stop", "reason": "a drop 0.55 m ahead in 3 frames", "values": {"drop_m": 0.55, "stop_m": 0.6, "streak": 3}}
EVENT = (1.2, "event", {"kind": "cliff_stop", "text": "cliff_stop drop_m 0.55", "notable": True, "t_src": 1.2, "raw": {"zones": 4},
                        "decision": DECISION})
RECORDS = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]}), tick(1.0, 0.0), frame(1.05), tick(1.1, 0.1), EVENT,
           frame(1.3, seq=8, frame_t_ns=123_523_000_000, state_t_ns=None, pair_dt_ms=None, state=None, pose=None, derived=None),
           tick(1.4, 0.2)]

with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    final = make_run(data, "duck/room/r1", RECORDS, signals=None)
    run_dir = final.parent

    # ---- the file ----------------------------------------------------------------------------------------------
    with open(final, "rb") as fh:
        r = make_reader(fh)
        summ = r.get_summary()
        topics = {ch.topic: (summ.schemas[ch.schema_id].name, ch.message_encoding, summ.schemas[ch.schema_id].encoding)
                  for ch in summ.channels.values()}
        msgs = [(ch.topic, m) for _, ch, m in r.iter_messages()]
    check("/depth/raw and /depth/status are foxglove.RawImage, protobuf; the metadata is JSON",
          topics["/depth/raw"] == ("foxglove.RawImage", "protobuf", "protobuf") and topics["/depth/status"] == ("foxglove.RawImage", "protobuf", "protobuf")
          and topics["/miniview/depth_frame"] == ("miniview.depth_frame", "json", "jsonschema"), topics)
    order = [t for t, _ in msgs if t.startswith("/depth/") or t == "/miniview/depth_frame"]
    check("a frame is /depth/raw, /depth/status, /miniview/depth_frame in that order, once per frame",
          order == ["/depth/raw", "/depth/status", "/miniview/depth_frame"] * 2, order)
    raw = wire._unpb("/depth/raw", next(m for t, m in msgs if t == "/depth/raw").data)
    stat = wire._unpb("/depth/status", next(m for t, m in msgs if t == "/depth/status").data)
    check("the distances are a 16UC1 image 8 x 8 (step 16) of the sensor's frame, the statuses mono8 (step 8)",
          (raw["encoding"], raw["width"], raw["height"], raw["step"], raw["frame_id"]) == ("16UC1", 8, 8, 16, "tof")
          and (stat["encoding"], stat["step"], stat["frame_id"]) == ("mono8", 8, "tof")
          and len(base64.b64decode(raw["data"])) == 128 and list(base64.b64decode(stat["data"])) == STATUS)
    sch = schemas.foxglove("RawImage")
    check("each RawImage carries every property its published schema requires", all(k in raw for k in sch["required"]) and all(k in stat for k in sch["required"]))

    # ---- the reader: the record comes back whole ---------------------------------------------------------------
    full = [x for x in Follower(run_dir, keep_raw=True).poll() if x[1] == "depth_frame"]
    p = full[0][2]
    check("a frame reads back: distances (a negative one too), statuses, times, the paired state, the pose, what was derived",
          p["distance_mm"] == DISTANCES and p["status"] == STATUS and p["frame_t_ns"] == 123_456_789_000
          and p["state_t_ns"] == 123_450_000_000 and p["pair_dt_ms"] == -6.5 and p["state"] == STATE and p["pose"] == [1.0, 2.0, 0.5]
          and p["derived"] == {"points": [[0.1, 0.2, 0.0, "f"], [0.3, -0.1, 0.12, "o"]], "drop_points": [[0.4, 0.0, 0.5]], "block_m": 0.25}, p)
    q = full[1][2]
    check("a frame that was not paired has none of that: no state time, no derived points", "state_t_ns" not in q and "derived" not in q and q["seq"] == 8, q)
    view = [x for x in Follower(run_dir).poll() if x[1] == "depth_frame"][0][2]
    check("the viewer's reading keeps the frame, its pairing, and the paired state and pose (the eye, RFC-0013), not the derived points (they are the replay's)",
          view["distance_mm"] == DISTANCES and view["pair_dt_ms"] == -6.5 and view["state"] == STATE and view["pose"] == [1.0, 2.0, 0.5]
          and not ({"derived", "t_src"} & set(view)), sorted(view))
    ev = [x for x in Follower(run_dir).poll() if x[1] == "event"][0][2]
    check("an event keeps its decision (rule, reason, values) in the viewer's reading too", ev["decision"] == DECISION, ev)

    # ---- a glance is a decision a page shows, even in a recording that wrote it as not notable (RFC-0013) ----------
    rec = Recorder(keys.run_dir(data, "duck/room/g1"), run_record("duck/room/g1"))
    glance = {"rule": "glance", "reason": "a suspected drop near the way: looked at it with the head", "values": {"bearing_deg": -7, "time_s": 1.9}}
    rec.add(0.5, "event", {"kind": "glance", "text": "", "notable": False, "raw": {}, "decision": glance})
    rec.add(0.6, "event", {"kind": "plan_kept", "text": "", "notable": False, "raw": {}})
    rec.close()
    kept = [p for _, k, p in Follower(rec.dir).poll() if k == "event"]
    check("a glance written as not notable is still in the viewer's reading, with its decision; another un-notable event is not",
          [e["kind"] for e in kept] == ["glance"] and kept[0]["decision"] == glance, kept)

    # ---- the tick protocol: nothing between the first and the last message -------------------------------------
    rec = Recorder(keys.run_dir(data, "duck/room/r2"), run_record("duck/room/r2"))
    rec.add(0.5, "depth_frame", frame(0.5)[2])
    msgs2 = wire.to_messages(0.6, "depth_frame", frame(0.6)[2], rec.base_ns)
    rec._write(msgs2[:2])                       # a writer that died after the status: no metadata message
    rec.add(0.7, "event", {"kind": "x", "text": "", "notable": False, "raw": {}})
    rec.add(0.8, "depth_frame", frame(0.8)[2])
    out = Follower(rec.dir, keep_raw=True)
    got = out.poll()
    check("a frame another record interrupts is dropped, and said", [k for _, k, _ in got].count("depth_frame") == 2 and out.partials == 1
          and "interrupted by /miniview/event" in " ".join(out.take_errors() + [str(out.asm.partial_msgs)]), (out.partials, out.errors))
    rec.close()

    # ---- the writer refuses what is not a frame ------------------------------------------------------------------
    try:
        wire.to_messages(1.0, "depth_frame", dict(frame(1.0)[2], distance_mm=[1, 2, 3]), 0)
        bad_write = False
    except ValueError:
        bad_write = True
    check("a frame whose distances are not rows x cols is refused by the writer", bad_write)

    # ---- the reader's checks -------------------------------------------------------------------------------------
    d = RunData()
    d.feed(0.0, "run", run_record())
    good = d.feed(*frame(1.0))
    short = d.feed(1.1, "depth_frame", dict(frame(1.1)[2], status=[5] * 3))
    nocl = d.feed(1.2, "depth_frame", {k: v for k, v in frame(1.2)[2].items() if k != "frame_t_ns"})
    baddec = d.feed(1.3, "event", {"kind": "k", "text": "", "decision": {"rule": "r"}})
    check("a good frame is applied; a short one, one with no sensor time and an event with half a decision are skipped and counted",
          good and not short and not nocl and not baddec and d.run["rejects"] == 3 and len(d.raw) == 1, d.run["first_error"])
    streams = {s["id"]: s for s in build([(0.0, "run", run_record()), frame(1.0), tick(1.1, 0.0)]).run["streams"]}
    none = {s["id"]: s for s in build([(0.0, "run", run_record()), tick(1.0, 0.0)]).run["streams"]}
    check("sensors.raw: counted when present, missing ('not in this run') when not",
          streams["sensors.raw"]["count"] == 1 and not streams["sensors.raw"]["missing"] and none["sensors.raw"]["missing"]
          and none["sensors.raw"]["why"] == "not in this run", (streams["sensors.raw"], none["sensors.raw"]))

    # ---- queries and the service ---------------------------------------------------------------------------------
    run_d = build([(0.0, "run", run_record())] + RECORDS)
    f1 = query.sensor_at(run_d.raw, 1.2)
    check("sensor_at gives the frame at or before t (the first one when t is earlier), its number and the count",
          f1["t"] == 1.05 and f1["index"] == 0 and f1["n"] == 2 and query.sensor_at(run_d.raw, 0.0)["index"] == 0
          and query.sensor_at(run_d.raw, 9.0)["index"] == 1 and query.sensor_at([], 1.0) is None)
    data2 = Path(tmp) / "served"
    make_run(data2, "duck/room/r1", RECORDS)
    cat = catalog(data2)
    cat.put_scene(scene())
    httpd, base = serve(cat, follow=False)
    try:
        code, body, _ = get(base, "/api/v1/runs/duck/room/r1/sensor?t=1.2")
        check("GET .../sensor?t= answers the frame at t with its pairing, the paired state and the pose (not the derived points)", code == 200 and body["t"] == 1.05
              and body["distance_mm"] == DISTANCES and body["pair_dt_ms"] == -6.5 and body["index"] == 0 and body["n"] == 2
              and body["state"] == STATE and body["pose"] == [1.0, 2.0, 0.5] and "derived" not in body, (code, str(body)[:200]))
        code2, body2, _ = get(base, "/api/v1/runs/duck/room/r1/sensor")
        check("without t it is the last frame", code2 == 200 and body2["index"] == 1, code2)
        code3, body3, _ = get(base, "/api/v1/runs/duck/room/r1/sensor?t=abc")
        check("a t that is not a number is a 400", code3 == 400 and "error" in body3, code3)
        make_run(data2, "duck/room/r3", [tick(1.0, 0.0)])
        cat.scan()
        code4, body4, _ = get(base, "/api/v1/runs/duck/room/r3/sensor?t=1")
        check("a run with no raw frames answers 404 and says so", code4 == 404 and "no raw depth frames" in body4["error"], (code4, body4))
        _, pres, _ = get(base, "/api/v1/runs/duck/room/r1/presence")
        check("presence has the raw frames' spans", pres["streams"]["sensors.raw"]["spans"], pres["streams"].get("sensors.raw"))
        _, ev_list, _ = get(base, "/api/v1/runs/duck/room/r1/events")
        _, summ_, _ = get(base, "/api/v1/runs/duck/room/r1")
        check("the run's events keep the decision", any(e.get("decision") == DECISION for e in summ_["events"]), summ_["events"])
    finally:
        httpd.shutdown()

    # ---- the commands --------------------------------------------------------------------------------------------
    env = {"PATH": "/usr/bin:/bin"}
    cli = [sys.executable, "-m", "miniview.cli", "--data", str(data2)]
    env["MINIVIEW_INDEX"] = str(Path(tmp) / "cli.sqlite")
    out = subprocess.run(cli + ["sensor", "duck/room/r1", "--at", "1.2"], capture_output=True, text=True, env=env)
    check("miniview sensor prints the frame as a grid, the invalid zones marked, and the pairing",
          out.returncode == 0 and "depth frame 1 of 2" in out.stdout and "-6.5 ms" in out.stdout
          and sum(line.count("*") for line in out.stdout.split("status:")[0].splitlines()[3:]) == 4, out.stdout + out.stderr)
    js = subprocess.run(cli + ["sensor", "duck/room/r1", "--at", "1.2", "--json"], capture_output=True, text=True, env=env)
    check("--json is the frame as the API gives it", js.returncode == 0 and json.loads(js.stdout)["distance_mm"] == DISTANCES, js.stderr)
    none_ = subprocess.run(cli + ["sensor", "duck/room/r3", "--at", "1"], capture_output=True, text=True, env=env)
    check("a run with no frames says so and fails", none_.returncode != 0 and "no raw depth frames" in none_.stderr, none_.stderr)

check.done()
