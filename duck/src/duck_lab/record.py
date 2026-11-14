"""Record a Microduck run as MCAP (RFC-0007): robotd's state stream, and in the simulator its ground
truth, so the same file opens in Foxglove, Lichtblick or Rerun.

    uv run duck-record runs/duck-run.mcap --seconds 30            # simulator (duck-sim's sockets)
    uv run duck-record out.mcap --robot-socket /run/robotd.sock --no-truth   # a real duck

Topics (JSON with JSON Schemas):
- /duck/state  every robot.state notification from robotd (robot.subscribe), as robotd sends it
- /duck/pose   odometry as foxglove.PoseInFrame (frame "odom"), so 3D panels can draw it
- /duck/truth  the simulator's trunk pose as foxglove.PoseInFrame (frame "world"); simulator only
- /tf          the same poses as foxglove.FrameTransform (world → trunk_truth, odom → trunk_odom,
               and world → odom with each), which 3D panels need to know the frames

    uv run duck-record --add-frames old.mcap new.mcap   # add /tf to a file recorded without it
"""

import argparse
import json
import math
import os
import socket
import threading
import time
from pathlib import Path

from mcap.writer import CompressionType, Writer

SIM = Path(os.path.expanduser("~/.cache/duck-sim"))

STATE_SCHEMA = {"type": "object", "title": "microduck.RobotState",
                "description": "robotd's robot.state notification params, unchanged"}
POSE_SCHEMA = {
    "title": "foxglove.PoseInFrame",
    "type": "object",
    "properties": {
        "timestamp": {"type": "object", "properties": {"sec": {"type": "integer"}, "nsec": {"type": "integer"}}},
        "frame_id": {"type": "string"},
        "pose": {"type": "object", "properties": {
            "position": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                                          "z": {"type": "number"}}},
            "orientation": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                                             "z": {"type": "number"}, "w": {"type": "number"}}},
        }},
    },
}


TF_SCHEMA = {
    "title": "foxglove.FrameTransform",
    "type": "object",
    "properties": {
        "timestamp": {"type": "object", "properties": {"sec": {"type": "integer"}, "nsec": {"type": "integer"}}},
        "parent_frame_id": {"type": "string"},
        "child_frame_id": {"type": "string"},
        "translation": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                                         "z": {"type": "number"}}},
        "rotation": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                                      "z": {"type": "number"}, "w": {"type": "number"}}},
    },
}


def frame_transform(pose: dict, child: str) -> dict:
    """A PoseInFrame as the transform from its frame to `child`: what 3D panels build frames from.
    /duck/truth becomes world → trunk_truth, /duck/pose becomes odom → trunk_odom."""
    return {"timestamp": pose["timestamp"], "parent_frame_id": pose["frame_id"], "child_frame_id": child,
            "translation": pose["pose"]["position"], "rotation": pose["pose"]["orientation"]}


def pose_in_frame(t_ns: int, frame: str, pos, quat_wxyz) -> dict:
    w, x, y, z = quat_wxyz
    return {"timestamp": {"sec": t_ns // 1_000_000_000, "nsec": t_ns % 1_000_000_000}, "frame_id": frame,
            "pose": {"position": {"x": pos[0], "y": pos[1], "z": pos[2] if len(pos) > 2 else 0.0},
                     "orientation": {"x": x, "y": y, "z": z, "w": w}}}


CHILD_FRAMES = {"/duck/truth": "trunk_truth", "/duck/pose": "trunk_odom"}


def yaw_quat(yaw: float) -> tuple:
    return (math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2))


