"""Runs as MCAP files, format 2 (ADR-0007): written so they can be followed while they grow, closed into
a compact, indexed file.

    <run>/run.live.mcap + writer.lock   while written: unchunked, flushed after every record
    <run>/run.mcap                      when done: zstd chunks, message indexes, summary

`Recorder` is the only writer (the lock is created exclusively). `Follower` reads only complete
records, resumes where it stopped, and reads the compacted file the same way, so one reader serves a
finished run and a live one. The messages' shapes are in `miniview.wire`.
"""

import io
import json
import os
import socket
import struct
import time
import uuid as uuidlib
from pathlib import Path

from mcap.exceptions import EndOfFile
from mcap.opcode import Opcode
from mcap.records import Channel, Header, Message, Schema
from mcap.stream_reader import StreamReader
from mcap.writer import CompressionType, Writer

from miniview import keys, schemas, wire

FORMAT = 2
LIVE, FINAL, LOCK = "run.live.mcap", "run.mcap", "writer.lock"
MAGIC = b"\x89MCAP0\r\n"
PROFILE = "miniview"
VERSION = "0.2"


class WriterBusy(Exception):
    """The run already exists or has a writer."""


def new_run(key: str, robot: dict, scene: str, kind: str, started_at_ns: int, started_at_source: str = "writer",
            source: dict | None = None, run_uuid: str | None = None) -> dict:
    keys.split_key(key)
    rec = {"format": FORMAT, "key": key, "uuid": run_uuid or str(uuidlib.uuid4()), "robot": robot, "scene": scene,
           "kind": kind, "started_at_ns": int(started_at_ns), "started_at_source": started_at_source,
           "writer": {"program": "miniview", "version": VERSION}}
    if source:
        rec["source"] = source
    return rec


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_info(run_dir: Path) -> dict | None:
    try:
        return json.loads((Path(run_dir) / LOCK).read_text())
    except (OSError, ValueError):
        return None


def writer_alive(run_dir: Path) -> bool:
    """A lock whose PID is alive on this host. A lock from another host cannot be checked: alive."""
    info = lock_info(run_dir)
    if not info:
        return (Path(run_dir) / LOCK).exists()
    if info.get("host") != socket.gethostname():
        return True
    return pid_alive(int(info.get("pid", 0)))


class Recorder:
    def __init__(self, run_dir: Path, run: dict):
        self.dir = Path(run_dir)
        key = run["key"]
        if self.dir.parts[-3:] != tuple(keys.split_key(key)):
            raise ValueError(f"run key {key!r} does not match the folder {self.dir}")
        self.dir.mkdir(parents=True, exist_ok=True)
        if (self.dir / FINAL).exists():
            raise WriterBusy(f"{key} already exists ({self.dir / FINAL})")
        try:
            fd = os.open(self.dir / LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise WriterBusy(f"{key} has a writer ({self.dir / LOCK})") from None
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "started_at_ns": time.time_ns()}))
        try:
            self._fh = open(self.dir / LIVE, "xb")
        except FileExistsError:
            (self.dir / LOCK).unlink()
            raise WriterBusy(f"{key} has a live file ({self.dir / LIVE})") from None
        self.base_ns = run["started_at_ns"]
        self.last_t = 0.0
        self.ended = False
        self._w = Writer(self._fh, use_chunking=False, compression=CompressionType.NONE)
        self._w.start(profile=PROFILE, library=f"miniview {VERSION}")
        self._ch = {}
        for topic, name in wire.CHANNELS.items():
            sid = self._w.register_schema(name, "jsonschema", schemas.schema_bytes(name))
            self._ch[topic] = self._w.register_channel(topic, "json", sid)
        self._emit(0.0, "run", run)

    def _emit(self, t: float, kind: str, p: dict) -> None:
        for topic, ns, pub, data in wire.to_messages(t, kind, p, self.base_ns):
            self._w.add_message(self._ch[topic], ns, data, pub)
        self._fh.flush()

    def add(self, t: float, kind: str, payload: dict) -> None:
        if self.ended:
            raise ValueError("the run has ended")
        if t < self.last_t - 1e-9:
            raise ValueError(f"time goes back: {t} after {self.last_t}")
        self.last_t = max(self.last_t, t)
        self._emit(t, kind, payload)
        self.ended = kind == "end"

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> Path:
        """Compact into run.mcap and remove the live file and the lock. Writes `end` (ended) if the run has none."""
        if not self.ended:
            self.add(self.last_t, "end", {"verdict": "ended"})
        self._fh.close()
        return compact(self.dir)


def _complete_end(buf: bytes, pos: int) -> int:
    """The offset after the last whole record in buf[pos:]; stops at a footer's DATA_END."""
    end = pos
    while end + 9 <= len(buf):
        op, length = struct.unpack_from("<BQ", buf, end)
        if op == Opcode.DATA_END or end + 9 + length > len(buf):
            break
        end += 9 + length
    return end


def _records(buf: bytes, pos: int, end: int):
    it = StreamReader(io.BytesIO(buf[pos:end]), skip_magic=True).records
    while True:
        try:
            yield next(it)
        except (StopIteration, EndOfFile):
            return


