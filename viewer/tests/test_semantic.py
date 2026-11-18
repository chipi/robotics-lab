"""The semantic map in a run (RFC-0016, ADR-0018): the navigator's `semantic` row becomes an `objects` record, its `look` row a `look`
record, its `room` row an event with the room and its votes as fields. Adapter, the file (the records come back whole, parts as
boxes), the reader's checks, the service's /semantic, the streams, and a run from before it still reads. The fixture is a slice of a
real recording (find-fridge-2: ticks, semantic and room rows) with look rows added, which that recording predates.
Run: cd viewer && uv run python tests/test_semantic.py"""

import json
import tempfile
from pathlib import Path

from mcap.reader import make_reader

from helpers import FIXTURE, Checks, catalog, get, make_run, run_record, scene, serve, tick
from miniview import keys, wire
from miniview.adapters.duck import DuckLog, prepare, records
from miniview.mcapio import Follower
from miniview.store import RunData

check = Checks("SEMANTIC")
SLICE = Path(__file__).resolve().parent / "fixtures" / "find-fridge-slice"
ROWS = [json.loads(line) for line in (SLICE / "ticks.jsonl").read_text().splitlines()]

OBJ = {"id": "fridge_1", "kind": "fridge", "x": 2.0, "y": 1.0, "n": 5, "confirmed": True, "landmark": 1.0, "permanence": "fixed",
       "first_t": 1.0, "last_t": 3.0, "confidence": 0.9, "sources": ["sim_camera"], "evidence": [{"t": 2.0, "box": [1, 2, 3, 4]}],
       "parts": [[2.0, 1.0, 0.3, 0.3, 0.5, 0.0, 1.7], [2.2, 1.0, 0.1, 0.1, 0.0, 0.0, 0.2]]}
SEEN = {"kind": "fridge", "x": 1.4, "y": -0.2, "radius": 0.42, "z0": 0.0, "z1": 1.7, "range_m": 1.42, "confidence": 0.8, "source": "sim_camera"}
SEM_ROW = {"event": "semantic", "t": 2.0, "changes": [["new", "fridge_1"], ["confirmed", "cabinet_1"]], "objects": [OBJ],
           "truth": [0.1, 0.2, 0.3]}
LOOK_ROW = {"event": "look", "t": 2.5, "pose": [0.5, 0.25, 1.5], "hfov_deg": 60, "range_m": 3.0, "seen": [SEEN], "truth": [0.6, 0.3, 1.6]}
ROOM_ROW = {"event": "room", "t": 3.0, "room": "kitchen", "votes": {"kitchen": 0.4, "office": 0.1},
            "decision": {"rule": "room", "reason": "the objects near say: kitchen", "values": {"votes": {"kitchen": 0.4}}}, "truth": [0, 0, 0]}
NO_ROOM_ROW = {"event": "room", "t": 3.5, "room": None, "votes": {}}


def by_kind(recs):
    out = {}
    for t, k, p in recs:
        out.setdefault(k, []).append((t, p))
    return out


# ---- the adapter: a row -> a record ----------------------------------------------------------------------------------
log = DuckLog(Path("/nonexistent/x"), "apartment")
(t, kind, p), = log.feed_row(SEM_ROW)
check("a semantic row is an `objects` record: the objects, the changes, the source time, the other fields in raw",
      kind == "objects" and t == 2.0 and p["objects"] == [OBJ] and p["changes"] == [["new", "fridge_1"], ["confirmed", "cabinet_1"]]
      and p["t_src"] == 2.0 and p["raw"] == {"truth": [0.1, 0.2, 0.3]}, p)
(t, kind, p), = log.feed_row(LOOK_ROW)
check("a look row is a `look` record: the belief pose, the field of view, the range, what it saw (relative to the robot)",
      kind == "look" and p["pose"] == [0.5, 0.25, 1.5] and p["hfov_deg"] == 60 and p["range_m"] == 3.0 and p["seen"] == [SEEN]
      and p["raw"] == {"truth": [0.6, 0.3, 1.6]}, p)
(t, kind, p), = log.feed_row(ROOM_ROW)
check("a room row stays an event, with the room and its votes as plain fields (and the decision as before)",
      kind == "event" and p["kind"] == "room" and p["room"] == "kitchen" and p["votes"] == {"kitchen": 0.4, "office": 0.1}
      and p["text"] == "room kitchen" and p["decision"]["rule"] == "room" and "room" not in p["raw"] and "votes" not in p["raw"], p)
