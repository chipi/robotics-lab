"""A robot's named values, one record per tick of its own (ADR-0013): power, tacho counts, sensor readings, the running program.

The run record declares them (`signals`: name, kind `number` or `text`, optional unit); a tick of values is one message on
`/<robot>/signals`, a protobuf message built from that declaration at run time: one optional field per signal (a double or a
string), so a signal missing from a tick is absent, not zero. The schema stored in the file is the message's own
FileDescriptorSet, so a reader that knows nothing of miniview (Rerun, Lichtblick) decodes the values by name. Rerun 0.43.2
turns the channel into one entity whose struct has a Float64 or Utf8 column per signal (ADR-0013).
"""

import math
import re

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
KINDS = ("number", "text")
_F = descriptor_pb2.FieldDescriptorProto


def check_decl(decl) -> str | None:
    """None when `decl` is a usable declaration (a list of {name, kind, unit?}), else why not."""
    if not isinstance(decl, list) or not decl:
        return "signals is not a non-empty list"
    seen = set()
    for d in decl:
        if not isinstance(d, dict):
            return "a signal is not an object"
        name = d.get("name")
        if not isinstance(name, str) or not NAME.match(name):
            return f"signal name {name!r}: a letter, then letters, digits and _ (at most 64)"
        if name in seen:
            return f"signal {name!r} declared twice"
        seen.add(name)
        if d.get("kind") not in KINDS:
            return f"signal {name!r}: kind {d.get('kind')!r} is not one of {KINDS}"
        if d.get("unit") is not None and not isinstance(d["unit"], str):
            return f"signal {name!r}: unit is not text"
    return None


def value_error(kind: str, v) -> str | None:
    if kind == "number":
        return None if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else "is not a finite number"
    return None if isinstance(v, str) else "is not text"


class SignalSet:
    """The declared signals of a run, the topic they travel on, and the message that carries them."""

    def __init__(self, decl: list, robot: str):
        err = check_decl(decl)
        if err:
            raise ValueError(err)
        self.decl = [dict(d) for d in decl]
        self.kinds = {d["name"]: d["kind"] for d in self.decl}
        self.topic = f"/{robot}/signals"
        fd = descriptor_pb2.FileDescriptorProto(name="miniview/signals.proto", package="miniview", syntax="proto3")
        msg = fd.message_type.add(name="Signals")
        for i, d in enumerate(self.decl):
            msg.field.add(name=d["name"], number=i + 1, label=_F.LABEL_OPTIONAL, proto3_optional=True, oneof_index=i,
                          type=_F.TYPE_DOUBLE if d["kind"] == "number" else _F.TYPE_STRING)
        for d in self.decl:
            msg.oneof_decl.add(name="_" + d["name"])        # proto3 `optional` is a one-field oneof: present or absent
        out = descriptor_pb2.FileDescriptorSet()
        out.file.add().CopyFrom(fd)
        self.descriptor_set = out.SerializeToString()
        pool = descriptor_pool.DescriptorPool()
        pool.Add(fd)
        self._cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("miniview.Signals"))

    def encode(self, values: dict) -> bytes:
        msg = self._cls()
        for name, v in values.items():
            if name not in self.kinds:
                raise ValueError(f"signal {name!r} is not declared")
            bad = value_error(self.kinds[name], v)
            if bad:
                raise ValueError(f"signal {name!r} {bad}")
            setattr(msg, name, float(v) if self.kinds[name] == "number" else v)
        return msg.SerializeToString()

    def decode(self, data: bytes) -> dict:
        msg = self._cls()
        msg.ParseFromString(data)
        return {f.name: getattr(msg, f.name) for f, _ in msg.ListFields()}

    def check(self, values: dict) -> str | None:
        """None when every value is declared and of its kind, else why not (a record's check against its run)."""
        for name, v in values.items():
            if name not in self.kinds:
                return f"signal {name!r} is not declared"
            bad = value_error(self.kinds[name], v)
            if bad:
                return f"signal {name!r} {bad}"
        return None