def compact(run_dir: Path, stopped: bool = False) -> Path:
    """run.live.mcap -> run.mcap (zstd chunks, message indexes, summary). With `stopped`, a run with no
    `end` gets one with the verdict `stopped` (a writer that died). Removes the live file and the lock."""
    run_dir = Path(run_dir)
    live, tmp, final = run_dir / LIVE, run_dir / (FINAL + ".tmp"), run_dir / FINAL
    buf = live.read_bytes()
    if buf[:len(MAGIC)] != MAGIC:
        raise ValueError(f"{live}: not an MCAP file")
    end = _complete_end(buf, len(MAGIC))
    schema_map, chan_map, ch_by_topic, topics = {}, {}, {}, {}
    base, last_ns, has_end = None, 0, False
    with open(tmp, "wb") as fh:
        w = Writer(fh, use_chunking=True, compression=CompressionType.ZSTD)
        for rec in _records(buf, len(MAGIC), end):
            if isinstance(rec, Header):
                w.start(profile=rec.profile, library=rec.library)
            elif isinstance(rec, Schema):
                schema_map[rec.id] = w.register_schema(rec.name, rec.encoding, rec.data)
            elif isinstance(rec, Channel):
                chan_map[rec.id] = w.register_channel(rec.topic, rec.message_encoding, schema_map[rec.schema_id],
                                                      rec.metadata)
                ch_by_topic[rec.topic], topics[rec.id] = chan_map[rec.id], rec.topic
            elif isinstance(rec, Message):
                topic = topics[rec.channel_id]
                if topic == "/miniview/run" and base is None:
                    base = rec.log_time
                has_end = has_end or topic == "/miniview/end"
                last_ns = max(last_ns, rec.log_time)
                w.add_message(chan_map[rec.channel_id], rec.log_time, rec.data, rec.publish_time, rec.sequence)
        if stopped and not has_end and base is not None:
            for topic, ns, pub, data in wire.to_messages((last_ns - base) / 1e9, "end", {"verdict": "stopped"}, base):
                w.add_message(ch_by_topic[topic], ns, data, pub)
        w.finish()
    os.replace(tmp, final)
    live.unlink()
    (run_dir / LOCK).unlink(missing_ok=True)
    return final


def write(run_dir: Path, run: dict, records) -> Path:
    """A finished run in one go (tests, imports without a follow)."""
    rec = Recorder(run_dir, run)
    for t, kind, p in records:
        rec.add(t, kind, p)
    return rec.close()


class Follower:
    """Reads the records added to a run's file since the last call; safe on a file still being written.
    The compacted file, once it exists, is read from the message after the last one taken from the live file."""

    def __init__(self, run_dir: Path, keep_raw: bool = False):
        self.dir = Path(run_dir)
        self.keep_raw = keep_raw
        self.asm = wire.Assembler(keep_raw)
        self.offset = 0
        self.topics = {}
        self.taken = 0            # messages read from the live file
        self.done = False         # run.mcap was read: the run is complete
        self.partials = 0
        self.ino = None           # the live file's identity: a different one, or a shorter one, was rewritten
        self.generation = 0       # counts the starts over (a rewritten file is read again from its first byte)
        self.rewrites = 0
        self.errors = []          # messages that were not what they said, not yet taken

    def take_errors(self) -> list:
        out, self.errors = self.errors, []
        return out

    def _start_over(self) -> None:
        self.asm = wire.Assembler(self.keep_raw)
        self.offset, self.topics, self.taken, self.partials = 0, {}, 0, 0
        self.generation += 1
        self.rewrites += 1

    def poll(self) -> list:
        if self.done:
            return []
        final, live = self.dir / FINAL, self.dir / LIVE
        if final.exists():
            return self._read_final(final)
        if not live.exists():
            return []
        st = live.stat()
        if self.ino is not None and (st.st_ino != self.ino or st.st_size < self.offset):
            self._start_over()
        self.ino = st.st_ino
        with open(live, "rb") as fh:
            fh.seek(self.offset)
            buf = fh.read()
        pos = 0
        if self.offset == 0:
            if len(buf) < len(MAGIC):
                return []
            if buf[:len(MAGIC)] != MAGIC:
                raise ValueError(f"{live}: not an MCAP file")
            pos = len(MAGIC)
        end = _complete_end(buf, pos)
        out = self._take(_records(buf, pos, end), 0)
        self.offset += end
        return out

    def _read_final(self, final: Path) -> list:
        buf = final.read_bytes()
        if buf[:len(MAGIC)] != MAGIC:
            raise ValueError(f"{final}: not an MCAP file")
        it = StreamReader(io.BytesIO(buf[len(MAGIC):]), skip_magic=True).records
        out = self._take(self._tolerant(it), self.taken, fresh=True)
        self.done = True
        return out

    @staticmethod
    def _tolerant(it):
        while True:
            try:
                yield next(it)
            except (StopIteration, EndOfFile):
                return

    def _take(self, recs, skip: int, fresh: bool = False) -> list:
        topics = {} if fresh else self.topics
        out, seen = [], 0
        for rec in recs:
            if isinstance(rec, Channel):
                topics[rec.id] = rec.topic
            elif isinstance(rec, Message):
                seen += 1
                if seen <= skip:
                    continue
                try:
                    out += self.asm.feed(topics[rec.channel_id], rec.log_time, rec.data)
                except Exception as e:      # one message that is not what its channel says costs that record only
                    self.asm.pending = None
                    self.errors.append(f"{topics.get(rec.channel_id)} at {rec.log_time}: {type(e).__name__}: {e}")
        if not fresh:
            self.taken += seen
        self.partials = self.asm.partials
        return out


def read(run_dir: Path, keep_raw: bool = False) -> list:
    return Follower(run_dir, keep_raw).poll()
