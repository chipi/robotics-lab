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

from miniview import schemas

KINDS = ("run", "epoch", "tick", "plan", "world", "event", "segment", "end")

CHANNELS = {                          # topic -> schema
    "/miniview/run": "miniview.run",
    "/tf": "foxglove.FrameTransform",
    "/belief/pose": "foxglove.PoseInFrame",
    "/truth/pose": "foxglove.PoseInFrame",
    "/depth": "foxglove.PointCloud",
    "/miniview/command": "miniview.command",
    "/miniview/tilt": "miniview.tilt",
    "/miniview/tick_extra": "miniview.tick_extra",
    "/miniview/plan": "miniview.plan",
    "/map": "foxglove.Grid",
    "/miniview/memory": "miniview.memory",
    "/miniview/event": "miniview.event",
    "/miniview/segment": "miniview.segment",
    "/miniview/end": "miniview.end",
}
POINT = struct.Struct("<fffB")
UINT8, FLOAT32 = 1, 7
_IDENT = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


PROTO = {"/belief/pose": "PoseInFrame", "/truth/pose": "PoseInFrame", "/tf": "FrameTransform", "/map": "Grid",
         "/depth": "PointCloud"}      # the Foxglove channels are protobuf (ADR-0007); our own kinds are JSON


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


def _stamp(ns: int) -> dict:
    return {"sec": ns // 10**9, "nsec": ns % 10**9}


def _quat(yaw: float) -> dict:
    return {"x": 0.0, "y": 0.0, "z": math.sin(yaw / 2), "w": math.cos(yaw / 2)}


def _yaw(q: dict) -> float:
    return 2 * math.atan2(q["z"], q["w"])


def _pose(ns: int, frame: str, p) -> dict:
    return {"timestamp": _stamp(ns), "frame_id": frame,
            "pose": {"position": {"x": p[0], "y": p[1], "z": 0.0}, "orientation": _quat(p[2])}}


def to_messages(t: float, kind: str, p: dict, base_ns: int) -> list:
    """[(topic, log_ns, publish_ns, data)] for one record, in the order they are written."""
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
            out.append(m("/truth/pose", _pose(ns, "world", p["truth"])))
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
        return [m("/miniview/event", {"kind": p["kind"], "text": p["text"], "notable": p.get("notable", True),
                                      "t_src": src, "raw": _raw(p.get("raw", {}))})]
    if kind == "segment":
        return [m("/miniview/segment", p)]
    if kind == "end":
        return [m("/miniview/end", p)]
    raise ValueError(f"unknown record kind {kind!r}")


# The tick protocol (ADR-0007): a tick is /belief/pose first, then at most one each of /truth/pose, /depth,
# /miniview/command, /miniview/tilt in that order, then /miniview/tick_extra last. A world is /map then /miniview/memory.
# Nothing else is written between the first and the last message of a tick or a world.
TICK_PARTS = ("truth", "depth", "cmd", "tilt")
TICK_TOPICS = {"belief": "/belief/pose", "truth": "/truth/pose", "depth": "/depth", "cmd": "/miniview/command",
               "tilt": "/miniview/tilt", "extra": "/miniview/tick_extra"}
TICK_INSIDE = {"/truth/pose", "/depth", "/miniview/command", "/miniview/tilt", "/miniview/tick_extra"}
FRAMES = {"/belief/pose": "map", "/truth/pose": "world", "/depth": "map", "/map": "map"}     # a message's frame_id


def tick_part(name: str, t: float, value, base_ns: int, t_src: float | None = None) -> tuple:
    """The one message (topic, log_ns, publish_ns, data) of a part of a tick: belief, truth, depth, cmd, tilt or extra."""
    p = {"belief": [0.0, 0.0, 0.0], "t_src": t_src, "raw": value if name == "extra" else {}}
    if name not in ("belief", "extra"):
        p[name] = value
    elif name == "belief":
        p["belief"] = value
    topic = TICK_TOPICS[name]
    return next(m for m in to_messages(t, "tick", p, base_ns) if m[0] == topic)


class Assembler:
    """Messages (topic, log_ns, data) in file order -> records (t, kind, payload).

    `keep_raw` keeps `raw` and `t_src` and the events that are not notable, what a copy of the
    source needs; the viewer's view of a run drops them."""

    def __init__(self, keep_raw: bool = False):
        self.keep_raw = keep_raw
        self.base_ns = None
        self.run = None
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
        o = _unpb(topic, data) if topic in PROTO else json.loads(data)
        if topic == "/miniview/run":
            self.base_ns, self.run = ns, o
            return [(0.0, "run", o)]
        if self.base_ns is None:
            raise ValueError("a message before the run record")
        t = self._t(ns)
        if self.pending and not (
                (self.pending[1] == "tick" and topic in TICK_INSIDE) or (self.pending[1] == "world" and topic == "/miniview/memory")):
            self._interrupt(topic, t)
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
        if topic in ("/truth/pose", "/depth", "/miniview/command", "/miniview/tilt"):
            if not self.pending or self.pending[1] != "tick":
                raise ValueError(f"{topic} outside a tick")
            d = self.pending[2]
            if topic == "/truth/pose":
                p = o["pose"]
                d["truth"] = [round(p["position"]["x"], 4), round(p["position"]["y"], 4), round(_yaw(p["orientation"]), 4)]
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
            if not self.pending or self.pending[1] != "tick":
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
            if not o.get("notable", True) and not self.keep_raw:
                return []
            d = {"kind": o["kind"], "text": o["text"]}
            if self.keep_raw:
                d.update(notable=o.get("notable", True), t_src=o.get("t_src"), raw=o.get("raw", {}))
            return [(t, "event", d)]
        if topic in ("/miniview/segment", "/miniview/end"):
            return [(t, topic.rsplit("/", 1)[1], o)]
        raise ValueError(f"unknown topic {topic!r}")