class Recorder:
    def __init__(self, path: Path, metadata: dict):
        self._file = open(path, "wb")
        self._writer = Writer(self._file, compression=CompressionType.ZSTD)
        self._writer.start(profile="", library="duck-lab")
        self._lock = threading.Lock()
        self._channels, self._seq, self.counts = {}, {}, {}
        for topic, schema in (("/duck/state", STATE_SCHEMA), ("/duck/pose", POSE_SCHEMA),
                              ("/duck/truth", POSE_SCHEMA), ("/tf", TF_SCHEMA)):
            sid = self._writer.register_schema(name=schema["title"], encoding="jsonschema",
                                               data=json.dumps(schema).encode())
            self._channels[topic] = self._writer.register_channel(topic=topic, message_encoding="json", schema_id=sid)
            self._seq[topic] = self.counts[topic] = 0
        self._writer.add_metadata("duck_lab.run", {k: str(v) for k, v in metadata.items()})

    def write(self, topic: str, message: dict, log_time_ns: int | None = None) -> None:
        now = log_time_ns or time.time_ns()
        with self._lock:
            self._write(topic, message, now)
            if topic in CHILD_FRAMES:
                # odom placed at the world origin (where the simulated robot boots). Sent with every
                # pose, as robots publish it: viewers keep a transform only for a while, and one sent
                # once at the start was "missing" in Lichtblick later in the run.
                self._write("/tf", {"timestamp": message["timestamp"], "parent_frame_id": "world",
                                    "child_frame_id": "odom", "translation": {"x": 0.0, "y": 0.0, "z": 0.0},
                                    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}, now)
                self._write("/tf", frame_transform(message, CHILD_FRAMES[topic]), now)

    def _write(self, topic: str, message: dict, now: int) -> None:
        self._seq[topic] += 1
        self.counts[topic] += 1
        self._writer.add_message(channel_id=self._channels[topic], log_time=now, publish_time=now,
                                 sequence=self._seq[topic], data=json.dumps(message).encode())

    def close(self) -> None:
        with self._lock:
            self._writer.finish()
            self._file.close()


def record_state(rec: Recorder, robot_socket: Path, hz: int, stop: threading.Event) -> None:
    s = socket.socket(socket.AF_UNIX)
    s.connect(str(robot_socket))
    s.settimeout(1.0)
    f = s.makefile("rw")
    f.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "robot.subscribe", "params": {"hz": hz}}) + "\n")
    f.flush()
    while not stop.is_set():
        try:
            line = f.readline()
        except (TimeoutError, socket.timeout):
            continue
        if not line:
            break
        msg = json.loads(line)
        if msg.get("method") != "robot.state":
            continue
        state = msg["params"]
        rec.write("/duck/state", state)
        odom = state.get("odom") or {}
        if "position" in odom:
            rec.write("/duck/pose", pose_in_frame(time.time_ns(), "odom", odom["position"],
                                                  yaw_quat(odom.get("yaw", 0.0))))
    s.close()


def record_truth(rec: Recorder, port: int, hz: int, stop: threading.Event) -> None:
    body = socket.create_connection(("127.0.0.1", port)).makefile("rw")
    body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n"); body.flush(); body.readline()
    while not stop.is_set():
        body.write('{"op":"read"}\n'); body.flush()
        r = json.loads(body.readline())
        rec.write("/duck/truth", pose_in_frame(time.time_ns(), "world", r["trunk"], r["imu"]["quat"]))
        time.sleep(1.0 / hz)


def add_frames(src: Path, dst: Path) -> dict:
    """Rewrite a recording made without /tf, adding it from the poses."""
    from mcap.reader import make_reader

    with open(src, "rb") as f:
        reader = make_reader(f)
        meta = {m.name: m.metadata for m in reader.iter_metadata()}.get("duck_lab.run", {})
        rec = Recorder(dst, meta)
        for _schema, channel, message in reader.iter_messages(log_time_order=True):
            if channel.topic in rec.counts and channel.topic != "/tf":
                rec.write(channel.topic, json.loads(message.data), message.log_time)
    rec.close()
    return rec.counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path, nargs="?")
    ap.add_argument("--add-frames", nargs=2, type=Path, metavar=("OLD", "NEW"))
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--robot-socket", type=Path, default=SIM / "duck-a.sock")
    ap.add_argument("--hz", type=int, default=20, help="robotd state rate")
    ap.add_argument("--body-port", type=int, default=int(os.environ.get("DUCK_SIM_PORT", "7801")))
    ap.add_argument("--no-truth", action="store_true", help="a real duck: no simulator to ask")
    args = ap.parse_args()
    if args.add_frames:
        counts = add_frames(*args.add_frames)
        print(f"wrote {args.add_frames[1]}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        return
    if args.out is None:
        ap.error("the output file is required")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rec = Recorder(args.out, {"robot": "microduck", "simulator": not args.no_truth,
                              "scene": os.environ.get("DUCK_SIM_SCENE", ""), "state_hz": args.hz})
    stop = threading.Event()
    threads = [threading.Thread(target=record_state, args=(rec, args.robot_socket, args.hz, stop), daemon=True)]
    if not args.no_truth:
        threads.append(threading.Thread(target=record_truth, args=(rec, args.body_port, 10, stop), daemon=True))
    for t in threads:
        t.start()
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    stop.set()
    for t in threads:
        t.join(timeout=3)
    rec.close()
    print(f"wrote {args.out}: " + ", ".join(f"{k} {v}" for k, v in rec.counts.items()))


if __name__ == "__main__":
    main()
