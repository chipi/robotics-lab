"""Runs as MCAP files (ADR-0004: the record of truth), written so they can be followed while they grow
(ADR-0005: a live run is a run that has not ended).

One channel per record kind (`/miniview/<kind>`), JSON messages, the record's time as log time in
nanoseconds. The writer does not chunk: each message is on disk once `add` returns, so a reader of
the growing file sees it at once. `Follower` reads only complete records and resumes where it
stopped; a finished file reads the same way, so there is one reader for both.
"""

import io
import json
import struct
from pathlib import Path

from mcap.exceptions import EndOfFile
from mcap.opcode import Opcode
from mcap.records import Channel, Message
from mcap.stream_reader import StreamReader
from mcap.writer import CompressionType, Writer

KINDS = ("run", "epoch", "tick", "plan", "world", "event", "end")
MAGIC = b"\x89MCAP0\r\n"
PROFILE = "miniview"


class Recorder:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(path, "wb")
        self._w = Writer(self._fh, use_chunking=False, compression=CompressionType.NONE)
        self._w.start(profile=PROFILE, library="miniview")
        self._ch = {}
        for k in KINDS:
            sid = self._w.register_schema(f"miniview.{k}", "jsonschema", b'{"type":"object"}')
            self._ch[k] = self._w.register_channel(f"/miniview/{k}", "json", sid)
        self._fh.flush()

    def add(self, t: float, kind: str, payload: dict) -> None:
        ns = max(0, round(t * 1e9))
        self._w.add_message(self._ch[kind], ns, json.dumps(payload, separators=(",", ":")).encode(), ns)

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        self._w.finish()
        self._fh.close()


def write(path: Path, records) -> None:
    rec = Recorder(path)
    for t, kind, p in records:
        rec.add(t, kind, p)
    rec.close()


class Follower:
    """Reads the records added to an MCAP file since the last call; safe on a file still being written."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.offset = 0
        self.topics = {}
        self.done = False         # the footer was read: the file is complete

    def poll(self) -> list:
        if self.done or not self.path.exists():
            return []
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            buf = fh.read()
        pos = 0
        if self.offset == 0:
            if len(buf) < len(MAGIC):
                return []
            if buf[:len(MAGIC)] != MAGIC:
                raise ValueError(f"{self.path}: not an MCAP file")
            pos = len(MAGIC)
        end = pos
        while end + 9 <= len(buf):
            op, length = struct.unpack_from("<BQ", buf, end)
            if end + 9 + length > len(buf):
                break                                   # a record still being written
            if op == Opcode.DATA_END:                   # the summary and footer follow: nothing new
                self.done = True
                break
            end += 9 + length
        out = []
        if end > pos:
            it = StreamReader(io.BytesIO(buf[pos:end]), skip_magic=True).records
            while True:
                try:
                    rec = next(it)
                except (StopIteration, EndOfFile):    # the slice holds whole records only: its end is a boundary
                    break
                if isinstance(rec, Channel):
                    self.topics[rec.id] = rec.topic
                elif isinstance(rec, Message):
                    topic = self.topics.get(rec.channel_id, "")
                    if topic.startswith("/miniview/"):
                        out.append((rec.log_time / 1e9, topic[len("/miniview/"):], json.loads(rec.data)))
        self.offset += end
        return out


def read(path: Path) -> list:
    return Follower(path).poll()
