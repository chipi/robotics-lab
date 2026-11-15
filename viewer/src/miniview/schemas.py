"""The schemas of a format 2 run (ADR-0007): Foxglove's protobuf schemas (the foxglove-schemas-protobuf package) for the
standard shapes, our own `miniview.*` JSON schemas for the rest. Foxglove's published JSON schemas stay copied in schemas/
(MIT, github.com/foxglove/schemas) as the reference the tests check the protobuf messages against."""

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


def message_class(short: str):
    """The protobuf class of a Foxglove schema ("PoseInFrame"), from the foxglove-schemas-protobuf package."""
    import importlib

    return getattr(importlib.import_module(f"foxglove_schemas_protobuf.{short}_pb2"), short)


def descriptor_set(short: str) -> bytes:
    """The FileDescriptorSet of a Foxglove message: its file and every file it imports, dependencies first."""
    from google.protobuf import descriptor_pb2

    out, seen = descriptor_pb2.FileDescriptorSet(), set()

    def add(fd):
        if fd.name in seen:
            return
        seen.add(fd.name)
        for dep in fd.dependencies:
            add(dep)
        fd.CopyToProto(out.file.add())

    add(message_class(short).DESCRIPTOR.file)
    return out.SerializeToString()


def schema_for(name: str) -> tuple:
    """(encoding, data) of a schema as the file stores it: `foxglove.X` is a protobuf descriptor set, `miniview.x` a JSON schema."""
    ns, _, short = name.partition(".")
    if ns == "foxglove":
        return "protobuf", descriptor_set(short)
    return "jsonschema", json.dumps(dict(MINIVIEW[short], title=name), separators=(",", ":")).encode()


def schema_bytes(name: str) -> bytes:
    """The JSON schema for `foxglove.X` (the published one, kept for the tests) or `miniview.x`."""
    ns, _, short = name.partition(".")
    obj = foxglove(short) if ns == "foxglove" else dict(MINIVIEW[short], title=name)
    return json.dumps(obj, separators=(",", ":")).encode()
