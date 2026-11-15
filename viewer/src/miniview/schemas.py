"""The schemas of a format 2 run (ADR-0007): Foxglove's published JSON schemas (copied from
github.com/foxglove/schemas, MIT, in schemas/) for the standard shapes, our own `miniview.*` for the rest."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent / "schemas"
FOXGLOVE = ("PoseInFrame", "FrameTransform", "Grid", "PointCloud")


def _obj(required: list, **props) -> dict:
    return {"type": "object", "properties": props, "required": required}


_NUM, _INT, _STR = {"type": "number"}, {"type": "integer"}, {"type": "string"}
_ARR = {"type": "array", "items": _NUM}
# Points as objects, never arrays of arrays, and every array with its item type: Lichtblick's reader
# of JSON schemas rejects both (checked 2026-11-15 on the Lichtblick of `make viewers`).
_POINTS = {"type": "array", "items": {"type": "object", "properties": {"x": _NUM, "y": _NUM}, "required": ["x", "y"]}}
_RAW = {"type": "object", "description": "every source field the record has no field of its own for"}

MINIVIEW = {
    "run": _obj(["format", "key", "uuid", "robot", "scene", "kind", "started_at_ns", "started_at_source", "writer"],
                format=_INT, key=_STR, uuid=_STR, robot={"type": "object"}, scene=_STR, kind=_STR,
                started_at_ns=_INT, started_at_source=_STR, writer={"type": "object"}, source={"type": "object"}),
    "segment": _obj(["index", "t_start", "t_end"], index=_INT, goal=_ARR, outcome=_STR, origin_src=_NUM,
                    t_start=_NUM, t_end=_NUM),
    "event": _obj(["kind", "text"], kind=_STR, text=_STR, notable={"type": "boolean"}, t_src=_NUM, raw=_RAW),
    "plan": _obj(["path"], path=_POINTS, t_src=_NUM, raw=_RAW),
    "command": _obj(["vx", "vyaw"], vx=_NUM, vyaw=_NUM),
    "tilt": _obj(["pitch_deg", "roll_deg"], pitch_deg=_NUM, roll_deg=_NUM),
    "memory": _obj(["obstacles", "drops"], obstacles=_POINTS, drops=_POINTS, raw=_RAW),
    "tick_extra": _obj(["t_src", "raw"], t_src=_NUM, raw=_RAW),
    "end": _obj(["verdict"], verdict=_STR, source_sha256=_STR),
}


def foxglove(name: str) -> dict:
    return json.loads((HERE / f"foxglove.{name}.json").read_text())


def schema_bytes(name: str) -> bytes:
    """The JSON schema for `foxglove.X` or `miniview.x`, as the file stores it."""
    ns, _, short = name.partition(".")
    obj = foxglove(short) if ns == "foxglove" else dict(MINIVIEW[short], title=name)
    return json.dumps(obj, separators=(",", ":")).encode()
