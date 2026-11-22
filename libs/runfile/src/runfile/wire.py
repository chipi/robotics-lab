"""Records (t, kind, payload) <-> the messages of a format 2 file (ADR-0007).

A tick is several messages written in a fixed order, the last one `/miniview/tick_extra`; a world is
`/map` then `/miniview/memory`. The reader emits a record only when its last message has arrived, so
a half-written tick (a crash mid-write) never shows up as a tick with fields missing.
"""

import base64
import json
import math
import struct

from google.protobuf import json_format

from runfile import schemas
from runfile.navcontract import stop_before
from runfile.signals import SignalSet

KINDS = ("run", "epoch", "tick", "signals", "plan", "world", "event", "depth_frame", "objects", "sighting", "segment", "end")

CHANNELS = {                          # topic -> schema
    "/miniview/run": "miniview.run",
    "/tf": "foxglove.FrameTransform",
    "/belief/pose": "foxglove.PoseInFrame",
    "/truth/pose": "foxglove.PoseInFrame",
    "/depth": "foxglove.PointCloud",
    "/depth/raw": "foxglove.RawImage",
    "/depth/status": "foxglove.RawImage",
    "/miniview/depth_frame": "miniview.depth_frame",
    "/miniview/command": "miniview.command",
    "/miniview/tilt": "miniview.tilt",
    "/miniview/tick_extra": "miniview.tick_extra",
    "/miniview/plan": "miniview.plan",
    "/map": "foxglove.Grid",
    "/miniview/memory": "miniview.memory",
    "/miniview/event": "miniview.event",
    "/miniview/objects": "miniview.objects",
    "/miniview/sighting": "miniview.sighting",
    "/miniview/segment": "miniview.segment",
    "/miniview/end": "miniview.end",
}
PART_FIELDS = ("x", "y", "hx", "hy", "yaw", "z0", "z1")     # an object's part: a box in plan (centre, half sizes, heading) with a bottom and a top
POINT = struct.Struct("<fffB")
UINT8, FLOAT32 = 1, 7
_IDENT = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


PROTO = {"/belief/pose": "PoseInFrame", "/truth/pose": "PoseInFrame", "/tf": "FrameTransform", "/map": "Grid",
         "/depth": "PointCloud", "/depth/raw": "RawImage", "/depth/status": "RawImage"}      # the Foxglove channels are protobuf (ADR-0007); our own kinds are JSON


def _pb(topic: str, obj: dict, ns: int) -> bytes:
    msg = schemas.message_class(PROTO[topic])()
    json_format.ParseDict({k: v for k, v in obj.items() if k != "timestamp"}, msg)
    msg.timestamp.FromNanoseconds(ns)
    return msg.SerializeToString()


def _unpb(topic: str, data: bytes) -> dict:
    msg = schemas.message_class(PROTO[topic])()
    msg.ParseFromString(data)
    return json_format.MessageToDict(msg, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)


def _js(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), allow_nan=False).encode()


