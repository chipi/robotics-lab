"""Runs as MCAP files, format 2 (ADR-0007): written so they can be followed while they grow, closed into
a compact, indexed file.

    <run>/run.live.mcap + writer.lock   while written: unchunked, flushed after every record
    <run>/run.mcap                      when done: zstd chunks, message indexes, summary

`Recorder` is the only writer (the lock is created exclusively). `Follower` reads only complete
records, resumes where it stopped, and reads the compacted file the same way, so one reader serves a
finished run and a live one. The messages' shapes are in `runfile.wire`.
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

from runfile import keys, schemas, wire

FORMAT = 2
LIVE, FINAL, LOCK = "run.live.mcap", "run.mcap", "writer.lock"
MAGIC = b"\x89MCAP0\r\n"
PROFILE = "miniview"
VERSION = "0.2"


class WriterBusy(Exception):
    """The run already exists or has a writer."""


def new_run(key: str, robot: dict, scene: str, kind: str, started_at_ns: int, started_at_source: str = "writer",
            source: dict | None = None, run_uuid: str | None = None, signals: list | None = None,
            odometry: dict | None = None, no_pose: str | None = None, writer: dict | None = None,
            goal_run: dict | None = None) -> dict:
    """The run record. `signals` declares the robot's named values (runfile.signals); `odometry` says how the pose was
    computed, `no_pose` why there is none (a robot with signals only); `writer` names the program that writes the run;
    `goal_run` says which goal run of Mission Control the run is, {id, name, kind, ...} (RFC-0014 §3.11 item 4)."""
    keys.split_key(key)
    rec = {"format": FORMAT, "key": key, "uuid": run_uuid or str(uuidlib.uuid4()), "robot": robot, "scene": scene,
           "kind": kind, "started_at_ns": int(started_at_ns), "started_at_source": started_at_source,
           "writer": writer or {"program": "miniview", "version": VERSION}}
    for k, v in (("source", source), ("signals", signals), ("odometry", odometry), ("no_pose", no_pose), ("goal_run", goal_run)):
        if v:
            rec[k] = v
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
    """A lock whose PID is alive on this host. A lock from another host (a writer in another container or on
    another machine) cannot be checked: it is unknown, not alive, and the file's growth decides (ADR-0009)."""
    info = lock_info(run_dir)
    if not info or info.get("host") != socket.gethostname():
        return False
    return pid_alive(int(info.get("pid", 0)))