(t, kind, p), = log.feed_row(NO_ROOM_ROW)
check("a room row with no room is an event with room null", p["room"] is None and p["votes"] == {} and p["text"] == "room none", p)
check("a room event is not notable (a verdict is never decided by it) and is not in the adapter's own list of notable events",
      p["notable"] is False and not log.events)
check("a semantic row with no objects list is an event as any unknown row, not a bad record",
      log.feed_row({"event": "semantic", "t": 4.0})[0][1] == "event")

# ---- the fixture slice through the adapter and the store --------------------------------------------------------------
recs = by_kind(records(SLICE, "apartment"))
check("the real slice: objects records for its semantic rows, looks for its look rows, room events, and the ticks",
      len(recs["objects"]) == sum(r.get("event") == "semantic" for r in ROWS) == 10 and len(recs["look"]) == 17
      and sum(p["kind"] == "room" for _, p in recs["event"]) == 3 and len(recs["tick"]) == 34, {k: len(v) for k, v in recs.items()})
meta, frames = prepare(SLICE, "apartment")
check("the slice builds a run: no rejects, the streams count what was recorded",
      meta["rejects"] == 0 and {s["id"]: s["count"] for s in meta["streams"] if s["id"].startswith("semantic.")} == {"semantic.objects": 10, "semantic.look": 17},
      (meta["rejects"], meta["first_error"]))
rooms = [e for e in meta["events"] if e["kind"] == "room"]
check("its room events are in the run's events with the room and votes (the first, the recording's: office at 4.249 s)",
      len(rooms) == 3 and (rooms[0]["t"], rooms[0]["room"], rooms[0]["votes"]) == (4.249, "office", {"office": 0.157}), rooms)

# ---- a run from before: no objects, no looks ---------------------------------------------------------------------------
old = by_kind(records(FIXTURE, "apartment"))
meta_old, _ = prepare(FIXTURE, "apartment")
check("a run recorded before the semantic map reads as it did: no objects or look records, no rejects",
      "objects" not in old and "look" not in old and meta_old["rejects"] == 0, sorted(old))
check("... its two semantic streams are there and missing, with a reason",
      {s["id"]: (s["count"], s["missing"]) for s in meta_old["streams"] if s["id"].startswith("semantic.")} == {"semantic.objects": (0, True), "semantic.look": (0, True)})

