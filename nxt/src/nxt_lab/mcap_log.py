"""Runs as MCAP (RFC-0007): the open log format the viewers read (Foxglove, Lichtblick, Rerun).

One file per recording, next to its CSV. JSON messages with JSON Schemas, on two topics:

- /nxt/state   every sample: commanded powers, tacho counts, sensors, the running program, and
               robotd-lite's last answer
- /nxt/events  the command log while recording: drives, stops, safety stops, fire, programs, setup
"""

import json
import time
from pathlib import Path

from mcap.writer import CompressionType, Writer

STATE_SCHEMA = {
    "type": "object",
    "title": "nxt_lab.State",
    "properties": {
        "t": {"type": "number", "description": "seconds since the recording started"},
        "power_left": {"type": "integer"},
        "power_right": {"type": "integer"},
        "tacho": {"type": "object", "description": "degrees per motor port",
                  "additionalProperties": {"type": "integer"}},
        "sensors": {"type": "object", "description": "per sensor port: value, and label for colour",
                    "additionalProperties": {"type": "object"}},
        "program": {"type": ["string", "null"]},
        "deadman": {"type": ["object", "null"], "description": "robotd-lite's last answer"},
    },
}
EVENT_SCHEMA = {
    "type": "object",
    "title": "nxt_lab.Event",
    "properties": {
        "seq": {"type": "integer"},
        "at": {"type": "string", "description": "local time, ISO 8601"},
        "kind": {"type": "string"},
        "ok": {"type": "boolean"},
    },
    "additionalProperties": True,
}


class McapLog:
    def __init__(self, path: Path, metadata: dict):
        self.path = path
        self._file = open(path, "wb")
        self._writer = Writer(self._file, compression=CompressionType.ZSTD)
        self._writer.start(profile="", library="nxt-lab")
        self._channels = {}
        for topic, schema in (("/nxt/state", STATE_SCHEMA), ("/nxt/events", EVENT_SCHEMA)):
            schema_id = self._writer.register_schema(name=schema["title"], encoding="jsonschema",
                                                     data=json.dumps(schema).encode())
            self._channels[topic] = self._writer.register_channel(topic=topic, message_encoding="json",
                                                                   schema_id=schema_id)
        self._writer.add_metadata("nxt_lab.run", {k: str(v) for k, v in metadata.items()})
        self._seq = {topic: 0 for topic in self._channels}

    def write(self, topic: str, message: dict, log_time_ns: int | None = None) -> None:
        now = log_time_ns or time.time_ns()
        self._seq[topic] += 1
        self._writer.add_message(channel_id=self._channels[topic], log_time=now, publish_time=now,
                                 sequence=self._seq[topic], data=json.dumps(message).encode())

    def close(self) -> None:
        try:
            self._writer.finish()
        finally:
            self._file.close()