def lock_is_foreign(run_dir: Path) -> bool:
    info = lock_info(run_dir)
    return bool(info) and info.get("host") != socket.gethostname()


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
        self._tick = None             # the tick being written in parts: {"t", "src", "next"}
        self._w = Writer(self._fh, use_chunking=False, compression=CompressionType.NONE)
        self._w.start(profile=PROFILE, library=f"miniview {VERSION}")
        # A channel is written with its first message: a run without raw frames has no /depth/raw, and Lichtblick opens no
        # empty Image panel for it.
        self._ch, self._sid = {}, {}
        self.sigs = wire.signal_set(run)
        if self.sigs:
            sid = self._w.register_schema("miniview.Signals", "protobuf", self.sigs.descriptor_set)
            self._ch[self.sigs.topic] = self._w.register_channel(self.sigs.topic, "protobuf", sid)
        self._emit(0.0, "run", run)

    def channel(self, topic: str) -> int:
        """The channel id of one of wire.CHANNELS' topics, registered (with its schema) on first use."""
        return _channel(self._w, self._ch, self._sid, topic)

    def _write(self, messages) -> None:
        for topic, ns, pub, data in messages:
            self._w.add_message(self.channel(topic), ns, data, pub)

    def _emit(self, t: float, kind: str, p: dict) -> None:
        self._write(wire.to_messages(t, kind, p, self.base_ns, self.sigs))
        self._fh.flush()                      # once per record: a tick or a map is on disk whole or not at all

    # The tick protocol (ADR-0007), for a writer that has the parts of a tick one by one: begin_tick writes /belief/pose,
    # then at most one each of tick_truth, tick_depth, tick_command, tick_tilt, in that order, then end_tick writes
    # /miniview/tick_extra and flushes. Nothing else may be written in between; `add(t, "tick", ...)` is the same in one call.
    # A signals tick (ADR-0013) is begin_signals, then end_tick: the robot's named values at t, with no pose.
    def begin_tick(self, t: float, belief, t_src: float | None = None) -> None:
        self._check_open(t)
        msg = wire.tick_part("belief", t, belief, self.base_ns, t_src)     # built first: a value that cannot be encoded leaves no tick open
        self._tick = {"t": t, "src": t_src, "next": 0}
        self.last_t = max(self.last_t, t)
        self._write([msg])

    def _part(self, name: str, value, **kw) -> None:
        tk = self._tick
        if tk is None:
            raise ValueError(f"{name} outside a tick: begin_tick first")
        order = wire.TICK_PARTS
        if order.index(name) < tk["next"]:
            raise ValueError(f"{name} out of order or twice in a tick (the order is {', '.join(order)})")
        tk["next"] = order.index(name) + 1
        self._write([wire.tick_part(name, tk["t"], value, self.base_ns, tk["src"], **kw)])

    def tick_truth(self, pose, truth_3d: dict | None = None) -> None:
        """The truth's [x, y, yaw]; with `truth_3d` ({z, quat: [w, x, y, z]}, ADR-0016) its height and whole orientation too."""
        self._part("truth", pose, truth_3d=truth_3d)

    def tick_depth(self, points) -> None:
        self._part("depth", points)

    def tick_command(self, vx: float, vyaw: float) -> None:
        self._part("cmd", [vx, vyaw])

    def tick_tilt(self, pitch_deg: float, roll_deg: float) -> None:
        self._part("tilt", [pitch_deg, roll_deg])

    def begin_signals(self, t: float, values: dict, t_src: float | None = None) -> None:
        """A signals tick (ADR-0013): the robot's named values at t, with no pose; `end_tick` closes it, nothing between."""
        if self.sigs is None:
            raise ValueError("the run declares no signals")
        self._check_open(t)
        msg = wire.signals_part(t, values, self.base_ns, self.sigs, t_src)    # built first: a value that cannot be encoded leaves no tick open
        self._tick = {"t": t, "src": t_src, "next": len(wire.TICK_PARTS)}
        self.last_t = max(self.last_t, t)
        self._write([msg])

    def end_tick(self, raw: dict | None = None) -> None:
        tk = self._tick
        if tk is None:
            raise ValueError("end_tick without begin_tick")
        self._write([wire.tick_part("extra", tk["t"], raw or {}, self.base_ns, tk["src"])])
        self._tick = None
        self._fh.flush()

    def _check_open(self, t: float) -> None:
        if self.ended:
            raise ValueError("the run has ended")
        if self._tick is not None:
            raise ValueError("a tick is open: end_tick before anything else is written")
        if t < self.last_t - 1e-9:
            raise ValueError(f"time goes back: {t} after {self.last_t}")

    def add(self, t: float, kind: str, payload: dict) -> None:
        self._check_open(t)
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


BLOCK = 1 << 20           # what the live reader takes of the file at a time
VALID_OPS = range(0x01, 0x10)
MAX_RECORD = 1 << 31      # a length past this is garbage, not a record


def _complete_end(buf: bytes, pos: int) -> int:
    """The offset after the last whole record in buf[pos:]; stops at a footer's DATA_END."""
    end = pos
    while end + 9 <= len(buf):
        op, length = struct.unpack_from("<BQ", buf, end)
        if op == Opcode.DATA_END or end + 9 + length > len(buf):
            break
        end += 9 + length
    return end


def _looks_wrong(buf: bytes, pos: int) -> bool:
    """The bytes at a record boundary are not a record: the file is not what the reader has read so far."""
    if pos + 9 > len(buf):
        return False
    op, length = struct.unpack_from("<BQ", buf, pos)
    return op not in VALID_OPS or length > MAX_RECORD


def _records(buf: bytes, pos: int, end: int):
    it = StreamReader(io.BytesIO(buf[pos:end]), skip_magic=True).records
    while True:
        try:
            yield next(it)
        except (StopIteration, EndOfFile):
            return


class _Limited:
    """A file read as if it ended at `end`: what a reader of a live file may use of it."""

    def __init__(self, fh, end: int):
        self.fh, self.end = fh, end

    def read(self, n: int = -1) -> bytes:
        left = self.end - self.fh.tell()
        return self.fh.read(left if n < 0 else min(n, left))


def _scan_end(fh, size: int) -> int:
    """The offset after the last whole record of a file (after the magic), by reading record headers only."""
    pos = len(MAGIC)
    while pos + 9 <= size:
        fh.seek(pos)
        op, length = struct.unpack("<BQ", fh.read(9))
        if op == Opcode.DATA_END or pos + 9 + length > size:
            break
        pos += 9 + length
    return pos


def _channel(w: Writer, by_topic: dict, schema_ids: dict, topic: str) -> int:
    if topic not in by_topic:
        name = wire.CHANNELS[topic]
        if name not in schema_ids:
            schema_ids[name] = w.register_schema(name, *schemas.schema_for(name))
        by_topic[topic] = w.register_channel(topic, "protobuf" if topic in wire.PROTO else "json", schema_ids[name])
    return by_topic[topic]