# ---- the file: written, read back ------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    RECS = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]}), tick(1.0, 0.0),
            (2.0, "objects", {"objects": [OBJ], "changes": [["new", "fridge_1"]], "t_src": 2.0, "raw": {"truth": [1, 2, 3]}}),
            (2.5, "look", {"pose": [0.5, 0.25, 1.5], "hfov_deg": 60.0, "range_m": 3.0, "seen": [SEEN], "t_src": 2.5, "raw": {}}),
            (3.0, "event", {"kind": "room", "text": "room kitchen", "notable": False, "t_src": 3.0, "raw": {}, "room": "kitchen",
                            "votes": {"kitchen": 0.4}}),
            tick(3.5, 0.2)]
    final = make_run(data, "duck/room/s1", RECS, signals=None)
    with open(final, "rb") as fh:
        r = make_reader(fh)
        summ = r.get_summary()
        topics = {ch.topic: (summ.schemas[ch.schema_id].name, ch.message_encoding, summ.schemas[ch.schema_id].encoding) for ch in summ.channels.values()}
        raw_obj = json.loads(next(m for _, ch, m in r.iter_messages() if ch.topic == "/miniview/objects").data)
    check("/miniview/objects and /miniview/look are our own JSON schemas, not Foxglove's",
          topics["/miniview/objects"] == ("miniview.objects", "json", "jsonschema") and topics["/miniview/look"] == ("miniview.look", "json", "jsonschema"), topics)
    check("on the wire a part is an object {x, y, hx, hy, yaw, z0, z1} and a change {change, id}: no arrays of arrays",
          raw_obj["objects"][0]["parts"][0] == {"x": 2.0, "y": 1.0, "hx": 0.3, "hy": 0.3, "yaw": 0.5, "z0": 0.0, "z1": 1.7}
          and raw_obj["changes"] == [{"change": "new", "id": "fridge_1"}], raw_obj)
    got = by_kind(Follower(final.parent, keep_raw=True).poll())
    check("the reader returns the records as written: parts and changes as lists again, the evidence, the raw fields",
          got["objects"][0][1]["objects"] == [OBJ] and got["objects"][0][1]["changes"] == [["new", "fridge_1"]]
          and got["objects"][0][1]["raw"] == {"truth": [1, 2, 3]} and got["look"][0][1]["seen"] == [SEEN]
          and got["look"][0][1]["pose"] == [0.5, 0.25, 1.5] and got["look"][0][0] == 2.5, got["look"])
    view = by_kind(Follower(final.parent).poll())
    check("the viewer's reading keeps them without the source time and raw",
          view["objects"][0][1].keys() == {"objects", "changes"} and "raw" not in view["look"][0][1], view["objects"][0][1].keys())
    room = [p for _, p in view["event"] if p["kind"] == "room"]
    check("a room event written as not notable is still in the viewer's reading, with its room and votes",
          room and room[0]["room"] == "kitchen" and room[0]["votes"] == {"kitchen": 0.4}, room)

    # ---- the service: /semantic, the streams, presence ----------------------------------------------------------------
    sc = data / "scenes" / "room"
    sc.mkdir(parents=True)
    (sc / "scene.json").write_text(json.dumps(scene()))
    cat = catalog(data)
    httpd, base = serve(cat, follow=False)
    try:
        key = keys.make_key("duck", "room", "s1")
        code, sem, _ = get(base, f"/api/v1/runs/{key}/semantic")
        check("GET /semantic is the snapshots and the looks, each with its time, parts as lists",
              code == 200 and [o["t"] for o in sem["objects"]] == [2.0] and sem["objects"][0]["objects"][0]["parts"] == OBJ["parts"]
              and sem["objects"][0]["changes"] == [["new", "fridge_1"]] and sem["looks"][0]["t"] == 2.5 and sem["looks"][0]["seen"] == [SEEN], (code, sem))
        code, sem, _ = get(base, f"/api/v1/runs/{key}/semantic?from=2.2&to=9")
        check("... a window cuts both by time", code == 200 and sem["objects"] == [] and len(sem["looks"]) == 1, sem)
        check("... a window that ends before it starts is a 400", get(base, f"/api/v1/runs/{key}/semantic?from=3&to=1")[0] == 400)
        run = get(base, f"/api/v1/runs/{key}")[1]
        st = {s["id"]: s for s in run["streams"]}
        check("the run lists the two streams, counted, in their own group",
              st["semantic.objects"]["count"] == 1 and st["semantic.look"]["count"] == 1 and st["semantic.look"]["group"] == "Semantic map"
              and not st["semantic.objects"]["missing"], st["semantic.objects"])
        pres = get(base, f"/api/v1/runs/{key}/presence")[1]["streams"]
        check("presence has a row for each: the snapshots' times, the looks' span",
              pres["semantic.objects"]["times"] == [2.0] and pres["semantic.look"]["spans"] == [[2.5, 2.5]], {k: v for k, v in pres.items() if k.startswith("semantic")})
        ev = [e for e in run["events"] if e["kind"] == "room"]
        check("the room event is in the run's events with the room and votes", ev and ev[0]["room"] == "kitchen" and ev[0]["votes"] == {"kitchen": 0.4}, ev)
    finally:
        httpd.shutdown()

# ---- the reader's checks --------------------------------------------------------------------------------------------------
d = RunData()
d.feed(0.0, "run", run_record())
ok = [d.feed(1.0, "objects", {"objects": [OBJ], "changes": []}), d.feed(1.1, "look", {"pose": [0, 0, 0], "hfov_deg": 60, "range_m": 3, "seen": [SEEN]}),
      d.feed(1.2, "look", {"pose": [0, 0, 0], "hfov_deg": 60, "range_m": 3, "seen": []})]
bad = [d.feed(1.3, "objects", {"objects": [dict(OBJ, parts=[[1, 2, 3]])], "changes": []}),
       d.feed(1.4, "objects", {"objects": [OBJ], "changes": [["new"]]}),
       d.feed(1.5, "look", {"pose": [0, 0], "hfov_deg": 60, "range_m": 3, "seen": []}),
       d.feed(1.6, "look", {"pose": [0, 0, 0], "hfov_deg": 60, "range_m": 3, "seen": [{"kind": "x", "x": "a", "y": 0}]}),
       d.feed(1.7, "look", {"pose": [0, 0, 0], "hfov_deg": 60, "range_m": 3, "seen": [dict(SEEN, confidence=float("nan"))]})]
check("good objects and look records are applied; short parts, a half change, a short pose, a detection with no number and a NaN are skipped and counted",
      all(ok) and not any(bad) and d.run["rejects"] == 5 and len(d.sem["objects"]) == 1 and len(d.sem["looks"]) == 2, (ok, bad, d.run["first_error"]))
try:
    wire.to_messages(1.0, "look", {"hfov_deg": 60}, 0)
    refused = False
except KeyError:
    refused = True
check("a writer refuses a look with no pose", refused)

check.done()
