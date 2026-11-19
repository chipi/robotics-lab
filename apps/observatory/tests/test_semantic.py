"""The semantic map in a run (RFC-0016, ADR-0019): the navigator's `semantic` row becomes an `objects` record, its `sighting` row a `sighting`
record (a recording's `look` rows too: that was the name until ADR-0019's rename), its `room` row an event with the room and its votes as fields. Adapter, the file (the records come back whole, parts as
boxes), the reader's checks, the service's /semantic, the streams, and a run from before it still reads. The fixture is a slice of a
real recording (find-fridge-2: ticks, semantic and room rows) with sighting rows added, which that recording predates.
Run: cd apps/observatory && uv run python tests/test_semantic.py"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from mcap.reader import make_reader

from helpers import FIXTURE, Checks, catalog, get, make_run, run_record, scene, serve, tick
from runfile import keys, wire
from runfile.adapters.duck import DuckLog, prepare, records
from runfile.mcapio import Follower
from runfile.store import RunData

check = Checks("SEMANTIC")
SLICE = Path(__file__).resolve().parent / "fixtures" / "find-fridge-slice"
ROWS = [json.loads(line) for line in (SLICE / "ticks.jsonl").read_text().splitlines()]

OBJ = {"id": "fridge_1", "kind": "fridge", "x": 2.0, "y": 1.0, "n": 5, "confirmed": True, "landmark": 1.0, "permanence": "fixed",
       "first_t": 1.0, "last_t": 3.0, "confidence": 0.9, "sources": ["sim_camera"], "evidence": [{"t": 2.0, "box": [1, 2, 3, 4]}],
       "parts": [[2.0, 1.0, 0.3, 0.3, 0.5, 0.0, 1.7], [2.2, 1.0, 0.1, 0.1, 0.0, 0.0, 0.2]]}
SEEN = {"kind": "fridge", "x": 1.4, "y": -0.2, "radius": 0.42, "z0": 0.0, "z1": 1.7, "range_m": 1.42, "confidence": 0.8, "source": "sim_camera"}
SEM_ROW = {"event": "semantic", "t": 2.0, "changes": [["new", "fridge_1"], ["confirmed", "cabinet_1"]], "objects": [OBJ],
           "truth": [0.1, 0.2, 0.3]}
SIGHTING_ROW = {"event": "sighting", "t": 2.5, "pose": [0.5, 0.25, 1.5], "hfov_deg": 60, "range_m": 3.0, "seen": [SEEN], "truth": [0.6, 0.3, 1.6]}
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
(t, kind, p), = log.feed_row(SIGHTING_ROW)
check("a sighting row is a `sighting` record: the belief pose, the field of view, the range, what it saw (relative to the robot)",
      kind == "sighting" and p["pose"] == [0.5, 0.25, 1.5] and p["hfov_deg"] == 60 and p["range_m"] == 3.0 and p["seen"] == [SEEN]
      and p["raw"] == {"truth": [0.6, 0.3, 1.6]}, p)
(t, kind, p), = log.feed_row(dict(SIGHTING_ROW, event="look"))
check("a row called `look`, as the recordings made before the rename (ADR-0019) have it, is the same `sighting` record",
      kind == "sighting" and p["pose"] == [0.5, 0.25, 1.5] and p["seen"] == [SEEN] and p["raw"] == {"truth": [0.6, 0.3, 1.6]}, p)
(t, kind, p), = log.feed_row(ROOM_ROW)
check("a room row stays an event, with the room and its votes as plain fields (and the decision as before)",
      kind == "event" and p["kind"] == "room" and p["room"] == "kitchen" and p["votes"] == {"kitchen": 0.4, "office": 0.1}
      and p["text"] == "room kitchen" and p["decision"]["rule"] == "room" and "room" not in p["raw"] and "votes" not in p["raw"], p)
(t, kind, p), = log.feed_row(NO_ROOM_ROW)
check("a room row with no room is an event with room null", p["room"] is None and p["votes"] == {} and p["text"] == "room none", p)
check("a room event is not notable (a verdict is never decided by it) and is not in the adapter's own list of notable events",
      p["notable"] is False and not log.events)
(t, kind, p), = log.feed_row({"event": "area_type", "t": 3.7, "type": "office", "votes": {"office": 0.9},
                              "decision": {"rule": "area_type", "reason": "the objects near look like: office", "values": {}}})
check("an `area_type` row (the room row's name since RFC-0016 revision 3) is read as a room event: the type as the room",
      kind == "event" and p["kind"] == "room" and p["room"] == "office" and p["votes"] == {"office": 0.9}
      and p["text"] == "room office" and "type" not in p["raw"], p)
(t, kind, p), = log.feed_row({"event": "area", "t": 3.8, "id": "area_2", "name": "Marko's office", "type": "office",
                              "guess": "bath", "agrees": False, "decision": {"rule": "area", "reason": "in Marko's office", "values": {}}})
check("an `area` row is a notable event with the operator's area, and says when the objects disagree",
      kind == "event" and p["kind"] == "area" and p["notable"] is True
      and p["area"] == {"id": "area_2", "name": "Marko's office", "type": "office", "guess": "bath", "agrees": False}
      and p["text"] == "area Marko's office, but the objects look bath" and "name" not in p["raw"], p)
msgs = wire.to_messages(3.8, "event", p, 0)
check("... and the area survives the MCAP encoding", [json.loads(d)["area"]["name"] for topic, _, _, d in msgs] == ["Marko's office"], msgs)
(t, kind, p), = log.feed_row({"event": "found", "t": 5.0, "kind": "fridge", "status": "reached", "why": "stood 0.6 m from it", "object": {"id": "fridge_1"}})
check("a found row is a notable event: `found <kind> <status>`, so the index and `events --kind found` see it",
      kind == "event" and p["kind"] == "found" and p["notable"] is True and p["text"] == "found fridge reached", p)
(t, kind, p), = log.feed_row({"event": "camera_failed", "t": 5.5, "why": "RuntimeError: no frame"})
check("a camera_failed row is a notable event whose text carries its why", p["notable"] is True and p["text"] == "camera_failed RuntimeError: no frame", p)
check("a semantic row with no objects list is an event as any unknown row, not a bad record",
      log.feed_row({"event": "semantic", "t": 4.0})[0][1] == "event")

# ---- the fixture slice through the adapter and the store --------------------------------------------------------------
recs = by_kind(records(SLICE, "apartment"))
check("the real slice: objects records for its semantic rows, sightings for its sighting rows, room events, and the ticks",
      len(recs["objects"]) == sum(r.get("event") == "semantic" for r in ROWS) == 10 and len(recs["sighting"]) == 17
      and sum(p["kind"] == "room" for _, p in recs["event"]) == 3 and len(recs["tick"]) == 34, {k: len(v) for k, v in recs.items()})
meta, frames = prepare(SLICE, "apartment")
check("the slice builds a run: no rejects, the streams count what was recorded",
      meta["rejects"] == 0 and {s["id"]: s["count"] for s in meta["streams"] if s["id"].startswith("semantic.")} == {"semantic.objects": 10, "semantic.sighting": 17, "semantic.areas": 0},
      (meta["rejects"], meta["first_error"]))
rooms = [e for e in meta["events"] if e["kind"] == "room"]
check("its room events are in the run's events with the room and votes (the first, the recording's: office at 4.249 s)",
      len(rooms) == 3 and (rooms[0]["t"], rooms[0]["room"], rooms[0]["votes"]) == (4.249, "office", {"office": 0.157}), rooms)

# ---- a run from before: no objects, no sightings ---------------------------------------------------------------------------
old = by_kind(records(FIXTURE, "apartment"))
meta_old, _ = prepare(FIXTURE, "apartment")
check("a run recorded before the semantic map reads as it did: no objects or sighting records, no rejects",
      "objects" not in old and "sighting" not in old and meta_old["rejects"] == 0, sorted(old))
check("... its semantic streams are there and missing, with a reason",
      {s["id"]: (s["count"], s["missing"]) for s in meta_old["streams"] if s["id"].startswith("semantic.")} == {"semantic.objects": (0, True), "semantic.sighting": (0, True), "semantic.areas": (0, True)})

# ---- the file: written, read back ------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    RECS = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]}), tick(1.0, 0.0),
            (2.0, "objects", {"objects": [OBJ], "changes": [["new", "fridge_1"]], "t_src": 2.0, "raw": {"truth": [1, 2, 3]}}),
            (2.5, "sighting", {"pose": [0.5, 0.25, 1.5], "hfov_deg": 60.0, "range_m": 3.0, "seen": [SEEN], "t_src": 2.5, "raw": {}}),
            (3.0, "event", {"kind": "room", "text": "room kitchen", "notable": False, "t_src": 3.0, "raw": {}, "room": "kitchen",
                            "votes": {"kitchen": 0.4}}),
            tick(3.5, 0.2)]
    final = make_run(data, "duck/room/s1", RECS, signals=None)
    with open(final, "rb") as fh:
        r = make_reader(fh)
        summ = r.get_summary()
        topics = {ch.topic: (summ.schemas[ch.schema_id].name, ch.message_encoding, summ.schemas[ch.schema_id].encoding) for ch in summ.channels.values()}
        raw_obj = json.loads(next(m for _, ch, m in r.iter_messages() if ch.topic == "/miniview/objects").data)
    check("/miniview/objects and /miniview/sighting are our own JSON schemas, not Foxglove's",
          topics["/miniview/objects"] == ("miniview.objects", "json", "jsonschema") and topics["/miniview/sighting"] == ("miniview.sighting", "json", "jsonschema"), topics)
    check("on the wire a part is an object {x, y, hx, hy, yaw, z0, z1} and a change {change, id}: no arrays of arrays",
          raw_obj["objects"][0]["parts"][0] == {"x": 2.0, "y": 1.0, "hx": 0.3, "hy": 0.3, "yaw": 0.5, "z0": 0.0, "z1": 1.7}
          and raw_obj["changes"] == [{"change": "new", "id": "fridge_1"}], raw_obj)
    got = by_kind(Follower(final.parent, keep_raw=True).poll())
    check("the reader returns the records as written: parts and changes as lists again, the evidence, the raw fields",
          got["objects"][0][1]["objects"] == [OBJ] and got["objects"][0][1]["changes"] == [["new", "fridge_1"]]
          and got["objects"][0][1]["raw"] == {"truth": [1, 2, 3]} and got["sighting"][0][1]["seen"] == [SEEN]
          and got["sighting"][0][1]["pose"] == [0.5, 0.25, 1.5] and got["sighting"][0][0] == 2.5, got["sighting"])
    view = by_kind(Follower(final.parent).poll())
    check("the viewer's reading keeps them without the source time and raw",
          view["objects"][0][1].keys() == {"objects", "changes"} and "raw" not in view["sighting"][0][1], view["objects"][0][1].keys())
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
        check("GET /semantic is the snapshots and the sightings, each with its time, parts as lists",
              code == 200 and [o["t"] for o in sem["objects"]] == [2.0] and sem["objects"][0]["objects"][0]["parts"] == OBJ["parts"]
              and sem["objects"][0]["changes"] == [["new", "fridge_1"]] and sem["sightings"][0]["t"] == 2.5 and sem["sightings"][0]["seen"] == [SEEN], (code, sem))
        code, sem, _ = get(base, f"/api/v1/runs/{key}/semantic?from=2.2&to=9")
        check("... a window cuts both by time", code == 200 and sem["objects"] == [] and len(sem["sightings"]) == 1, sem)
        check("... a window that ends before it starts is a 400", get(base, f"/api/v1/runs/{key}/semantic?from=3&to=1")[0] == 400)
        run = get(base, f"/api/v1/runs/{key}")[1]
        st = {s["id"]: s for s in run["streams"]}
        check("the run lists the two streams, counted, in their own group",
              st["semantic.objects"]["count"] == 1 and st["semantic.sighting"]["count"] == 1 and st["semantic.sighting"]["group"] == "Semantic map"
              and not st["semantic.objects"]["missing"], st["semantic.objects"])
        pres = get(base, f"/api/v1/runs/{key}/presence")[1]["streams"]
        check("presence has a row for each: the snapshots' times, the sightings' span",
              pres["semantic.objects"]["times"] == [2.0] and pres["semantic.sighting"]["spans"] == [[2.5, 2.5]], {k: v for k, v in pres.items() if k.startswith("semantic")})
        ev = [e for e in run["events"] if e["kind"] == "room"]
        check("the room event is in the run's events with the room and votes", ev and ev[0]["room"] == "kitchen" and ev[0]["votes"] == {"kitchen": 0.4}, ev)
        # ---- the agent's query: /state?t= carries the semantic map at t -------------------------------------------------
        def sem_at(t):
            code, s, _ = get(base, f"/api/v1/runs/{key}/state?t={t}")
            return s["semantic"] if code == 200 else (code, s)
        s = sem_at(2.7)
        check("/state at 2.7 s: the snapshot in force (kind, id, map x/y, confirmed, landmark, confidence), the sighting 0.2 s old (kind, range, confidence), no room yet",
              s["objects_t"] == 2.0 and s["objects"] == [{"kind": "fridge", "id": "fridge_1", "x": 2.0, "y": 1.0, "confirmed": True, "landmark": 1.0, "confidence": 0.9}]
              and s["sighting"] == {"t": 2.5, "pose": [0.5, 0.25, 1.5], "hfov_deg": 60.0, "range_m": 3.0, "seen": [{"kind": "fridge", "range_m": 1.42, "confidence": 0.8}]}
              and s["room"] is None, s)
        s = sem_at(3.0)
        check("/state at 3.0 s: the room with its votes (the event at 3.0 s counts), the sighting 0.5 s old is still current",
              s["room"] == {"t": 3.0, "name": "kitchen", "votes": {"kitchen": 0.4}} and s["sighting"]["t"] == 2.5, s)
        s = sem_at(3.6)
        check("/state at 3.6 s: the sighting is 1.1 s old, so none is current; the objects and the room stay", s["sighting"] is None and len(s["objects"]) == 1 and s["room"]["name"] == "kitchen", s)
        check("/state at 2.5 s exactly: the sighting at that time is current (a record at t counts)", sem_at(2.5)["sighting"]["t"] == 2.5)
        check("/state before the first snapshot: an empty list, no sighting, no room, the key still there (the run has semantic records)",
              sem_at(1.0) == {"objects_t": None, "objects": [], "sighting": None, "room": None, "area": None}, sem_at(1.0))
        code, st, _ = get(base, f"/api/v1/runs/{key}/state?t=3.2")
        check("/state's last_event skips room events, as the page's does (the room is in `semantic`)", code == 200 and st["last_event"] is None and st["semantic"]["room"]["name"] == "kitchen", st["last_event"])
    finally:
        httpd.shutdown()

    # ---- the commands: `state` carries the semantic map, `objects` is it alone ----------------------------------------------
    env = {"PATH": "/usr/bin:/bin", "MINIVIEW_INDEX": str(Path(tmp) / "cli.sqlite")}
    cli = [sys.executable, "-m", "observatory.cli", "--data", str(data)]
    out = subprocess.run(cli + ["objects", "duck/room/s1", "--at", "2.7"], capture_output=True, text=True, env=env)
    check("miniview objects at 2.7 s prints the object (confirmed, map x/y), no room yet, the current sighting with what it saw",
          out.returncode == 0 and "fridge_1" in out.stdout and "confirmed" in out.stdout and "not told yet" in out.stdout and "saw fridge 1.42 m 0.8" in out.stdout, out.stdout + out.stderr)
    js = subprocess.run(cli + ["objects", "duck/room/s1", "--at", "3.0", "--json"], capture_output=True, text=True, env=env)
    check("--json is what /state's `semantic` holds", js.returncode == 0 and json.loads(js.stdout)["room"] == {"t": 3.0, "name": "kitchen", "votes": {"kitchen": 0.4}}, js.stdout + js.stderr)
    st_out = subprocess.run(cli + ["state", "duck/room/s1", "--at", "3.0"], capture_output=True, text=True, env=env)
    check("miniview state prints the objects, the sighting and the room too", st_out.returncode == 0 and "objects (1, 1 confirmed)" in st_out.stdout and "room: kitchen" in st_out.stdout, st_out.stdout + st_out.stderr)

# ---- the query without a service: a run with no semantic map has no `semantic` key --------------------------------------------
from observatory import query  # noqa: E402

old_run = {"id": "r", "scene": "s", "epochs": [], "events": [{"t": 1.0, "kind": "cliff_stop", "text": "cliff_stop"}]}
old_frames = {"t": [0.1], "belief": [[0, 0, 0]], "truth": [None], "tilt": [None], "cmd": [[0, 0]], "depth": [None], "plan_at": [-1], "world_at": [-1]}
check("a run with no objects, sightings or room events: the state has no `semantic` key", "semantic" not in query.state(old_run, old_frames, 0.1, None, {"objects": [], "sightings": []}))
room_only = dict(old_run, events=[{"t": 0.05, "kind": "room", "text": "room none", "room": None, "votes": {}}])
check("a run with only a room event: `semantic` has the room (no name, no votes) and no objects",
      query.state(room_only, old_frames, 0.1, None, None)["semantic"] == {"objects_t": None, "objects": [], "sighting": None, "room": {"t": 0.05, "name": None, "votes": {}}, "area": None})
area_run = dict(old_run, events=[{"t": 0.05, "kind": "area", "text": "area Kitchen", "area": {"id": "area_1", "name": "Kitchen", "type": "kitchen", "guess": None, "agrees": None}}])
check("a run with an area event: `semantic` has the area at its time",
      query.state(area_run, old_frames, 0.1, None, None)["semantic"]["area"] == {"t": 0.05, "id": "area_1", "name": "Kitchen", "type": "kitchen", "guess": None, "agrees": None})
unconf = query.semantic_at(old_run, {"objects": [{"t": 0.0, "objects": [dict(OBJ, confirmed=False, landmark=0.5)], "changes": []}], "sightings": []}, 1.0)
check("an unconfirmed object is in the list with confirmed false and its landmark value", unconf["objects"][0]["confirmed"] is False and unconf["objects"][0]["landmark"] == 0.5, unconf)

# ---- a file written before the rename: the topic `/miniview/look` is read as a sighting ---------------------------------------
asm = wire.Assembler()
asm.feed("/miniview/run", 1_000_000_000, json.dumps(run_record()).encode())
legacy = asm.feed("/miniview/look", 3_000_000_000, json.dumps({"pose": [0.5, 0.25, 1.5], "hfov_deg": 60.0, "range_m": 3.0, "seen": [SEEN], "t_src": 2.0, "raw": {}}).encode())
check("a message on /miniview/look (a file from before the rename) comes back as a `sighting` record",
      len(legacy) == 1 and legacy[0][1] == "sighting" and legacy[0][2]["seen"] == [SEEN] and legacy[0][2]["pose"] == [0.5, 0.25, 1.5], legacy)

# ---- the reader's checks --------------------------------------------------------------------------------------------------
d = RunData()
d.feed(0.0, "run", run_record())
ok = [d.feed(1.0, "objects", {"objects": [OBJ], "changes": []}), d.feed(1.1, "sighting", {"pose": [0, 0, 0], "hfov_deg": 60, "range_m": 3, "seen": [SEEN]}),
      d.feed(1.2, "sighting", {"pose": [0, 0, 0], "hfov_deg": 60, "range_m": 3, "seen": []})]
bad = [d.feed(1.3, "objects", {"objects": [dict(OBJ, parts=[[1, 2, 3]])], "changes": []}),
       d.feed(1.4, "objects", {"objects": [OBJ], "changes": [["new"]]}),
       d.feed(1.5, "sighting", {"pose": [0, 0], "hfov_deg": 60, "range_m": 3, "seen": []}),
       d.feed(1.6, "sighting", {"pose": [0, 0, 0], "hfov_deg": 60, "range_m": 3, "seen": [{"kind": "x", "x": "a", "y": 0}]}),
       d.feed(1.7, "sighting", {"pose": [0, 0, 0], "hfov_deg": 60, "range_m": 3, "seen": [dict(SEEN, confidence=float("nan"))]})]
check("good objects and sighting records are applied; short parts, a half change, a short pose, a detection with no number and a NaN are skipped and counted",
      all(ok) and not any(bad) and d.run["rejects"] == 5 and len(d.sem["objects"]) == 1 and len(d.sem["sightings"]) == 2, (ok, bad, d.run["first_error"]))
try:
    wire.to_messages(1.0, "sighting", {"hfov_deg": 60}, 0)
    refused = False
except KeyError:
    refused = True
check("a writer refuses a sighting with no pose", refused)

check.done()