def compact(run_dir: Path, stopped: bool = False, require_end: bool = False) -> Path:
    """run.live.mcap -> run.mcap (zstd chunks, message indexes, summary), streamed: the live file is read record by
    record, never held whole. With `stopped`, a run with no `end` gets one with the verdict `stopped` (a writer that
    died); with `require_end`, a run with no `end` is refused (ValueError) and nothing changes. Removes the live file and
    the lock. Runs wherever the file is: the writer's computer need not do it (ADR-0007)."""
    run_dir = Path(run_dir)
    live, tmp, final = run_dir / LIVE, run_dir / (FINAL + ".tmp"), run_dir / FINAL
    schema_map, chan_map, ch_by_topic, topics = {}, {}, {}, {}
    base, last_ns, has_end = None, 0, False
    with open(live, "rb") as src, open(tmp, "wb") as fh:
        if src.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{live}: not an MCAP file")
        end = _scan_end(src, live.stat().st_size)
        src.seek(len(MAGIC))
        w = Writer(fh, use_chunking=True, compression=CompressionType.ZSTD)
        it = StreamReader(_Limited(src, end), skip_magic=True).records
        while True:
            try:
                rec = next(it)
            except (StopIteration, EndOfFile):
                break
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
        if require_end and not has_end:
            raise ValueError(f"{run_dir.name}: the file has no end record; `miniview repair` closes it as stopped")
        if stopped and not has_end and base is not None:
            for topic, ns, pub, data in wire.to_messages((last_ns - base) / 1e9, "end", {"verdict": "stopped"}, base):
                w.add_message(_channel(w, ch_by_topic, {}, topic), ns, data, pub)
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
    """Reads the records added to a run's file since the last call; safe on a file still being written, and bounded in
    memory (the file is read a block at a time). The compacted file, once it exists, is read from the message after the
    last one taken from the live file. `iter_poll` yields the records as they are decoded; `poll` collects them."""

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
        out, gen = [], self.generation
        for rec in self.iter_poll():
            if self.generation != gen:          # the file was found rewritten while reading: what came before is stale
                out, gen = [], self.generation
            out.append(rec)
        return [] if self.generation != gen else out

    def iter_poll(self):
        if self.done:
            return
        final, live = self.dir / FINAL, self.dir / LIVE
        if final.exists():
            yield from self._iter_final(final)
        elif live.exists():
            yield from self._iter_live(live)

    def _iter_live(self, live: Path):
        st = live.stat()
        if self.ino is not None and (st.st_ino != self.ino or st.st_size < self.offset):
            self._start_over()
        self.ino = st.st_ino
        block = BLOCK
        with open(live, "rb") as fh:
            while True:
                fh.seek(self.offset)
                buf = fh.read(block)
                pos = 0
                if self.offset == 0:
                    if len(buf) < len(MAGIC):
                        return
                    if buf[:len(MAGIC)] != MAGIC:
                        raise ValueError(f"{live}: not an MCAP file")
                    pos = len(MAGIC)
                if self.offset > 0 and _looks_wrong(buf, 0):      # the same file, cut and rewritten, longer than we had read
                    self._start_over()
                    continue
                end = _complete_end(buf, pos)
                if end == pos and len(buf) >= block:               # a record bigger than the block: take a bigger one
                    block *= 2
                    continue
                yield from self._iter_take(_records(buf, pos, end), 0)
                self.offset += end
                if len(buf) < block or end == pos:
                    return

    def _iter_final(self, final: Path):
        with open(final, "rb") as fh:
            if fh.read(len(MAGIC)) != MAGIC:
                raise ValueError(f"{final}: not an MCAP file")
            it = StreamReader(fh, skip_magic=True).records
            yield from self._iter_take(self._tolerant(it), self.taken, fresh=True)
        self.done = True

    @staticmethod
    def _tolerant(it):
        while True:
            try:
                yield next(it)
            except (StopIteration, EndOfFile):
                return

    def _iter_take(self, recs, skip: int, fresh: bool = False):
        topics = {} if fresh else self.topics
        seen = 0
        try:
            for rec in recs:
                if isinstance(rec, Channel):
                    topics[rec.id] = rec.topic
                elif isinstance(rec, Message):
                    seen += 1
                    if seen <= skip:
                        continue
                    try:
                        yield from self.asm.feed(topics[rec.channel_id], rec.log_time, rec.data)
                    except Exception as e:      # one message that is not what its channel says costs that record only
                        self.asm.pending = None
                        self.errors.append(f"{topics.get(rec.channel_id)} at {rec.log_time}: {type(e).__name__}: {e}")
                    self.errors += self.asm.drain()
        finally:
            if not fresh:
                self.taken += seen
            self.partials = self.asm.partials


def read(run_dir: Path, keep_raw: bool = False) -> list:
    return Follower(run_dir, keep_raw).poll()
