"""One look at Nav2's two costmaps (RFC-0015 §4 step 2, checks 1, 2, 3 and 5): for each, its size and the number of cells that are
unknown (-1), free (0), costed (1-252), inscribed (253) and lethal (254), and the lethal cells' bounding box. Prints for the
`/local_costmap/costmap` and `/global_costmap/costmap` topics (transient-local, as Nav2 publishes them).
    python3 costmap_probe.py [label]
"""

import sys
import time

import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy


def summary(label: str, m: OccupancyGrid) -> str:
    d = list(m.data)
    n = {"unknown": sum(v == -1 for v in d), "free": sum(v == 0 for v in d), "costed": sum(1 <= v <= 252 for v in d),
         "inscribed": sum(v == 253 for v in d), "lethal": sum(v == 254 or v == 100 for v in d)}
    w, r = m.info.width, m.info.resolution
    lethal = [(i % w, i // w) for i, v in enumerate(d) if v in (254, 100)]
    box = "none"
    if lethal:
        xs, ys = [c[0] for c in lethal], [c[1] for c in lethal]
        ox, oy = m.info.origin.position.x, m.info.origin.position.y
        box = f"x {ox + min(xs) * r:.2f}..{ox + (max(xs) + 1) * r:.2f}, y {oy + min(ys) * r:.2f}..{oy + (max(ys) + 1) * r:.2f}"
    return (f"{label}: {w}x{m.info.height} at {r} m, origin ({m.info.origin.position.x:.2f}, {m.info.origin.position.y:.2f}), "
            f"frame {m.header.frame_id}, {n}, lethal box {box}")


def main() -> None:
    rclpy.init()
    node = Node("costmap_probe")
    got = {}
    qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
    for name in ("local_costmap", "global_costmap"):
        node.create_subscription(OccupancyGrid, f"/{name}/costmap", lambda m, n=name: got.setdefault(n, m), qos)
    t0 = time.time()
    while len(got) < 2 and time.time() - t0 < 10:
        rclpy.spin_once(node, timeout_sec=0.5)
    for name in ("local_costmap", "global_costmap"):
        print(summary((sys.argv[1] + " " if len(sys.argv) > 1 else "") + name, got[name]) if name in got else f"{name}: not published")


if __name__ == "__main__":
    main()
