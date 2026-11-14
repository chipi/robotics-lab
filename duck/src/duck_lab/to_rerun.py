"""Our MCAP runs as Rerun recordings (.rrd), for the viewer spike (RFC-0007 §4).

Rerun imports MCAP but keeps JSON messages as opaque blobs; it decodes protobuf and ROS 2. So this
reads our JSON topics and logs them with Rerun's own types: poses as 3D transforms and paths, numbers
as scalar plots, the command log as text.

    uv run duck-to-rerun runs/duck-apartment-walk.mcap -o duck.rrd
    uv run rerun duck.rrd --web-viewer     # or open the .rrd in the Rerun app
"""

import argparse
import json
from pathlib import Path

import rerun as rr
from mcap.reader import make_reader


def numbers(prefix: str, value, out: dict) -> None:
    """Flatten nested JSON into {"a/b/c": number} for scalar plots."""
    if isinstance(value, bool):
        out[prefix] = float(value)
    elif isinstance(value, (int, float)):
        out[prefix] = float(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            numbers(f"{prefix}/{k}" if prefix else str(k), v, out)
    elif isinstance(value, list) and len(value) <= 16:
        for i, v in enumerate(value):
            numbers(f"{prefix}/{i}", v, out)


def convert(src: Path, dst: Path) -> dict:
    rr.init(f"robotics-lab-{src.stem}", spawn=False)
    rr.save(str(dst))
    paths = {"/duck/pose": [], "/duck/truth": []}
    counts = {}
    with open(src, "rb") as f:
        for _schema, channel, message in make_reader(f).iter_messages(log_time_order=True):
            rr.set_time("log_time", timestamp=message.log_time * 1e-9)
            data = json.loads(message.data)
            topic = channel.topic
            counts[topic] = counts.get(topic, 0) + 1
            if topic in paths:
                p, q = data["pose"]["position"], data["pose"]["orientation"]
                xyz = [p["x"], p["y"], p["z"]]
                frame = "odom" if topic == "/duck/pose" else "world"
                rr.log(f"{frame}/duck", rr.Transform3D(translation=xyz,
                                                       quaternion=rr.Quaternion(xyzw=[q["x"], q["y"], q["z"], q["w"]])))
                paths[topic].append(xyz)
                rr.log(f"{frame}/path", rr.LineStrips3D([paths[topic]]))
            elif topic == "/duck/state":
                flat = {}
                for key in ("odom", "imu", "move", "velocities", "safety"):
                    if key in data:
                        numbers(key, data[key], flat)
                for name, v in flat.items():
                    rr.log(f"duck/state/{name}", rr.Scalars(v))
            elif topic == "/nxt/state":
                flat = {}
                numbers("", {k: data[k] for k in ("power_left", "power_right", "tacho") if k in data}, flat)
                for port, reading in (data.get("sensors") or {}).items():
                    if isinstance(reading.get("value"), (int, float)):
                        flat[f"sensor_{port}"] = float(reading["value"])
                for name, v in flat.items():
                    rr.log(f"nxt/{name}", rr.Scalars(v))
            elif topic == "/nxt/events":
                detail = " ".join(f"{k}={v}" for k, v in data.items() if k not in ("seq", "at", "kind", "ok"))
                rr.log("nxt/events", rr.TextLog(f"{data['kind']} {detail}".strip(),
                                                level="INFO" if data.get("ok", True) else "ERROR"))
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()
    out = args.out or args.src.with_suffix(".rrd")
    counts = convert(args.src, out)
    print(f"wrote {out}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