def _raw(v):
    """JSON has no inf or nan: in `raw` they become the strings "inf", "-inf" and "nan" (the source copy keeps them)."""
    if isinstance(v, float) and not math.isfinite(v):
        return "nan" if v != v else ("inf" if v > 0 else "-inf")
    if isinstance(v, dict):
        return {k: _raw(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_raw(x) for x in v]
    return v


def _xy(points) -> list:
    """[[x, y], ...] as [{"x", "y"}, ...]: Lichtblick's JSON-schema reader takes no arrays of arrays."""
    return [{"x": p[0], "y": p[1]} for p in points]


def _unxy(points) -> list:
    return [[p["x"], p["y"]] for p in points]


# kinds a recording from before the adapter listed them as notable wrote as not notable, but that are decisions a page shows (RFC-0013)
ALWAYS_NOTABLE = ("glance", "room", "area", "site")
SENSOR_FRAME = "tof"          # the depth sensor's own frame_id: the raw frame is an image of it, not a place in the map


def _u16(v: int) -> int:
    """A distance as the 16 bits an image holds (the sensor's int16: a negative value is kept, read back by `_i16`)."""
    return v & 0xFFFF


def _i16(v: int) -> int:
    return v - 0x10000 if v >= 0x8000 else v


def _raw_image(ns: int, rows: int, cols: int, encoding: str, step: int, data: bytes) -> dict:
    return {"timestamp": _stamp(ns), "frame_id": SENSOR_FRAME, "width": cols, "height": rows, "encoding": encoding,
            "step": step, "data": base64.b64encode(data).decode()}


def _depth_frame_meta(p: dict) -> dict:
    """The JSON message that completes a depth frame: its identity and times, the state it was paired with, and what the
    navigator derived (points as {x, y, z, k}, drops as {ahead, left, h}: Lichtblick reads no arrays of arrays)."""
    m = {k: p[k] for k in ("rows", "cols", "frame_t_ns", "seq", "state_t_ns", "pair_dt_ms", "t_src", "state", "pose")
         if p.get(k) is not None}
    d = p.get("derived")
    if d is not None:
        m["derived"] = {"points": [{"x": x, "y": y, "z": z, "k": k} for x, y, z, k in d["points"]]}
        if d.get("drop_points") is not None:
            m["derived"]["drop_points"] = [{"ahead": a, "left": l_, "h": h} for a, l_, h in d["drop_points"]]
        if d.get("block_m") is not None:
            m["derived"]["block_m"] = d["block_m"]
    return m


def _objects_msg(p: dict) -> dict:
    """The semantic map as a message: a part as {x, y, hx, hy, yaw, z0, z1} and a change as {change, id} (Lichtblick's JSON-schema
    reader takes no arrays of arrays)."""
    return {"objects": [dict(o, parts=[dict(zip(PART_FIELDS, q)) for q in o.get("parts", [])]) for o in p["objects"]],
            "changes": [{"change": c[0], "id": c[1]} for c in p.get("changes", [])],
            "t_src": p.get("t_src"), "raw": _raw(p.get("raw", {}))}


def _objects_rec(o: dict, keep_raw: bool) -> dict:
    d = {"objects": [dict(x, parts=[[q[k] for k in PART_FIELDS] for q in x.get("parts", [])]) for x in o["objects"]],
         "changes": [[c["change"], c["id"]] for c in o.get("changes", [])]}
    if keep_raw:
        d.update(t_src=o.get("t_src"), raw=o.get("raw", {}))
    return d


def _stamp(ns: int) -> dict:
    return {"sec": ns // 10**9, "nsec": ns % 10**9}


def _quat(yaw: float) -> dict:
    return {"x": 0.0, "y": 0.0, "z": math.sin(yaw / 2), "w": math.cos(yaw / 2)}


def _yaw(q: dict) -> float:
    """The heading of any orientation (for a pure yaw the same as 2·atan2(z, w))."""
    return math.atan2(2 * (q["w"] * q["z"] + q["x"] * q["y"]), 1 - 2 * (q["y"] ** 2 + q["z"] ** 2))


def _pose(ns: int, frame: str, p, full: dict | None = None) -> dict:
    """A pose in the plane; with `full` ({z, quat: [w, x, y, z]}, ADR-0016) its height and whole orientation instead."""
    if full:
        w, x, y, z = full["quat"]
        return {"timestamp": _stamp(ns), "frame_id": frame,
                "pose": {"position": {"x": p[0], "y": p[1], "z": full["z"]}, "orientation": {"x": x, "y": y, "z": z, "w": w}}}
    return {"timestamp": _stamp(ns), "frame_id": frame,
            "pose": {"position": {"x": p[0], "y": p[1], "z": 0.0}, "orientation": _quat(p[2])}}


def signal_set(run: dict) -> SignalSet | None:
    """The run's declared signals as a message, or None when it declares none."""
    return SignalSet(run["signals"], run["robot"]["name"]) if run.get("signals") else None


def to_messages(t: float, kind: str, p: dict, base_ns: int, sigs: SignalSet | None = None) -> list:
    """[(topic, log_ns, publish_ns, data)] for one record, in the order they are written. `sigs` is the run's
    signal set: a `signals` record needs it."""
    ns = base_ns + max(0, round(t * 1e9))
    src = p.get("t_src")
    pub = round(src * 1e9) if isinstance(src, (int, float)) else ns
    pub = max(0, pub)

    def m(topic, obj):
        return (topic, ns, pub, _pb(topic, obj, ns) if topic in PROTO else _js(obj))

    if kind == "run":
        return [("/miniview/run", base_ns, base_ns, _js(p))]
    if kind == "epoch":
        x, y, yaw = p["map_to_world"]
        return [m("/tf", {"timestamp": _stamp(ns), "parent_frame_id": "world", "child_frame_id": "map",
                          "translation": {"x": x, "y": y, "z": 0.0}, "rotation": _quat(yaw)})]
    if kind == "tick":
        out = [m("/belief/pose", _pose(ns, "map", p["belief"]))]
        if p.get("truth"):
            out.append(m("/truth/pose", _pose(ns, "world", p["truth"], p.get("truth_3d"))))
        if p.get("depth") is not None:
            data = b"".join(POINT.pack(x, y, z, ord(k)) for x, y, z, k in p["depth"])
            out.append(m("/depth", {
                "timestamp": _stamp(ns), "frame_id": "map", "pose": {"position": {"x": 0, "y": 0, "z": 0},
                                                                     "orientation": _IDENT},
                "point_stride": POINT.size,
                "fields": [{"name": "x", "offset": 0, "type": FLOAT32}, {"name": "y", "offset": 4, "type": FLOAT32},
                           {"name": "z", "offset": 8, "type": FLOAT32}, {"name": "kind", "offset": 12, "type": UINT8}],
                "data": base64.b64encode(data).decode()}))
        if p.get("cmd") is not None:
            out.append(m("/miniview/command", {"vx": p["cmd"][0], "vyaw": p["cmd"][1]}))
        if p.get("tilt") is not None:
            out.append(m("/miniview/tilt", {"pitch_deg": p["tilt"][0], "roll_deg": p["tilt"][1]}))
        out.append(m("/miniview/tick_extra", {"t_src": src, "raw": _raw(p.get("raw", {}))}))
        return out
    if kind == "signals":
        if sigs is None:
            raise ValueError("a signals record in a run that declares no signals")
        return [(sigs.topic, ns, pub, sigs.encode(p["values"])),
                m("/miniview/tick_extra", {"t_src": src, "raw": _raw(p.get("raw", {}))})]
    if kind == "plan":
        return [m("/miniview/plan", {"path": _xy(p["path"]), "t_src": src, "raw": _raw(p.get("raw", {}))})]
    if kind == "world":
        g = p["grid"]
        cells = g["cells"].encode("ascii")
        if len(cells) != g["w"] * g["h"]:
            raise ValueError(f"grid cells: {len(cells)} for {g['w']} x {g['h']}")
        return [m("/map", {"timestamp": _stamp(ns), "frame_id": "map",
                           "pose": {"position": {"x": g["origin"][0], "y": g["origin"][1], "z": 0.0},
                                    "orientation": _IDENT},
                           "column_count": g["w"], "cell_size": {"x": g["res"], "y": g["res"]},
                           "row_stride": g["w"], "cell_stride": 1,
                           "fields": [{"name": "cell", "offset": 0, "type": UINT8}],
                           "data": base64.b64encode(cells).decode()}),
                m("/miniview/memory", {"obstacles": _xy(p["obstacles"]), "drops": _xy(p["drops"]),
                                       "raw": _raw(p.get("raw", {}))})]
    if kind == "event":
        e = {"kind": p["kind"], "text": p["text"], "notable": p.get("notable", True), "t_src": src,
             "raw": _raw(p.get("raw", {}))}
        if p.get("decision") is not None:
            e["decision"] = _raw(p["decision"])
        if p["kind"] == "room":
            e["room"], e["votes"] = p.get("room"), p.get("votes") or {}
        if p["kind"] == "area":
            e["area"] = p.get("area") or {}
        if p["kind"] == "site":
            e["site"] = p.get("site") or {}
        return [m("/miniview/event", e)]
    if kind == "depth_frame":
        rows, cols = p["rows"], p["cols"]
        if len(p["distance_mm"]) != rows * cols or len(p["status"]) != rows * cols:
            raise ValueError(f"depth frame: {len(p['distance_mm'])} distances and {len(p['status'])} statuses for {rows} x {cols}")
        dist = struct.pack(f"<{rows * cols}H", *(_u16(v) for v in p["distance_mm"]))
        return [m("/depth/raw", _raw_image(ns, rows, cols, "16UC1", cols * 2, dist)),
                m("/depth/status", _raw_image(ns, rows, cols, "mono8", cols, bytes(p["status"]))),
                m("/miniview/depth_frame", _depth_frame_meta(p))]
    if kind == "objects":
        return [m("/miniview/objects", _objects_msg(p))]
    if kind == "sighting":
        return [m("/miniview/sighting", {"pose": p["pose"], "hfov_deg": p["hfov_deg"], "range_m": p["range_m"], "seen": p["seen"],
                                     "t_src": src, "raw": _raw(p.get("raw", {}))})]
    if kind == "segment":
        return [m("/miniview/segment", p)]
    if kind == "end":
        return [m("/miniview/end", p)]
    raise ValueError(f"unknown record kind {kind!r}")


# The tick protocol (ADR-0007, extended by ADR-0013): a tick is /belief/pose first, then at most one each of /truth/pose,
# /depth, /miniview/command, /miniview/tilt in that order, then /miniview/tick_extra last; a signals tick is the robot's
# /<robot>/signals message, then /miniview/tick_extra. A world is /map then /miniview/memory. Nothing else is written
# between the first and the last message of a tick or a world.
TICK_PARTS = ("truth", "depth", "cmd", "tilt")
TICK_TOPICS = {"belief": "/belief/pose", "truth": "/truth/pose", "depth": "/depth", "cmd": "/miniview/command",
               "tilt": "/miniview/tilt", "extra": "/miniview/tick_extra"}
TICK_INSIDE = {"/truth/pose", "/depth", "/miniview/command", "/miniview/tilt", "/miniview/tick_extra"}
FRAMES = {"/belief/pose": "map", "/truth/pose": "world", "/depth": "map", "/map": "map", "/depth/raw": SENSOR_FRAME,
          "/depth/status": SENSOR_FRAME}     # a message's frame_id
INSIDE = {"tick": TICK_INSIDE, "world": {"/miniview/memory"}, "signals": {"/miniview/tick_extra"},   # what may follow a record's first message
          "depth_frame": {"/depth/status", "/miniview/depth_frame"}}


def tick_part(name: str, t: float, value, base_ns: int, t_src: float | None = None, truth_3d: dict | None = None) -> tuple:
    """The one message (topic, log_ns, publish_ns, data) of a part of a tick: belief, truth (with its whole pose when given,
    ADR-0016), depth, cmd, tilt or extra."""
    p = {"belief": [0.0, 0.0, 0.0], "t_src": t_src, "raw": value if name == "extra" else {}, "truth_3d": truth_3d}
    if name not in ("belief", "extra"):
        p[name] = value
    elif name == "belief":
        p["belief"] = value
    topic = TICK_TOPICS[name]
    return next(m for m in to_messages(t, "tick", p, base_ns) if m[0] == topic)


def signals_part(t: float, values: dict, base_ns: int, sigs: SignalSet, t_src: float | None = None) -> tuple:
    """The first message of a signals tick (a tick of the robot's named values, with no pose): then comes `tick_part("extra", ...)`."""
    return to_messages(t, "signals", {"values": values, "t_src": t_src}, base_ns, sigs)[0]


class Assembler:
    """Messages (topic, log_ns, data) in file order -> records (t, kind, payload).

    `keep_raw` keeps `raw` and `t_src` and the events that are not notable, what a copy of the
    source needs; the viewer's view of a run drops them."""

    def __init__(self, keep_raw: bool = False):
        self.keep_raw = keep_raw
        self.base_ns = None
        self.run = None
        self.sigs = None              # the run's signal set, once its run record is read
        self.pending = None           # a tick or world whose last message has not arrived
        self.partials = 0             # ticks and worlds dropped for lack of their last message
        self.partial_msgs = []        # why, one line each, until drained

    def _interrupt(self, by: str, t: float) -> None:
        """A tick or a world was started and another record came before its last message: it is dropped, and said."""
        if self.pending:
            self.partials += 1
            self.partial_msgs.append(f"{self.pending[1]} at t={self.pending[0]}: interrupted by {by} at t={t}")
            self.pending = None

    def drain(self) -> list:
        out, self.partial_msgs = self.partial_msgs, []
        return out

    def _t(self, ns: int) -> float:
        return round((ns - self.base_ns) / 1e9, 6)

    def feed(self, topic: str, ns: int, data: bytes) -> list:
        """The records this message completes (usually none or one). ValueError for what is not ours."""
        if self.sigs is not None and topic == self.sigs.topic:
            o = self.sigs.decode(data)
        else:
            o = _unpb(topic, data) if topic in PROTO else json.loads(data)
        if topic == "/miniview/run":
            self.base_ns, self.run = ns, o
            try:
                self.sigs = signal_set(o)
            except (KeyError, TypeError, ValueError):
                self.sigs = None                 # the run record says what is wrong with it (validate); no signals are read
            return [(0.0, "run", o)]
        if self.base_ns is None:
            raise ValueError("a message before the run record")
        t = self._t(ns)
        if self.pending and topic not in INSIDE[self.pending[1]]:
            self._interrupt(topic, t)
        if self.sigs is not None and topic == self.sigs.topic:
            self.pending = (t, "signals", {"values": o})
            return []
        if topic in FRAMES and o.get("frame_id") != FRAMES[topic]:
            raise ValueError(f"{topic}: frame_id {o.get('frame_id')!r}, expected {FRAMES[topic]!r}")
        if topic == "/tf":
            if (o.get("parent_frame_id"), o.get("child_frame_id")) != ("world", "map"):
                raise ValueError(f"/tf is {o.get('parent_frame_id')!r} <- {o.get('child_frame_id')!r}, expected world <- map")
            return [(t, "epoch", {"map_to_world": [round(o["translation"]["x"], 5), round(o["translation"]["y"], 5),
                                                    round(_yaw(o["rotation"]), 5)]})]
        if topic == "/belief/pose":
            p = o["pose"]
            self.pending = (t, "tick", {"belief": [round(p["position"]["x"], 4), round(p["position"]["y"], 4),
                                                   round(_yaw(p["orientation"]), 4)],
                                        "truth": None, "tilt": None, "cmd": None, "depth": None})
            return []
        if topic == "/map":
            g, c = o, o["cell_size"]["x"]
            self.pending = (t, "world", {"grid": {"res": c, "origin": [g["pose"]["position"]["x"],
                                                                      g["pose"]["position"]["y"]],
                                                  "w": g["column_count"], "h": len(base64.b64decode(g["data"])) //
                                                  max(g["row_stride"], 1),
                                                  "cells": base64.b64decode(g["data"]).decode("ascii")}})
            return []
        if topic == "/depth/raw":
            w, h = o["width"], o["height"]
            vals = struct.unpack(f"<{w * h}H", base64.b64decode(o["data"])[:w * h * 2])
            self.pending = (t, "depth_frame", {"rows": h, "cols": w, "distance_mm": [_i16(v) for v in vals]})
            return []
        if topic == "/depth/status":
            if not self.pending or self.pending[1] != "depth_frame":
                raise ValueError("depth status outside a depth frame")
            self.pending[2]["status"] = list(base64.b64decode(o["data"]))
            return []
        if topic == "/miniview/depth_frame":
            if not self.pending or self.pending[1] != "depth_frame" or "status" not in self.pending[2]:
                raise ValueError("depth frame metadata outside a depth frame")
            pt, kind, d = self.pending
            self.pending = None
            # the paired state and the pose are small and the eye needs them (RFC-0013: where the sensor was); `derived` and `t_src` stay the replay's
            for k in ("frame_t_ns", "seq", "state_t_ns", "pair_dt_ms", "state", "pose"):
                if k in o:
                    d[k] = o[k]
            if self.keep_raw:
                d.update({k: o[k] for k in ("t_src",) if k in o})
                if "derived" in o:
                    der = o["derived"]
                    d["derived"] = {"points": [[q["x"], q["y"], q["z"], q["k"]] for q in der["points"]]}
                    if "drop_points" in der:
                        d["derived"]["drop_points"] = [[q["ahead"], q["left"], q["h"]] for q in der["drop_points"]]
                    if "block_m" in der:
                        d["derived"]["block_m"] = der["block_m"]
            return [(pt, kind, d)]
        if topic in ("/truth/pose", "/depth", "/miniview/command", "/miniview/tilt"):
            if not self.pending or self.pending[1] != "tick":
                raise ValueError(f"{topic} outside a tick")
            d = self.pending[2]
            if topic == "/truth/pose":
                p = o["pose"]
                q = p["orientation"]
                d["truth"] = [round(p["position"]["x"], 4), round(p["position"]["y"], 4), round(_yaw(q), 4)]
                if p["position"].get("z") or q.get("x") or q.get("y"):     # a height or a tilt: the whole pose (ADR-0016)
                    d["truth_3d"] = {"z": round(p["position"].get("z", 0.0), 4),
                                     "quat": [round(q.get(k, 0.0), 6) for k in ("w", "x", "y", "z")]}
            elif topic == "/depth":
                raw = base64.b64decode(o["data"])
                d["depth"] = [[round(x, 4), round(y, 4), round(z, 4), chr(k)]
                              for x, y, z, k in POINT.iter_unpack(raw[:len(raw) // POINT.size * POINT.size])]
            elif topic == "/miniview/command":
                d["cmd"] = [o["vx"], o["vyaw"]]
            else:
                d["tilt"] = [o["pitch_deg"], o["roll_deg"]]
            return []
        if topic == "/miniview/tick_extra":
            if not self.pending or self.pending[1] not in ("tick", "signals"):
                raise ValueError("tick_extra outside a tick")
            pt, kind, d = self.pending
            self.pending = None
            if self.keep_raw:
                d.update(t_src=o["t_src"], raw=o["raw"])
            return [(pt, kind, d)]
        if topic == "/miniview/memory":
            if not self.pending or self.pending[1] != "world":
                raise ValueError("memory outside a world")
            pt, kind, d = self.pending
            self.pending = None
            d.update(obstacles=_unxy(o["obstacles"]), drops=_unxy(o["drops"]))
            if self.keep_raw:
                d["raw"] = o["raw"]
            return [(pt, kind, d)]
        if topic == "/miniview/plan":
            d = {"path": _unxy(o["path"])}
            if self.keep_raw:
                d.update(t_src=o.get("t_src"), raw=o.get("raw", {}))
            return [(t, "plan", d)]
        if topic == "/miniview/event":
            if not o.get("notable", True) and o["kind"] not in ALWAYS_NOTABLE and not self.keep_raw:
                return []
            d = {"kind": o["kind"], "text": o["text"]}
            if o["kind"] == "aborted":                     # a stop before the navigator contract: named by its reason now
                d["kind"] = stop_before((o.get("raw") or {}).get("why") or o["text"].removeprefix("aborted why "))
                d["text"] = d["kind"] + o["text"].removeprefix("aborted")
            if o.get("decision") is not None:
                d["decision"] = o["decision"]
            if o["kind"] == "room":
                d["room"], d["votes"] = o.get("room"), o.get("votes") or {}
            if o["kind"] == "area":
                d["area"] = o.get("area") or {}
            if o["kind"] == "site":
                d["site"] = o.get("site") or {}
            if self.keep_raw:
                d.update(notable=o.get("notable", True), t_src=o.get("t_src"), raw=o.get("raw", {}))
            return [(t, "event", d)]
        if topic == "/miniview/objects":
            return [(t, "objects", _objects_rec(o, self.keep_raw))]
        if topic in ("/miniview/sighting", "/miniview/look"):        # `look` is what a file written before the rename (ADR-0019) calls it
            d = {k: o[k] for k in ("pose", "hfov_deg", "range_m", "seen")}
            if self.keep_raw:
                d.update(t_src=o.get("t_src"), raw=o.get("raw", {}))
            return [(t, "sighting", d)]
        if topic in ("/miniview/segment", "/miniview/end"):
            return [(t, topic.rsplit("/", 1)[1], o)]
        raise ValueError(f"unknown topic {topic!r}")
